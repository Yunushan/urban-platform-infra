#!/usr/bin/env bash
set -euo pipefail

release="${HELM_RELEASE_NAME:-${PROJECT:-urban-platform-infra}}"
namespace="${HELM_RELEASE_NAMESPACE:-${NAMESPACE:-urban-platform}}"
enabled="${RECOVER_HELM_RELEASE:-${DEPLOY_RECOVER_FAILED_RELEASE:-false}}"
cleanup_stale_resources="${RECOVER_STALE_RESOURCES:-${DEPLOY_RECOVER_STALE_RESOURCES:-true}}"
delete_pending_pvcs="${RECOVER_PENDING_PVCS:-${DEPLOY_RECOVER_PENDING_PVCS:-true}}"
delete_all_pvcs="${RECOVER_DELETE_PVCS:-${DEPLOY_RECOVER_DELETE_PVCS:-false}}"
timeout="${HELM_RECOVER_TIMEOUT:-${HELM_TIMEOUT:-10m}}"
request_timeout="${KUBECTL_REQUEST_TIMEOUT:-120s}"
selector="${HELM_RECOVER_SELECTOR:-app.kubernetes.io/part-of=urban-platform-infra}"
helm_bin="${HELM:-helm}"
kubectl_bin="${KUBECTL:-kubectl}"

if [ "${enabled}" != "true" ]; then
  echo "Helm recovery disabled for ${release}; set DEPLOY_RECOVER_FAILED_RELEASE=true to enable it."
  exit 0
fi

if ! command -v "${helm_bin}" >/dev/null 2>&1; then
  echo "helm is required for automatic release recovery." >&2
  exit 1
fi
if ! command -v "${kubectl_bin}" >/dev/null 2>&1; then
  echo "kubectl is required for automatic release recovery." >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required for automatic Helm status parsing." >&2
  exit 1
fi

kube() {
  "${kubectl_bin}" --request-timeout="${request_timeout}" "$@"
}

release_status() {
  "${helm_bin}" list -n "${namespace}" -a --filter "^${release}$" -o json 2>/dev/null \
    | python3 -c 'import json,sys; data=json.load(sys.stdin); print(data[0].get("status", "") if data else "")' 2>/dev/null || true
}

delete_if_supported() {
  local resource="$1"
  if kube api-resources --namespaced=true -o name 2>/dev/null | grep -qx "${resource}"; then
    kube -n "${namespace}" delete "${resource}" -l "${selector}" --ignore-not-found --timeout="${timeout}" || true
  fi
}

delete_stale_resources() {
  if [ "${cleanup_stale_resources}" != "true" ]; then
    return 0
  fi

  echo "Deleting stale ${release} resources labeled ${selector} in namespace ${namespace}."
  for resource in \
    deployments.apps \
    statefulsets.apps \
    daemonsets.apps \
    jobs.batch \
    ingresses.networking.k8s.io \
    services \
    configmaps \
    serviceaccounts \
    poddisruptionbudgets.policy \
    networkpolicies.networking.k8s.io \
    prometheusrules.monitoring.coreos.com \
    servicemonitors.monitoring.coreos.com \
    externalsecrets.external-secrets.io \
    elasticsearches.elasticsearch.k8s.elastic.co \
    kibanas.kibana.k8s.elastic.co \
    clusters.postgresql.cnpg.io \
    imagecatalogs.postgresql.cnpg.io \
    pods; do
    delete_if_supported "${resource}"
  done
}

delete_pvcs() {
  if [ "${delete_all_pvcs}" = "true" ]; then
    echo "Deleting all PVCs in namespace ${namespace} because DEPLOY_RECOVER_DELETE_PVCS=true."
    kube -n "${namespace}" delete pvc --all --ignore-not-found --timeout="${timeout}" || true
    return 0
  fi

  if [ "${delete_pending_pvcs}" != "true" ]; then
    return 0
  fi

  mapfile -t pending_pvcs < <(kube -n "${namespace}" get pvc --no-headers 2>/dev/null | awk '$2 == "Pending" {print $1}')
  if [ "${#pending_pvcs[@]}" -eq 0 ]; then
    echo "No Pending PVCs found in namespace ${namespace}."
    return 0
  fi

  echo "Deleting Pending PVCs in namespace ${namespace}: ${pending_pvcs[*]}"
  kube -n "${namespace}" delete pvc "${pending_pvcs[@]}" --ignore-not-found --timeout="${timeout}" || true
}

status="$(release_status)"
manifest_file=""

if [ "${status}" = "deployed" ]; then
  echo "Helm release ${release} is deployed; recovery is not needed."
  exit 0
fi

if [ -n "${status}" ]; then
  echo "Recovering Helm release ${release} from status ${status}."
  manifest_file="$(mktemp)"
  if ! "${helm_bin}" get manifest "${release}" -n "${namespace}" > "${manifest_file}" 2>/dev/null; then
    rm -f "${manifest_file}"
    manifest_file=""
  fi

  "${helm_bin}" uninstall "${release}" -n "${namespace}" --no-hooks --timeout "${timeout}" || true

  if [ -n "${manifest_file}" ] && [ -s "${manifest_file}" ]; then
    kube -n "${namespace}" delete -f "${manifest_file}" --ignore-not-found --timeout="${timeout}" || true
    rm -f "${manifest_file}"
  fi
else
  echo "No Helm release record found for ${release}; checking for stale resources before install."
fi

kube -n "${namespace}" delete secret -l "owner=helm,name=${release}" --ignore-not-found --timeout="${timeout}" || true
delete_stale_resources
delete_pvcs

echo "Helm release recovery completed for ${release}."
