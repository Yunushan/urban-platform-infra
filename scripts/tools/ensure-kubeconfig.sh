#!/usr/bin/env bash
set -euo pipefail

ENVIRONMENT="${ENV:-prod}"
ENGINE="${ENGINE:-rke2}"
INVENTORY_PATH="${INVENTORY:-inventories/${ENVIRONMENT}/hosts.yml}"
ANSIBLE_CONFIG_PATH="${ANSIBLE_CONFIG:-ansible/ansible.cfg}"
ANSIBLE_PLAYBOOK_BIN="${ANSIBLE_PLAYBOOK:-ansible-playbook}"
OPERATOR_KUBECONFIG_PATH="${OPERATOR_KUBECONFIG:-${KUBECONFIG:-${HOME}/.kube/config}}"
FALLBACK_INVENTORY_PATH="${TMPDIR:-/tmp}/urban-platform-import-inventory.yml"

write_kubeconfig_from_node() {
  local node="$1"
  local endpoint_host="$2"
  local endpoint_port="$3"
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local remote_kubeconfig_command="${MIGRATION_RKE2_KUBECONFIG_COMMAND:-sudo cat /etc/rancher/rke2/rke2.yaml}"
  local tmp_kubeconfig
  local ssh_options=()

  if [ -n "${MIGRATION_SSH_KEY:-}" ]; then
    ssh_options+=("-i" "${MIGRATION_SSH_KEY}")
  fi

  tmp_kubeconfig="$(mktemp)"
  echo "Fetching RKE2 kubeconfig directly from ${ssh_user}@${node}."
  if ! printf '%s\n' "${remote_kubeconfig_command}" | ssh "${ssh_options[@]}" "${ssh_user}@${node}" 'sh -s' > "${tmp_kubeconfig}"; then
    rm -f "${tmp_kubeconfig}"
    echo "Could not fetch /etc/rancher/rke2/rke2.yaml from ${ssh_user}@${node}." >&2
    echo "Verify SSH access, MIGRATION_SSH_USER, MIGRATION_SSH_KEY, and sudo permissions on the first RKE2 node." >&2
    return 1
  fi

  sed -i -E "s#server: https://[^[:space:]]+#server: https://${endpoint_host}:${endpoint_port}#" "${tmp_kubeconfig}"
  install -d -m 0700 "$(dirname "${OPERATOR_KUBECONFIG_PATH}")"
  install -m 0600 "${tmp_kubeconfig}" "${OPERATOR_KUBECONFIG_PATH}"
  rm -f "${tmp_kubeconfig}"
}

kubernetes_api_ready() {
  if ! command -v kubectl >/dev/null 2>&1; then
    return 0
  fi
  KUBECONFIG="${OPERATOR_KUBECONFIG_PATH}" kubectl get --raw=/readyz --request-timeout=10s >/dev/null 2>&1
}

start_kubernetes_api_tunnel() {
  local node="$1"
  local remote_port="$2"
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local requested_port="${MIGRATION_KUBE_API_TUNNEL_PORT:-16443}"
  local socket_dir="${TMPDIR:-/tmp}/urban-platform-kubeapi"
  local socket_path
  local port
  local max_port
  local ssh_options=("-o" "ExitOnForwardFailure=yes")

  if [ -n "${MIGRATION_SSH_KEY:-}" ]; then
    ssh_options+=("-i" "${MIGRATION_SSH_KEY}")
  fi

  mkdir -p "${socket_dir}"
  chmod 0700 "${socket_dir}" 2>/dev/null || true

  port="${requested_port}"
  max_port="$((requested_port + 20))"
  while [ "${port}" -le "${max_port}" ]; do
    socket_path="${socket_dir}/ssh-${node//[^A-Za-z0-9_.-]/_}-${remote_port}-${port}.sock"
    if ssh -S "${socket_path}" -O check "${ssh_options[@]}" "${ssh_user}@${node}" >/dev/null 2>&1; then
      echo "${port}"
      return 0
    fi
    rm -f "${socket_path}"
    echo "Trying SSH tunnel 127.0.0.1:${port} -> ${node}:127.0.0.1:${remote_port}" >&2
    if ssh "${ssh_options[@]}" -fN -M -S "${socket_path}" \
      -L "127.0.0.1:${port}:127.0.0.1:${remote_port}" \
      "${ssh_user}@${node}"; then
      echo "${port}"
      return 0
    fi
    rm -f "${socket_path}"
    port="$((port + 1))"
  done

  return 1
}

stop_kubernetes_api_tunnel() {
  local node="$1"
  local remote_port="$2"
  local local_port="$3"
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local socket_dir="${TMPDIR:-/tmp}/urban-platform-kubeapi"
  local socket_path="${socket_dir}/ssh-${node//[^A-Za-z0-9_.-]/_}-${remote_port}-${local_port}.sock"
  local ssh_options=()

  if [ -n "${MIGRATION_SSH_KEY:-}" ]; then
    ssh_options+=("-i" "${MIGRATION_SSH_KEY}")
  fi

  ssh -S "${socket_path}" -O exit "${ssh_options[@]}" "${ssh_user}@${node}" >/dev/null 2>&1 || true
  rm -f "${socket_path}"
}

