#!/usr/bin/env bash
set -euo pipefail

helmfile_bin="${HELMFILE:-helmfile}"
helm_bin="${HELM:-helm}"
helmfile_config="${HELMFILE_CONFIG:-deploy/helmfile.yaml.gotmpl}"
kubeconfig_path="${OPERATOR_KUBECONFIG:-${KUBECONFIG:-${HOME}/.kube/config}}"
kubeconfig_script="${KUBECONFIG_SCRIPT:-scripts/tools/ensure-kubeconfig.sh}"
kubectl_bin="${KUBECTL:-kubectl}"
retries="${HELMFILE_SYNC_RETRIES:-4}"
retry_delay="${HELMFILE_SYNC_RETRY_DELAY:-20}"
sync_attempt_timeout="${HELMFILE_SYNC_ATTEMPT_TIMEOUT:-240}"
pending_wait_timeout="${HELMFILE_PENDING_WAIT_TIMEOUT:-180}"
pending_wait_delay="${HELMFILE_PENDING_WAIT_DELAY:-10}"
pending_rollback_timeout="${HELMFILE_PENDING_ROLLBACK_TIMEOUT:-10m}"
pending_release_specs="${HELMFILE_PENDING_RELEASES:-external-secrets:external-secrets cert-manager:cert-manager cloudnative-pg:cnpg-system eck-operator:elastic-system kube-prometheus-stack:observability opentelemetry-collector:observability loki:observability opensearch:observability clickhouse:observability}"
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

if ! command -v "${helm_bin}" >/dev/null 2>&1; then
  echo "helm is required to recover operator release locks." >&2
  exit 1
fi

diagnose_helmfile_output() {
  local output_file="$1"

  if grep -Eiq 'context deadline exceeded|Client\.Timeout|not a valid chart repository|cannot be reached' "${output_file}"; then
    echo "Helmfile detected a chart repository or network timeout during this attempt." >&2
    echo "Disabled optional stacks are skipped by the Helmfile template; if a disabled repo is named here, pull the latest repo code and rerun deploy-auto." >&2
  fi

  if grep -Eiq 'grafana\.github\.io|helm\.linkerd\.io|go\.temporal\.io' "${output_file}"; then
    echo "Helmfile touched an optional repository. That should only happen when the matching component is enabled." >&2
  fi
}

run_helmfile_sync() {
  local output_file
  local status

  output_file="$(mktemp "${TMPDIR:-/tmp}/urban-platform-helmfile.XXXXXX.log")"
  set +e
  if command -v timeout >/dev/null 2>&1 && [ "${sync_attempt_timeout}" != "0" ]; then
    KUBECONFIG="${kubeconfig_path}" timeout "${sync_attempt_timeout}" "${helmfile_bin}" -f "${helmfile_config}" sync 2>&1 | tee "${output_file}"
    status="${PIPESTATUS[0]}"
  else
    KUBECONFIG="${kubeconfig_path}" "${helmfile_bin}" -f "${helmfile_config}" sync 2>&1 | tee "${output_file}"
    status="${PIPESTATUS[0]}"
  fi
  set -e

  diagnose_helmfile_output "${output_file}" || true
  rm -f "${output_file}"

  if [ "${status}" -eq 124 ]; then
    echo "Helmfile sync attempt timed out after ${sync_attempt_timeout}s; retry control will continue if attempts remain." >&2
  fi
  return "${status}"
}

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

helm_release_status() {
  local release="$1"
  local namespace="$2"

  KUBECONFIG="${kubeconfig_path}" "${helm_bin}" status "${release}" -n "${namespace}" 2>/dev/null \
    | awk -F': *' '$1 == "STATUS" {print $2; exit}' || true
}

