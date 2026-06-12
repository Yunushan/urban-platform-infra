#!/usr/bin/env bash
set -euo pipefail

enabled="${DEPLOY_ENABLE_STRIMZI:-${INSTALL_STRIMZI:-false}}"
namespace="${STRIMZI_OPERATOR_NAMESPACE:-strimzi-system}"
release="${STRIMZI_OPERATOR_RELEASE:-strimzi-kafka-operator}"
repo_name="${STRIMZI_OPERATOR_REPO_NAME:-strimzi}"
repo_url="${STRIMZI_OPERATOR_REPO_URL:-https://strimzi.io/charts/}"
chart="${STRIMZI_OPERATOR_CHART:-strimzi/strimzi-kafka-operator}"
chart_version="${STRIMZI_OPERATOR_CHART_VERSION:-1.0.0}"
timeout_value="${STRIMZI_OPERATOR_TIMEOUT:-10m}"
retries="${STRIMZI_OPERATOR_RETRIES:-3}"
retry_delay="${STRIMZI_OPERATOR_RETRY_DELAY:-20}"
kubeconfig_path="${OPERATOR_KUBECONFIG:-${KUBECONFIG:-${HOME}/.kube/config}}"

if [ "${enabled}" != "true" ]; then
  echo "Strimzi operator install disabled."
  exit 0
fi

if ! command -v helm >/dev/null 2>&1; then
  echo "helm is required to install Strimzi." >&2
  exit 1
fi

attempt=1
while true; do
  echo "Installing Strimzi operator ${chart_version} with Helm (attempt ${attempt}/${retries})."
  if KUBECONFIG="${kubeconfig_path}" helm repo add "${repo_name}" "${repo_url}" --force-update \
    && KUBECONFIG="${kubeconfig_path}" helm repo update "${repo_name}" \
    && KUBECONFIG="${kubeconfig_path}" helm upgrade --install "${release}" "${chart}" \
      --namespace "${namespace}" \
      --create-namespace \
      --version "${chart_version}" \
      --wait \
      --timeout "${timeout_value}"; then
    KUBECONFIG="${kubeconfig_path}" kubectl -n "${namespace}" rollout status deployment/strimzi-cluster-operator --timeout="${timeout_value}"
    exit 0
  fi

  if [ "${attempt}" -ge "${retries}" ]; then
    echo "Strimzi operator install failed after ${retries} attempt(s)." >&2
    exit 1
  fi

  echo "Strimzi operator install attempt ${attempt}/${retries} failed; retrying in ${retry_delay}s." >&2
  sleep "${retry_delay}"
  attempt=$((attempt + 1))
done