show_remote_rke2_diagnostics() {
  local node="$1"
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local ssh_options=()

  if [ -n "${MIGRATION_SSH_KEY:-}" ]; then
    ssh_options+=("-i" "${MIGRATION_SSH_KEY}")
  fi

  echo "Remote RKE2 diagnostics for ${node}:" >&2
  ssh "${ssh_options[@]}" "${ssh_user}@${node}" 'sh -s' <<'REMOTE_DIAGNOSTICS' >&2 || true
set -u
if ! sudo -n true 2>/dev/null; then
  echo "passwordless sudo is not available for this SSH user"
  exit 0
fi

for service in rke2-server rke2-agent; do
  state="$(sudo systemctl is-active "${service}" 2>/dev/null || true)"
  if [ -n "${state}" ] && [ "${state}" != "unknown" ]; then
    echo "${service}: ${state}"
  fi
done

if command -v ss >/dev/null 2>&1; then
  echo "listening RKE2 API ports:"
  sudo ss -ltnp 2>/dev/null | awk 'NR == 1 || /:6443/ || /:9345/' || true
fi

echo "local /readyz probe:"
if command -v rke2 >/dev/null 2>&1; then
  sudo rke2 kubectl --kubeconfig /etc/rancher/rke2/rke2.yaml get --raw=/readyz --request-timeout=10s || true
elif [ -x /var/lib/rancher/rke2/bin/kubectl ]; then
  sudo /var/lib/rancher/rke2/bin/kubectl --kubeconfig /etc/rancher/rke2/rke2.yaml get --raw=/readyz --request-timeout=10s || true
elif command -v kubectl >/dev/null 2>&1; then
  sudo kubectl --kubeconfig /etc/rancher/rke2/rke2.yaml get --raw=/readyz --request-timeout=10s || true
else
  echo "kubectl/rke2 kubectl is not available"
fi
REMOTE_DIAGNOSTICS
}

if [ "${ENGINE}" != "rke2" ]; then
  echo "Skipping automatic kubeconfig repair for ENGINE=${ENGINE}; using existing kubectl context."
  exit 0
fi