last_deployed_revision() {
  local release="$1"
  local namespace="$2"

  KUBECONFIG="${kubeconfig_path}" "${helm_bin}" history "${release}" -n "${namespace}" -o json 2>/dev/null \
    | python3 -c '
import json
import sys

try:
    rows = json.load(sys.stdin)
except Exception:
    rows = []

revision = ""
for row in rows:
    if str(row.get("status", "")).lower() == "deployed":
        revision = str(row.get("revision", ""))
print(revision)
' || true
}

latest_pending_release_secret() {
  local release="$1"
  local namespace="$2"

  KUBECONFIG="${kubeconfig_path}" "${kubectl_bin}" -n "${namespace}" get secret \
    -l "owner=helm,name=${release}" \
    --sort-by=.metadata.creationTimestamp \
    -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.labels.status}{"\n"}{end}' 2>/dev/null \
    | awk '$2 ~ /^pending-/ {name=$1} END {print name}' || true
}

recover_pending_release() {
  local release="$1"
  local namespace="$2"
  local status
  local deadline
  local revision
  local pending_secret

  status="$(helm_release_status "${release}" "${namespace}")"
  # Recover stale Helm locks that later surface as "another operation is in progress".
  case "${status}" in
    pending-*)
      ;;
    *)
      return 0
      ;;
  esac

  echo "Helm release ${release} in namespace ${namespace} is ${status}; waiting for the operation to finish."
  deadline="$(($(date +%s) + pending_wait_timeout))"
  while [ "$(date +%s)" -lt "${deadline}" ]; do
    sleep "${pending_wait_delay}"
    status="$(helm_release_status "${release}" "${namespace}")"
    case "${status}" in
      pending-*)
        echo "Helm release ${release} is still ${status}; waiting."
        ;;
      *)
        echo "Helm release ${release} left pending state (${status:-not found})."
        return 0
        ;;
    esac
  done

  revision="$(last_deployed_revision "${release}" "${namespace}")"
  if [ -n "${revision}" ]; then
    echo "Rolling back stale pending Helm release ${release} to deployed revision ${revision}."
    if KUBECONFIG="${kubeconfig_path}" "${helm_bin}" rollback "${release}" "${revision}" -n "${namespace}" --wait --timeout "${pending_rollback_timeout}"; then
      return 0
    fi
    echo "Helm rollback for ${release} failed; attempting pending secret cleanup." >&2
  else
    echo "No deployed revision found for pending Helm release ${release}; attempting pending secret cleanup." >&2
  fi

  pending_secret="$(latest_pending_release_secret "${release}" "${namespace}")"
  if [ -n "${pending_secret}" ]; then
    echo "Deleting stale Helm pending secret ${pending_secret} for ${release}."
    KUBECONFIG="${kubeconfig_path}" "${kubectl_bin}" -n "${namespace}" delete secret "${pending_secret}" --ignore-not-found
    return 0
  fi

  echo "Could not recover pending Helm release ${release}; no stale pending secret found." >&2
  return 1
}

recover_pending_releases() {
  local spec
  local release
  local namespace

  for spec in ${pending_release_specs}; do
    release="${spec%%:*}"
    namespace="${spec#*:}"
    if [ -z "${release}" ] || [ -z "${namespace}" ] || { [ "${release}" = "${namespace}" ] && [[ "${spec}" != *:* ]]; }; then
      continue
    fi
    recover_pending_release "${release}" "${namespace}" || return 1
  done
}

attempt=1
while true; do
  echo "Running helmfile sync (attempt ${attempt}/${retries}, attempt timeout ${sync_attempt_timeout}s)."
  status=0
  if wait_for_stable_api && recover_pending_releases; then
    if run_helmfile_sync; then
      exit 0
    fi
    status=$?
  else
    status=$?
  fi

  if [ "${attempt}" -ge "${retries}" ]; then
    echo "helmfile sync failed after ${retries} attempts." >&2
    exit "${status}"
  fi

  refresh_kubeconfig || true
  echo "helmfile sync attempt ${attempt}/${retries} failed; retrying in ${retry_delay}s." >&2
  sleep "${retry_delay}"
  attempt=$((attempt + 1))
done
