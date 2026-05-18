#!/usr/bin/env bash
set -euo pipefail

version="${LOCAL_PATH_PROVISIONER_VERSION:-v0.0.35}"
storage_class="${LOCAL_PATH_STORAGE_CLASS:-local-path}"
make_default="${LOCAL_PATH_STORAGE_DEFAULT:-true}"
timeout="${LOCAL_PATH_ROLLOUT_TIMEOUT:-180s}"
manifest_url="${LOCAL_PATH_PROVISIONER_MANIFEST_URL:-https://raw.githubusercontent.com/rancher/local-path-provisioner/${version}/deploy/local-path-storage.yaml}"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required to install local-path storage." >&2
  exit 1
fi

echo "Installing local-path provisioner ${version} from ${manifest_url}"
kubectl apply -f "${manifest_url}"

kubectl -n local-path-storage rollout status deployment/local-path-provisioner --timeout="${timeout}"

if [ "${make_default}" = "true" ]; then
  kubectl patch storageclass "${storage_class}" --type=merge \
    -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true","storageclass.beta.kubernetes.io/is-default-class":"true"}}}'
fi

kubectl get storageclass "${storage_class}"
