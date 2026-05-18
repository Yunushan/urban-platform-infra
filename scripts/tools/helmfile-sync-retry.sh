#!/usr/bin/env bash
set -euo pipefail

helmfile_bin="${HELMFILE:-helmfile}"
helmfile_config="${HELMFILE_CONFIG:-deploy/helmfile.yaml.gotmpl}"
kubeconfig_path="${OPERATOR_KUBECONFIG:-${KUBECONFIG:-${HOME}/.kube/config}}"
kubeconfig_script="${KUBECONFIG_SCRIPT:-scripts/tools/ensure-kubeconfig.sh}"
retries="${HELMFILE_SYNC_RETRIES:-4}"
retry_delay="${HELMFILE_SYNC_RETRY_DELAY:-20}"
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

attempt=1
while true; do
  echo "Running helmfile sync (attempt ${attempt}/${retries})."
  if KUBECONFIG="${kubeconfig_path}" "${helmfile_bin}" -f "${helmfile_config}" sync; then
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
