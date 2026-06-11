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
host_path="${LOCAL_PATH_STORAGE_PATH:-/opt/local-path-provisioner}"
prepare_host_paths="${LOCAL_PATH_PREPARE_HOST_PATHS:-auto}"
fallback_inventory_path="${FALLBACK_INVENTORY_PATH:-/tmp/urban-platform-import-inventory.yml}"

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

ssh_options_for_node() {
  printf '%s\n' "-o"
  printf '%s\n' "BatchMode=yes"
  printf '%s\n' "-o"
  printf '%s\n' "ConnectTimeout=${MIGRATION_SSH_CONNECT_TIMEOUT:-10}"
  printf '%s\n' "-o"
  printf '%s\n' "ServerAliveInterval=${MIGRATION_SSH_SERVER_ALIVE_INTERVAL:-5}"
  printf '%s\n' "-o"
  printf '%s\n' "ServerAliveCountMax=${MIGRATION_SSH_SERVER_ALIVE_COUNT_MAX:-2}"
  if [ -n "${MIGRATION_SSH_KEY:-}" ]; then
    printf '%s\n' "-i"
    printf '%s\n' "${MIGRATION_SSH_KEY}"
  fi
}

migration_become_password() {
  if [ -n "${MIGRATION_BECOME_PASSWORD:-}" ]; then
    printf '%s' "${MIGRATION_BECOME_PASSWORD}"
    return 0
  fi
  if [ -n "${MIGRATION_BECOME_PASSWORD_FILE:-}" ] && [ -r "${MIGRATION_BECOME_PASSWORD_FILE}" ]; then
    sed -n '1p' "${MIGRATION_BECOME_PASSWORD_FILE}"
  fi
}

recover_migration_context() {
  local discovered_rke2_nodes
  local recovered_ssh_user
  local recovered_ssh_key
  local recovered_password

  if [ -z "${MIGRATION_RKE2_NODES:-}" ] && [ -r "${fallback_inventory_path}" ]; then
    discovered_rke2_nodes="$(
      sed -nE "s/^[[:space:]]*ansible_host:[[:space:]]*['\"]?([^'\"]+)['\"]?[[:space:]]*$/\1/p" "${fallback_inventory_path}" \
        | paste -sd, -
    )"
    if [ -n "${discovered_rke2_nodes}" ]; then
      export MIGRATION_RKE2_NODES="${discovered_rke2_nodes}"
      echo "Recovered MIGRATION_RKE2_NODES from ${fallback_inventory_path}."
    fi
  fi

  if [ "${MIGRATION_RECOVER_INVENTORY_SSH_CONTEXT:-true}" = "true" ] && [ -r "${fallback_inventory_path}" ]; then
    recovered_ssh_user="$(
      sed -nE "s/^[[:space:]]*ansible_user:[[:space:]]*['\"]?([^'\"]+)['\"]?[[:space:]]*$/\1/p" "${fallback_inventory_path}" \
        | head -n 1
    )"
    if [ -n "${recovered_ssh_user}" ] && { [ -z "${MIGRATION_SSH_USER:-}" ] || [ "${MIGRATION_SSH_USER:-}" = "root" ]; }; then
      export MIGRATION_SSH_USER="${recovered_ssh_user}"
      echo "Recovered MIGRATION_SSH_USER from ${fallback_inventory_path}: ${MIGRATION_SSH_USER}."
    fi

    if [ -z "${MIGRATION_SSH_KEY:-}" ]; then
      recovered_ssh_key="$(
        sed -nE "s/^[[:space:]]*ansible_ssh_private_key_file:[[:space:]]*['\"]?([^'\"]+)['\"]?[[:space:]]*$/\1/p" "${fallback_inventory_path}" \
          | head -n 1
      )"
      if [ -z "${recovered_ssh_key}" ]; then
        for recovered_ssh_key in \
          "${HOME}/.ssh/id_ed25519_urban_ansible" \
          "${HOME}/.ssh/id_rsa_urban_ansible" \
          "${HOME}/.ssh/id_ed25519"; do
          if [ -r "${recovered_ssh_key}" ]; then
            break
          fi
          recovered_ssh_key=""
        done
      fi
      if [ -n "${recovered_ssh_key}" ] && [ -r "${recovered_ssh_key}" ]; then
        export MIGRATION_SSH_KEY="${recovered_ssh_key}"
        echo "Recovered MIGRATION_SSH_KEY from local SSH identity: ${MIGRATION_SSH_KEY}."
      fi
    fi
  fi

  if [ -z "${MIGRATION_BECOME_PASSWORD:-}" ] && [ -z "${MIGRATION_BECOME_PASSWORD_FILE:-}" ] && [ -r "${fallback_inventory_path}" ]; then
    recovered_password="$(
      sed -nE "s/^[[:space:]]*ansible_become_password:[[:space:]]*'(.*)'[[:space:]]*$/\1/p" "${fallback_inventory_path}" \
        | sed "s/''/'/g" \
        | head -n 1
    )"
    if [ -z "${recovered_password}" ]; then
      recovered_password="$(
        sed -nE "s/^[[:space:]]*ansible_become_password:[[:space:]]*([^[:space:]#]+).*$/\1/p" "${fallback_inventory_path}" \
          | head -n 1
      )"
    fi
    if [ -n "${recovered_password}" ]; then
      export MIGRATION_BECOME_PASSWORD="${recovered_password}"
      echo "Recovered MIGRATION_BECOME_PASSWORD from ${fallback_inventory_path}."
    fi
  fi
}

