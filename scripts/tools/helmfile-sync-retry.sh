#!/usr/bin/env bash
set -euo pipefail

helmfile_bin="${HELMFILE:-helmfile}"
helmfile_config="${HELMFILE_CONFIG:-deploy/helmfile.yaml.gotmpl}"
kubeconfig_path="${OPERATOR_KUBECONFIG:-${KUBECONFIG:-${HOME}/.kube/config}}"
kubeconfig_script="${KUBECONFIG_SCRIPT:-scripts/tools/ensure-kubeconfig.sh}"
kubectl_bin="${KUBECTL:-kubectl}"
retries="${HELMFILE_SYNC_RETRIES:-4}"
retry_delay="${HELMFILE_SYNC_RETRY_DELAY:-20}"
api_wait_timeout="${HELMFILE_API_WAIT_TIMEOUT:-600}"
api_wait_delay="${HELMFILE_API_WAIT_DELAY:-15}"
api_stable_successes="${HELMFILE_API_STABLE_SUCCESSES:-2}"
api_ready_timeout="${HELMFILE_API_READY_TIMEOUT:-15s}"
api_version_timeout="${HELMFILE_API_VERSION_TIMEOUT:-15s}"
api_openapi_timeout="${HELMFILE_API_OPENAPI_TIMEOUT:-60s}"
migration_cluster_vip="${MIGRATION_CLUSTER_VIP:-${DEPLOY_CLUSTER_VIP:-}}"

if ! command -v "${helmfile_bin}" >/dev/null 2>&1; then
  echo "helmfile is required to install operators." >&2
  exit 1
fi

refresh_kubeconfig() {
  if [ ! -x "${kubeconfig_script}" ] && [ ! -f "${kubeconfig_script}" ]; then
    echo "Cannot refresh operator kubeconfig because ${kubeconfig_script} is missing." >&2
    return 1
  fi

  echo "Refreshing operator kubeconfig before Helmfile retry."
  OPERATOR_KUBECONFIG_FORCE_REPAIR=true \
    OPERATOR_KUBECONFIG="${kubeconfig_path}" \
    KUBECONFIG="${kubeconfig_path}" \
    MIGRATION_CLUSTER_VIP="${migration_cluster_vip}" \
    bash "${kubeconfig_script}"
}

api_probe_once() {
  local probe
  local path
  local timeout
  local output

  for probe in "/readyz:${api_ready_timeout}" "/version:${api_version_timeout}" "/openapi/v2:${api_openapi_timeout}"; do
    path="${probe%:*}"
    timeout="${probe#*:}"
    if ! output="$(KUBECONFIG="${kubeconfig_path}" "${kubectl_bin}" get --raw="${path}" --request-timeout="${timeout}" 2>&1 >/dev/null)"; then
      echo "Kubernetes API ${path} probe failed: ${output}" >&2
      return 1
    fi
  done
  return 0
}

wait_for_stable_api() {
  local deadline
  local consecutive=0

  if ! command -v "${kubectl_bin}" >/dev/null 2>&1; then
    echo "kubectl is required before running Helmfile." >&2
    return 1
  fi

  deadline="$(($(date +%s) + api_wait_timeout))"
  echo "Waiting for Kubernetes API stability before Helmfile: /readyz, /version, /openapi/v2."
  while [ "$(date +%s)" -lt "${deadline}" ]; do
    if api_probe_once; then
      consecutive=$((consecutive + 1))
      if [ "${consecutive}" -ge "${api_stable_successes}" ]; then
        echo "Kubernetes API is stable for Helmfile (${consecutive}/${api_stable_successes} successful probe rounds)."
        return 0
      fi
      sleep 3
      continue
    fi
    consecutive=0
    echo "Kubernetes API is not stable enough for Helmfile yet; retrying in ${api_wait_delay}s." >&2
    sleep "${api_wait_delay}"
  done

  echo "Kubernetes API did not become stable for Helmfile within ${api_wait_timeout}s." >&2
  return 1
}

attempt=1
while true; do
  echo "Running helmfile sync (attempt ${attempt}/${retries})."
  if wait_for_stable_api && KUBECONFIG="${kubeconfig_path}" "${helmfile_bin}" -f "${helmfile_config}" sync; then
    exit 0
  fi
  status=$?

  if [ "${attempt}" -ge "${retries}" ]; then
    echo "helmfile sync failed after ${retries} attempts." >&2
    exit "${status}"
  fi

  refresh_kubeconfig || true
  echo "helmfile sync attempt ${attempt}/${retries} failed; retrying in ${retry_delay}s." >&2
  sleep "${retry_delay}"
  attempt=$((attempt + 1))
done