if [ ! -f "${INVENTORY_PATH}" ]; then
  if [ -z "${MIGRATION_RKE2_NODES:-}" ]; then
    echo "Missing inventory ${INVENTORY_PATH}; cannot repair operator kubeconfig." >&2
    echo "Set INVENTORY=/path/to/hosts.yml or MIGRATION_RKE2_NODES=node-1,node-2,node-3." >&2
    exit 1
  fi

  IFS=',' read -r -a rke2_nodes <<< "${MIGRATION_RKE2_NODES}"
  first_rke2_node=""
  for node in "${rke2_nodes[@]}"; do
    node="${node//[[:space:]]/}"
    if [ -n "${node}" ]; then
      first_rke2_node="${node}"
      break
    fi
  done
  if [ -z "${first_rke2_node}" ]; then
    echo "MIGRATION_RKE2_NODES did not contain any usable node address." >&2
    exit 1
  fi

  explicit_cluster_vip="${MIGRATION_CLUSTER_VIP:-${CLUSTER_VIP:-}}"
  cluster_vip="${explicit_cluster_vip:-${first_rke2_node}}"
  if [ -n "${explicit_cluster_vip}" ]; then
    kubernetes_api_port="${MIGRATION_KUBERNETES_API_VIP_PORT:-${KUBERNETES_API_VIP_PORT:-7443}}"
  else
    kubernetes_api_port="${MIGRATION_KUBERNETES_API_VIP_PORT:-${KUBERNETES_API_VIP_PORT:-6443}}"
  fi
  ansible_user_for_nodes="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"

  {
    printf 'all:\n'
    printf '  vars:\n'
    printf '    ansible_user: %s\n' "${ansible_user_for_nodes}"
    printf '    ansible_python_interpreter: /usr/bin/python3\n'
    printf '    cluster_engine: rke2\n'
    printf '    cluster_vip: %s\n' "${cluster_vip}"
    printf '    kubernetes_api_vip_port: %s\n' "${kubernetes_api_port}"
    printf '  children:\n'
    printf '    cluster_nodes:\n'
    printf '      children:\n'
    printf '        rke2_servers:\n'
    printf '        rke2_agents:\n'
    printf '    rke2_servers:\n'
    printf '      hosts:\n'
    index=1
    for node in "${rke2_nodes[@]}"; do
      node="${node//[[:space:]]/}"
      if [ -z "${node}" ]; then
        continue
      fi
      printf '        import-rke2-%02d:\n' "${index}"
      printf '          ansible_host: %s\n' "${node}"
      printf '          node_ip: %s\n' "${node}"
      index=$((index + 1))
    done
    printf '    rke2_agents:\n'
    printf '      hosts: {}\n'
    printf '    load_balancers:\n'
    printf '      hosts:\n'
    index=1
    for node in "${rke2_nodes[@]}"; do
      node="${node//[[:space:]]/}"
      if [ -z "${node}" ]; then
        continue
      fi
      printf '        import-rke2-%02d: {}\n' "${index}"
      index=$((index + 1))
    done
  } > "${FALLBACK_INVENTORY_PATH}"
  chmod 0600 "${FALLBACK_INVENTORY_PATH}" 2>/dev/null || true
  INVENTORY_PATH="${FALLBACK_INVENTORY_PATH}"
  echo "Generated temporary operator inventory from MIGRATION_RKE2_NODES: ${INVENTORY_PATH}"
  echo "Operator kubeconfig endpoint candidates will use port ${kubernetes_api_port}"
  if [ -n "${explicit_cluster_vip}" ]; then
    endpoint_candidates=("${cluster_vip}")
  else
    endpoint_candidates=("${rke2_nodes[@]}")
  fi

  selected_endpoint=""
  for endpoint_candidate in "${endpoint_candidates[@]}"; do
    endpoint_candidate="${endpoint_candidate//[[:space:]]/}"
    if [ -z "${endpoint_candidate}" ]; then
      continue
    fi
    echo "Trying Kubernetes API endpoint https://${endpoint_candidate}:${kubernetes_api_port}"
    write_kubeconfig_from_node "${first_rke2_node}" "${endpoint_candidate}" "${kubernetes_api_port}"
    if kubernetes_api_ready; then
      selected_endpoint="${endpoint_candidate}"
      break
    fi
    echo "Kubernetes API endpoint https://${endpoint_candidate}:${kubernetes_api_port} is not ready from this operator; trying the next endpoint." >&2
  done

  if [ -z "${selected_endpoint}" ]; then
    if [ "${MIGRATION_KUBE_API_TUNNEL:-auto}" = "false" ]; then
      echo "No Kubernetes API endpoint from MIGRATION_RKE2_NODES became ready." >&2
      echo "Check RKE2 server health/firewall rules, or set MIGRATION_CLUSTER_VIP and MIGRATION_KUBERNETES_API_VIP_PORT to the reachable API endpoint." >&2
      exit 1
    fi
    echo "No node API endpoint was reachable directly; trying SSH tunnel fallback." >&2
    for tunnel_node in "${rke2_nodes[@]}"; do
      tunnel_node="${tunnel_node//[[:space:]]/}"
      if [ -z "${tunnel_node}" ]; then
        continue
      fi
      if ! tunnel_port="$(start_kubernetes_api_tunnel "${tunnel_node}" "${kubernetes_api_port}")"; then
        echo "Could not open an SSH tunnel through ${tunnel_node}; trying the next node." >&2
        continue
      fi
      write_kubeconfig_from_node "${first_rke2_node}" "127.0.0.1" "${tunnel_port}"
      if kubernetes_api_ready; then
        selected_endpoint="127.0.0.1:${tunnel_port} via SSH tunnel ${tunnel_node}"
        break
      fi
      echo "Kubernetes API was not ready through SSH tunnel via ${tunnel_node}; trying the next node." >&2
      stop_kubernetes_api_tunnel "${tunnel_node}" "${kubernetes_api_port}" "${tunnel_port}"
    done

    if [ -z "${selected_endpoint}" ]; then
      echo "Kubernetes API was not ready through direct endpoints or SSH tunnel fallback." >&2
      echo "Check RKE2 service health and passwordless sudo for ${ansible_user_for_nodes}." >&2
      for diagnostic_node in "${rke2_nodes[@]}"; do
        diagnostic_node="${diagnostic_node//[[:space:]]/}"
        if [ -n "${diagnostic_node}" ]; then
          show_remote_rke2_diagnostics "${diagnostic_node}"
        fi
      done
      exit 1
    fi
  fi
  if [[ "${selected_endpoint}" == 127.0.0.1:* ]]; then
    echo "Operator kubeconfig ready: ${OPERATOR_KUBECONFIG_PATH} (endpoint https://${selected_endpoint})"
  else
    echo "Operator kubeconfig ready: ${OPERATOR_KUBECONFIG_PATH} (endpoint https://${selected_endpoint}:${kubernetes_api_port})"
  fi
  exit 0
fi

extra_args=()
if [ -n "${ANSIBLE_ARGS:-}" ]; then
  # shellcheck disable=SC2206
  extra_args=(${ANSIBLE_ARGS})
fi

ANSIBLE_CONFIG="${ANSIBLE_CONFIG_PATH}" \
  "${ANSIBLE_PLAYBOOK_BIN}" \
  -i "${INVENTORY_PATH}" \
  ansible/playbooks/operator-kubeconfig.yml \
  -e "cluster_engine=${ENGINE}" \
  -e "deployment_environment=${ENVIRONMENT}" \
  -e "operator_kubeconfig_path=${OPERATOR_KUBECONFIG_PATH}" \
  "${extra_args[@]}"

if command -v kubectl >/dev/null 2>&1; then
  KUBECONFIG="${OPERATOR_KUBECONFIG_PATH}" kubectl get --raw=/readyz --request-timeout=10s >/dev/null
fi

echo "Operator kubeconfig ready: ${OPERATOR_KUBECONFIG_PATH}"