discover_storage_nodes() {
  local discovered_nodes

  if [ -n "${MIGRATION_RKE2_NODES:-}" ]; then
    printf '%s\n' "${MIGRATION_RKE2_NODES}" | tr ',' '\n'
    return 0
  fi

  discovered_nodes="$(
    kubectl --request-timeout="${request_timeout}" get nodes \
      -o jsonpath='{range .items[*]}{range .status.addresses[?(@.type=="InternalIP")]}{.address}{"\n"}{end}{end}' 2>/dev/null || true
  )"
  if [ -n "${discovered_nodes}" ]; then
    printf '%s\n' "${discovered_nodes}"
  fi
}

emit_prepare_host_path_script() {
  cat <<'REMOTE_PREPARE_LOCAL_PATH'
set -eu
path="${1:?missing local-path storage path}"
mkdir -p "$path"
chmod 0777 "$path"
if command -v chcon >/dev/null 2>&1; then
  chcon -Rt container_file_t "$path" || true
fi
if command -v semanage >/dev/null 2>&1; then
  semanage fcontext -a -t container_file_t "${path}(/.*)?" 2>/dev/null || \
    semanage fcontext -m -t container_file_t "${path}(/.*)?" 2>/dev/null || true
fi
if command -v restorecon >/dev/null 2>&1; then
  restorecon -RF "$path" >/dev/null 2>&1 || true
fi
ls -ldZ "$path" 2>/dev/null || ls -ld "$path"
REMOTE_PREPARE_LOCAL_PATH
}

prepare_host_path_on_node() {
  local node="$1"
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local become_password
  local ssh_options=()

  mapfile -t ssh_options < <(ssh_options_for_node)
  become_password="$(migration_become_password)"

  echo "Preparing local-path host path ${host_path} on ${ssh_user}@${node}."
  if [ "${ssh_user}" = "root" ]; then
    emit_prepare_host_path_script \
      | ssh "${ssh_options[@]}" "${ssh_user}@${node}" sh -s -- "${host_path}"
  elif ssh "${ssh_options[@]}" "${ssh_user}@${node}" "sudo -n true" >/dev/null 2>&1; then
    emit_prepare_host_path_script \
      | ssh "${ssh_options[@]}" "${ssh_user}@${node}" sudo -n sh -s -- "${host_path}"
  elif [ -n "${become_password}" ]; then
    { printf '%s\n' "${become_password}"; emit_prepare_host_path_script; } \
      | ssh "${ssh_options[@]}" "${ssh_user}@${node}" sudo -S sh -s -- "${host_path}"
  else
    emit_prepare_host_path_script \
      | ssh "${ssh_options[@]}" "${ssh_user}@${node}" sudo -n sh -s -- "${host_path}"
  fi
}

prepare_host_paths() {
  local node
  local prepared=0
  local failed=0
  local nodes=()

  if [ "${prepare_host_paths}" = "false" ]; then
    return 0
  fi
  if ! command -v ssh >/dev/null 2>&1; then
    if [ "${prepare_host_paths}" = "true" ]; then
      echo "ssh is required to prepare local-path host directories." >&2
      exit 1
    fi
    echo "ssh is not available; skipping local-path host directory preparation." >&2
    return 0
  fi

  recover_migration_context
  mapfile -t nodes < <(discover_storage_nodes | awk 'NF && !seen[$0]++')
  if [ "${#nodes[@]}" -eq 0 ]; then
    if [ "${prepare_host_paths}" = "true" ]; then
      echo "Could not discover nodes for local-path host directory preparation." >&2
      exit 1
    fi
    echo "Could not discover nodes; skipping local-path host directory preparation." >&2
    return 0
  fi

  for node in "${nodes[@]}"; do
    node="${node//[[:space:]]/}"
    if [ -z "${node}" ]; then
      continue
    fi
    if prepare_host_path_on_node "${node}"; then
      prepared=$((prepared + 1))
    else
      failed=$((failed + 1))
      echo "Could not prepare local-path host path on ${node}; continuing." >&2
    fi
  done

  if [ "${prepared}" -eq 0 ]; then
    echo "No local-path host directories were prepared." >&2
    if [ "${prepare_host_paths}" = "true" ]; then
      exit 1
    fi
  elif [ "${failed}" -gt 0 ]; then
    echo "Prepared local-path host directories on ${prepared} node(s); ${failed} node(s) could not be prepared." >&2
  else
    echo "Prepared local-path host directories on ${prepared} node(s)."
  fi
}

prepare_host_paths

echo "Installing local-path provisioner ${version} from ${manifest_url}"
kubectl_retry apply -f "${manifest_url}"
kubectl_retry -n local-path-storage delete pod --field-selector=status.phase=Failed --ignore-not-found || true
kubectl_retry -n local-path-storage rollout restart deployment/local-path-provisioner

kubectl_retry -n local-path-storage rollout status deployment/local-path-provisioner --timeout="${timeout}"

if [ "${make_default}" = "true" ]; then
  kubectl_retry patch storageclass "${storage_class}" --type=merge \
    -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true","storageclass.beta.kubernetes.io/is-default-class":"true"}}}'
fi

kubectl_retry get storageclass "${storage_class}"
