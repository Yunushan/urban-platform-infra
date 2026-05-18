#!/usr/bin/env bash
set -euo pipefail

version="${LOCAL_PATH_PROVISIONER_VERSION:-v0.0.35}"
storage_class="${LOCAL_PATH_STORAGE_CLASS:-local-path}"
make_default="${LOCAL_PATH_STORAGE_DEFAULT:-true}"
timeout="${LOCAL_PATH_ROLLOUT_TIMEOUT:-180s}"
manifest_url="${LOCAL_PATH_PROVISIONER_MANIFEST_URL:-https://raw.githubusercontent.com/rancher/local-path-provisioner/${version}/deploy/local-path-storage.yaml}"
request_timeout="${KUBECTL_REQUEST_TIMEOUT:-60s}"
retries="${KUBECTL_RETRIES:-8}"
retry_delay="${KUBECTL_RETRY_DELAY:-5}"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required to install local-path storage." >&2
  exit 1
fi

kubectl_retry() {
  local attempt=1
  local status=0

  while true; do
    if kubectl --request-timeout="${request_timeout}" "$@"; then
      return 0
    fi
    status=$?
    if [ "${attempt}" -ge "${retries}" ]; then
      echo "kubectl failed after ${retries} attempts: kubectl $*" >&2
      return "${status}"
    fi
    echo "kubectl attempt ${attempt}/${retries} failed: kubectl $*; retrying in ${retry_delay}s." >&2
    sleep "${retry_delay}"
    attempt=$((attempt + 1))
  done
}

echo "Installing local-path provisioner ${version} from ${manifest_url}"
kubectl_retry apply -f "${manifest_url}"

kubectl_retry -n local-path-storage rollout status deployment/local-path-provisioner --timeout="${timeout}"

if [ "${make_default}" = "true" ]; then
  kubectl_retry patch storageclass "${storage_class}" --type=merge \
    -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true","storageclass.beta.kubernetes.io/is-default-class":"true"}}}'
fi

kubectl_retry get storageclass "${storage_class}"
