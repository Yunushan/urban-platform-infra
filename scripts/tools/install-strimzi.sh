#!/usr/bin/env bash
set -euo pipefail

enabled="${DEPLOY_ENABLE_STRIMZI:-${INSTALL_STRIMZI:-false}}"
namespace="${STRIMZI_OPERATOR_NAMESPACE:-strimzi-system}"
release="${STRIMZI_OPERATOR_RELEASE:-strimzi-kafka-operator}"
repo_name="${STRIMZI_OPERATOR_REPO_NAME:-strimzi}"
repo_url="${STRIMZI_OPERATOR_REPO_URL:-https://strimzi.io/charts/}"
chart="${STRIMZI_OPERATOR_CHART:-strimzi/strimzi-kafka-operator}"
chart_version="${STRIMZI_OPERATOR_CHART_VERSION:-1.1.0}"
timeout_value="${STRIMZI_OPERATOR_TIMEOUT:-10m}"
retries="${STRIMZI_OPERATOR_RETRIES:-3}"
retry_delay="${STRIMZI_OPERATOR_RETRY_DELAY:-20}"
watch_namespaces="${STRIMZI_WATCH_NAMESPACES:-${NAMESPACE:-urban-platform}}"
watch_any_namespace="${STRIMZI_WATCH_ANY_NAMESPACE:-false}"
kubeconfig_path="${OPERATOR_KUBECONFIG:-${KUBECONFIG:-${HOME}/.kube/config}}"
preload_images="${STRIMZI_PRELOAD_IMAGES:-auto}"
preload_script="${RKE2_IMAGE_PRELOAD_SCRIPT:-scripts/tools/preload-rke2-images.sh}"
kafka_version="${STRIMZI_KAFKA_VERSION:-4.2.0}"
operator_image_registry="${STRIMZI_OPERATOR_IMAGE_REGISTRY:-quay.io}"
operator_image_repository="${STRIMZI_OPERATOR_IMAGE_REPOSITORY:-strimzi}"
operator_image_name="${STRIMZI_OPERATOR_IMAGE_NAME:-operator}"
operator_image_tag="${STRIMZI_OPERATOR_IMAGE_TAG:-${chart_version}}"
operator_image_digest="${STRIMZI_OPERATOR_IMAGE_DIGEST:-}"
operator_image_pull_secrets="${STRIMZI_OPERATOR_IMAGE_PULL_SECRETS:-}"
kafka_image="${STRIMZI_KAFKA_IMAGE:-quay.io/strimzi/kafka:${chart_version}-kafka-${kafka_version}}"

if [ -z "${operator_image_registry}" ] || [ -z "${operator_image_repository}" ] || [ -z "${operator_image_name}" ]; then
  echo "Strimzi operator image registry, repository, and name must be non-empty." >&2
  exit 2
fi

if [ -n "${operator_image_digest}" ] && [[ ! "${operator_image_digest}" =~ ^sha256:[[:xdigit:]]{64}$ ]]; then
  echo "STRIMZI_OPERATOR_IMAGE_DIGEST must be a sha256 digest." >&2
  exit 2
fi

operator_image="${operator_image_registry}/${operator_image_repository}/${operator_image_name}"
helm_image_args=(
  --set-string "image.registry=${operator_image_registry}"
  --set-string "image.repository=${operator_image_repository}"
  --set-string "image.name=${operator_image_name}"
)
if [ -n "${operator_image_digest}" ]; then
  operator_image="${operator_image}@${operator_image_digest}"
  helm_image_args+=(--set-string "image.digest=${operator_image_digest}")
else
  operator_image="${operator_image}:${operator_image_tag}"
  helm_image_args+=(--set-string "image.tag=${operator_image_tag}")
fi

if [ -n "${operator_image_pull_secrets}" ]; then
  IFS=',' read -r -a pull_secret_values <<< "${operator_image_pull_secrets}"
  pull_secret_index=0
  for pull_secret in "${pull_secret_values[@]}"; do
    pull_secret="${pull_secret//[[:space:]]/}"
    [ -n "${pull_secret}" ] || continue
    helm_image_args+=(--set-string "image.imagePullSecrets[${pull_secret_index}].name=${pull_secret}")
    pull_secret_index=$((pull_secret_index + 1))
  done
fi

case "${chart_version}:${kafka_version}" in
  0.*:4.3.*|1.0.*:4.3.*)
    echo "Apache Kafka ${kafka_version} requires Strimzi 1.1.0 or newer; requested ${chart_version}." >&2
    exit 2
    ;;
esac

if [ "${enabled}" != "true" ]; then
  echo "Strimzi operator install disabled."
  exit 0
fi

if ! command -v helm >/dev/null 2>&1; then
  echo "helm is required to install Strimzi." >&2
  exit 1
fi

helm_watch_args=()
case "${watch_any_namespace}" in
  true)
    helm_watch_args+=(--set watchAnyNamespace=true)
    ;;
  false)
    if [ -n "${watch_namespaces}" ]; then
      helm_watch_args+=(--set "watchNamespaces={${watch_namespaces}}")
    fi
    ;;
  *)
    echo "STRIMZI_WATCH_ANY_NAMESPACE must be true or false." >&2
    exit 2
    ;;
esac

preload_strimzi_images() {
  local should_preload="false"

  case "${preload_images}" in
    true)
      should_preload="true"
      ;;
    false)
      should_preload="false"
      ;;
    auto)
      if [ "${MIGRATION_IMAGE_MODE:-}" = "preload" ] \
        || [ -n "${MIGRATION_RKE2_NODES:-}" ] \
        || [ -r "${MIGRATION_FALLBACK_INVENTORY:-/tmp/urban-platform-import-inventory.yml}" ]; then
        should_preload="true"
      fi
      ;;
    *)
      echo "STRIMZI_PRELOAD_IMAGES must be auto, true, or false." >&2
      exit 2
      ;;
  esac

  if [ "${should_preload}" != "true" ]; then
    echo "Strimzi RKE2 image preload disabled."
    return 0
  fi

  if [ ! -r "${preload_script}" ]; then
    if [ "${preload_images}" = "true" ]; then
      echo "Strimzi RKE2 image preload script not found: ${preload_script}" >&2
      exit 1
    fi
    echo "Strimzi RKE2 image preload script not found; continuing without preload: ${preload_script}" >&2
    return 0
  fi

  echo "Preloading Strimzi images for RKE2 nodes: ${operator_image} ${kafka_image}"
  if bash "${preload_script}" "${operator_image}" "${kafka_image}"; then
    return 0
  fi

  if [ "${preload_images}" = "true" ]; then
    echo "Strimzi RKE2 image preload failed." >&2
    exit 1
  fi

  echo "Strimzi RKE2 image preload failed in auto mode; continuing so cluster-side pulls can still proceed." >&2
}

preload_strimzi_images

attempt=1
while true; do
  echo "Installing Strimzi operator ${chart_version} with Helm (attempt ${attempt}/${retries})."
  if KUBECONFIG="${kubeconfig_path}" helm repo add "${repo_name}" "${repo_url}" --force-update \
    && KUBECONFIG="${kubeconfig_path}" helm repo update "${repo_name}" \
    && KUBECONFIG="${kubeconfig_path}" helm upgrade --install "${release}" "${chart}" \
      --namespace "${namespace}" \
      --create-namespace \
      --version "${chart_version}" \
      "${helm_watch_args[@]}" \
      "${helm_image_args[@]}" \
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
