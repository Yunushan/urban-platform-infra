#!/usr/bin/env bash
set -euo pipefail

ENVIRONMENT="${ENV:-prod}"
ENGINE="${ENGINE:-rke2}"
INVENTORY_PATH="${INVENTORY:-inventories/${ENVIRONMENT}/hosts.yml}"
ANSIBLE_CONFIG_PATH="${ANSIBLE_CONFIG:-ansible/ansible.cfg}"
ANSIBLE_PLAYBOOK_BIN="${ANSIBLE_PLAYBOOK:-ansible-playbook}"
OPERATOR_KUBECONFIG_PATH="${OPERATOR_KUBECONFIG:-${KUBECONFIG:-${HOME}/.kube/config}}"
FALLBACK_INVENTORY_PATH="${TMPDIR:-/tmp}/urban-platform-import-inventory.yml"

migration_become_password() {
  if [ -n "${MIGRATION_BECOME_PASSWORD_FILE:-}" ]; then
    case "${MIGRATION_BECOME_PASSWORD_FILE}" in
      /path/to/*|path/to/*)
        echo "MIGRATION_BECOME_PASSWORD_FILE is still a placeholder: ${MIGRATION_BECOME_PASSWORD_FILE}" >&2
        return 1
        ;;
    esac
    if [ ! -r "${MIGRATION_BECOME_PASSWORD_FILE}" ]; then
      echo "MIGRATION_BECOME_PASSWORD_FILE is not readable: ${MIGRATION_BECOME_PASSWORD_FILE}" >&2
      return 1
    fi
    sed -n '1p' "${MIGRATION_BECOME_PASSWORD_FILE}"
    return 0
  fi
  printf '%s' "${MIGRATION_BECOME_PASSWORD:-}"
}

become_password_prompt_enabled() {
  case "${MIGRATION_BECOME_PASSWORD_PROMPT:-auto}" in
    false|False|FALSE|0|no|No|NO|never|Never|NEVER)
      return 1
      ;;
  esac
  return 0
}

become_password_prompt_available() {
  become_password_prompt_enabled && [ -r /dev/tty ] && [ -w /dev/tty ]
}

validate_become_password_input() {
  if [ -z "${MIGRATION_BECOME_PASSWORD_FILE:-}" ]; then
    return 0
  fi

  case "${MIGRATION_BECOME_PASSWORD_FILE}" in
    /path/to/*|path/to/*)
      echo "Ignoring placeholder MIGRATION_BECOME_PASSWORD_FILE=${MIGRATION_BECOME_PASSWORD_FILE}; deploy-auto will prompt if sudo needs a password." >&2
      unset MIGRATION_BECOME_PASSWORD_FILE
      return 0
      ;;
  esac

  if [ -r "${MIGRATION_BECOME_PASSWORD_FILE}" ]; then
    return 0
  fi

  if become_password_prompt_available; then
    echo "MIGRATION_BECOME_PASSWORD_FILE is not readable: ${MIGRATION_BECOME_PASSWORD_FILE}; deploy-auto will prompt if sudo needs a password." >&2
    unset MIGRATION_BECOME_PASSWORD_FILE
    return 0
  fi

  echo "MIGRATION_BECOME_PASSWORD_FILE is not readable: ${MIGRATION_BECOME_PASSWORD_FILE}" >&2
  echo "Create the file with mode 0600, enable passwordless sudo, or run from an interactive terminal." >&2
  exit 1
}

write_kubeconfig_from_node() {
  local node="$1"
  local endpoint_host="$2"
  local endpoint_port="$3"
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local remote_kubeconfig_command="${MIGRATION_RKE2_KUBECONFIG_COMMAND:-}"
  local become_password
  local tmp_kubeconfig
  local ssh_options=()

  mapfile -t ssh_options < <(ssh_options_for_node)

  become_password="$(migration_become_password)"
  tmp_kubeconfig="$(mktemp)"
  echo "Fetching RKE2 kubeconfig directly from ${ssh_user}@${node}."
  if [ -z "${remote_kubeconfig_command}" ]; then
    if [ -n "${become_password}" ]; then
      if ! printf '%s\n' "${become_password}" | ssh "${ssh_options[@]}" "${ssh_user}@${node}" "sudo -S -p '' test -e /etc/rancher/rke2/rke2.yaml"; then
        rm -f "${tmp_kubeconfig}"
        echo "RKE2 kubeconfig is not present on ${node} yet; this is normal before the first server is installed." >&2
        return 2
      fi
    elif ! ssh "${ssh_options[@]}" "${ssh_user}@${node}" "sudo -n test -e /etc/rancher/rke2/rke2.yaml"; then
      rm -f "${tmp_kubeconfig}"
      echo "RKE2 kubeconfig is not present on ${node} yet, or ${ssh_user} cannot check it without sudo." >&2
      return 2
    fi
  fi
  if [ -n "${remote_kubeconfig_command}" ]; then
    if ! printf '%s\n' "${remote_kubeconfig_command}" | ssh "${ssh_options[@]}" "${ssh_user}@${node}" 'sh -s' > "${tmp_kubeconfig}"; then
      rm -f "${tmp_kubeconfig}"
      echo "Could not fetch /etc/rancher/rke2/rke2.yaml from ${ssh_user}@${node}." >&2
      echo "Verify SSH access, MIGRATION_SSH_USER, MIGRATION_SSH_KEY, and sudo permissions on the first RKE2 node." >&2
      return 1
    fi
  elif [ -n "${become_password}" ]; then
    if ! printf '%s\n' "${become_password}" | ssh "${ssh_options[@]}" "${ssh_user}@${node}" "sudo -S -p '' cat /etc/rancher/rke2/rke2.yaml" > "${tmp_kubeconfig}"; then
      rm -f "${tmp_kubeconfig}"
      echo "Could not fetch /etc/rancher/rke2/rke2.yaml from ${ssh_user}@${node} using MIGRATION_BECOME_PASSWORD_FILE." >&2
      echo "Verify SSH access, MIGRATION_SSH_USER, MIGRATION_SSH_KEY, and the sudo password file." >&2
      return 1
    fi
  else
    if ! ssh "${ssh_options[@]}" "${ssh_user}@${node}" "sudo -n cat /etc/rancher/rke2/rke2.yaml" > "${tmp_kubeconfig}"; then
      rm -f "${tmp_kubeconfig}"
      echo "Could not fetch /etc/rancher/rke2/rke2.yaml from ${ssh_user}@${node}." >&2
      echo "Configure passwordless sudo, use root SSH, or set MIGRATION_BECOME_PASSWORD_FILE to a root-readable local password file on the operator." >&2
      return 1
    fi
  fi

  sed -i -E "s#server: https://[^[:space:]]+#server: https://${endpoint_host}:${endpoint_port}#" "${tmp_kubeconfig}"
  install -d -m 0700 "$(dirname "${OPERATOR_KUBECONFIG_PATH}")"
  install -m 0600 "${tmp_kubeconfig}" "${OPERATOR_KUBECONFIG_PATH}"
  rm -f "${tmp_kubeconfig}"
}

rewrite_existing_kubeconfig_endpoint() {
  local endpoint_host="$1"
  local endpoint_port="$2"
  local tls_server_name="${3:-}"
  local tmp_kubeconfig

  if [ ! -s "${OPERATOR_KUBECONFIG_PATH}" ]; then
    return 1
  fi

  tmp_kubeconfig="$(mktemp)"
  awk -v endpoint="${endpoint_host}:${endpoint_port}" -v tls_server_name="${tls_server_name}" '
    /^[[:space:]]*tls-server-name:/ {
      next
    }
    /^[[:space:]]*server:[[:space:]]*https:\/\// {
      indent = $0
      sub(/server:.*/, "", indent)
      print indent "server: https://" endpoint
      if (tls_server_name != "") {
        print indent "tls-server-name: " tls_server_name
      }
      next
    }
    { print }
  ' "${OPERATOR_KUBECONFIG_PATH}" > "${tmp_kubeconfig}"
  install -d -m 0700 "$(dirname "${OPERATOR_KUBECONFIG_PATH}")"
  install -m 0600 "${tmp_kubeconfig}" "${OPERATOR_KUBECONFIG_PATH}"
  rm -f "${tmp_kubeconfig}"
}

yaml_quote() {
  local value="$1"
  printf "'"
  printf '%s' "${value}" | sed "s/'/''/g"
  printf "'"
}

normalize_rke2_version() {
  local value="$1"
  printf '%s\n' "${value}" \
    | tr -d '\r' \
    | sed -nE 's/.*v?([0-9]+\.[0-9]+\.[0-9]+)[+-](rke2r[0-9]+).*/v\1+\2/p' \
    | head -n 1 || true
}

generate_rke2_token() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_hex(32))'
    return 0
  fi
  return 1
}

generate_keepalived_auth_pass() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 4
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_hex(4))'
    return 0
  fi
  return 1
}

recover_become_password_from_fallback_inventory() {
  local recovered_password

  if [ -n "${MIGRATION_BECOME_PASSWORD:-}" ] || [ -n "${MIGRATION_BECOME_PASSWORD_FILE:-}" ]; then
    return 0
  fi
  if [ ! -r "${FALLBACK_INVENTORY_PATH}" ]; then
    return 0
  fi

  recovered_password="$(
    sed -nE "s/^[[:space:]]*ansible_become_password:[[:space:]]*'(.*)'[[:space:]]*$/\1/p" "${FALLBACK_INVENTORY_PATH}" \
      | sed "s/''/'/g" \
      | head -n 1
  )"
  if [ -z "${recovered_password}" ]; then
    recovered_password="$(
      sed -nE "s/^[[:space:]]*ansible_become_password:[[:space:]]*([^[:space:]#]+).*$/\1/p" "${FALLBACK_INVENTORY_PATH}" \
        | head -n 1
    )"
  fi
  if [ -n "${recovered_password}" ]; then
    export MIGRATION_BECOME_PASSWORD="${recovered_password}"
    echo "Recovered MIGRATION_BECOME_PASSWORD from ${FALLBACK_INVENTORY_PATH}."
  fi
}

passwordless_sudo_available_on_reachable_nodes() {
  local node
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local ssh_options=()
  local reachable_node=false

  mapfile -t ssh_options < <(ssh_options_for_node)

  for node in "$@"; do
    node="${node//[[:space:]]/}"
    if [ -z "${node}" ]; then
      continue
    fi
    if ssh "${ssh_options[@]}" "${ssh_user}@${node}" "true" >/dev/null 2>&1; then
      reachable_node=true
      if ! ssh "${ssh_options[@]}" "${ssh_user}@${node}" "sudo -n true" >/dev/null 2>&1; then
        return 1
      fi
    fi
  done
  [ "${reachable_node}" = "true" ]
}

sudo_password_works_on_any_node() {
  local password="$1"
  local node
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local ssh_options=()

  shift
  mapfile -t ssh_options < <(ssh_options_for_node)

  for node in "$@"; do
    node="${node//[[:space:]]/}"
    if [ -z "${node}" ]; then
      continue
    fi
    if printf '%s\n' "${password}" | ssh "${ssh_options[@]}" "${ssh_user}@${node}" "sudo -S -p '' true" >/dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

prompt_for_become_password_if_needed() {
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local prompted_password

  if [ -n "${MIGRATION_BECOME_PASSWORD:-}" ] || [ -n "${MIGRATION_BECOME_PASSWORD_FILE:-}" ]; then
    return 0
  fi
  if passwordless_sudo_available_on_reachable_nodes "$@"; then
    return 0
  fi
  if ! become_password_prompt_available; then
    echo "sudo requires a password for ${ssh_user}, but no interactive terminal is available for prompting." >&2
    echo "Enable passwordless sudo or set MIGRATION_BECOME_PASSWORD_FILE to a readable private password file." >&2
    exit 1
  fi

  printf 'sudo password for %s: ' "${ssh_user}" > /dev/tty
  IFS= read -r -s prompted_password < /dev/tty
  printf '\n' > /dev/tty
  if [ -z "${prompted_password}" ]; then
    echo "No sudo password entered; cannot continue automatic RKE2 recovery." >&2
    exit 1
  fi
  if ! sudo_password_works_on_any_node "${prompted_password}" "$@"; then
    echo "The sudo password entered for ${ssh_user} did not work on any RKE2 node." >&2
    exit 1
  fi
  export MIGRATION_BECOME_PASSWORD="${prompted_password}"
  echo "Using prompted sudo password for this deploy-auto run."
}

filter_ssh_reachable_nodes() {
  local node
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local ssh_options=()

  mapfile -t ssh_options < <(ssh_options_for_node)

  for node in "$@"; do
    node="${node//[[:space:]]/}"
    if [ -z "${node}" ]; then
      continue
    fi
    if ssh "${ssh_options[@]}" "${ssh_user}@${node}" "true" >/dev/null 2>&1; then
      printf '%s\n' "${node}"
    else
      echo "RKE2 node ${node} is not reachable over SSH; excluding it from this automatic repair pass." >&2
    fi
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

remote_sudo_sh() {
  local node="$1"
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local become_password
  local ssh_options=()

  mapfile -t ssh_options < <(ssh_options_for_node)
  become_password="$(migration_become_password)"

  if [ -n "${become_password}" ]; then
    { printf '%s\n' "${become_password}"; cat; } \
      | ssh "${ssh_options[@]}" "${ssh_user}@${node}" "sudo -S -p '' sh -s" 2>/dev/null || true
  else
    ssh "${ssh_options[@]}" "${ssh_user}@${node}" "sudo -n sh -s" 2>/dev/null || true
  fi
}

discover_remote_rke2_token() {
  local node="$1"

  remote_sudo_sh "${node}" <<'REMOTE_DISCOVER_TOKEN'
if [ -s /var/lib/rancher/rke2/server/node-token ]; then
  cat /var/lib/rancher/rke2/server/node-token
  exit 0
fi
if [ -s /var/lib/rancher/rke2/server/token ]; then
  cat /var/lib/rancher/rke2/server/token
  exit 0
fi
if [ -s /etc/rancher/rke2/config.yaml ]; then
  awk -F': *' '/^token:/ {print $2; exit}' /etc/rancher/rke2/config.yaml
fi
REMOTE_DISCOVER_TOKEN
}

discover_remote_cluster_vip() {
  local node="$1"

  remote_sudo_sh "${node}" <<'REMOTE_DISCOVER_CLUSTER_VIP'
if [ -s /etc/rancher/rke2/config.yaml ]; then
  awk '
    /^server:/ {
      value=$0
      sub(/^[^:]+:[[:space:]]*/, "", value)
      gsub(/^"|"$/, "", value)
      sub(/^https:\/\//, "", value)
      sub(/:.*/, "", value)
      print value
      exit
    }
  ' /etc/rancher/rke2/config.yaml
fi
REMOTE_DISCOVER_CLUSTER_VIP
}

discover_remote_rke2_version() {
  local node="$1"
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local ssh_options=()
  local version

  mapfile -t ssh_options < <(ssh_options_for_node)

  version="$(ssh "${ssh_options[@]}" "${ssh_user}@${node}" 'sh -s' <<'REMOTE_DISCOVER_VERSION' 2>/dev/null || true
if command -v rke2 >/dev/null 2>&1; then
  rke2 --version
elif [ -x /usr/local/bin/rke2 ]; then
  /usr/local/bin/rke2 --version
elif [ -x /usr/bin/rke2 ]; then
  /usr/bin/rke2 --version
elif [ -x /var/lib/rancher/rke2/bin/rke2 ]; then
  /var/lib/rancher/rke2/bin/rke2 --version
fi
REMOTE_DISCOVER_VERSION
)"
  if [ -n "${version}" ]; then
    printf '%s\n' "${version}"
    return 0
  fi

  remote_sudo_sh "${node}" <<'REMOTE_DISCOVER_VERSION_WITH_SUDO'
if [ -x /usr/local/bin/rke2 ]; then
  /usr/local/bin/rke2 --version
elif [ -x /usr/bin/rke2 ]; then
  /usr/bin/rke2 --version
elif [ -x /var/lib/rancher/rke2/bin/rke2 ]; then
  /var/lib/rancher/rke2/bin/rke2 --version
fi
REMOTE_DISCOVER_VERSION_WITH_SUDO
}

discover_remote_cluster_domain() {
  local node="$1"

  remote_sudo_sh "${node}" <<'REMOTE_DISCOVER_DOMAIN'
if [ -s /etc/rancher/rke2/config.yaml ]; then
  awk -F': *' '/^cluster-domain:/ {print $2; exit}' /etc/rancher/rke2/config.yaml
fi
REMOTE_DISCOVER_DOMAIN
}

discover_remote_keepalived_auth_pass() {
  local node="$1"

  remote_sudo_sh "${node}" <<'REMOTE_DISCOVER_KEEPALIVED_AUTH'
if [ -s /etc/keepalived/keepalived.conf ]; then
  awk '/^[[:space:]]*auth_pass[[:space:]]+/ {print $2; exit}' /etc/keepalived/keepalived.conf
fi
REMOTE_DISCOVER_KEEPALIVED_AUTH
}

discover_remote_keepalived_interface() {
  local node="$1"

  remote_sudo_sh "${node}" <<'REMOTE_DISCOVER_KEEPALIVED_INTERFACE'
if [ -s /etc/keepalived/keepalived.conf ]; then
  interface="$(awk '/^[[:space:]]*interface[[:space:]]+/ {print $2; exit}' /etc/keepalived/keepalived.conf)"
  if [ -n "${interface}" ]; then
    echo "${interface}"
    exit 0
  fi
fi
ip route show default 2>/dev/null | awk '{print $5; exit}'
REMOTE_DISCOVER_KEEPALIVED_INTERFACE
}

discover_remote_value_from_nodes() {
  local description="$1"
  local discoverer="$2"
  local node
  local value

  shift 2
  for node in "$@"; do
    node="${node//[[:space:]]/}"
    if [ -z "${node}" ]; then
      continue
    fi
    value="$("${discoverer}" "${node}" | sed -n '/[^[:space:]]/ {p; q;}')"
    if [ -n "${value}" ]; then
      echo "Discovered ${description} from ${node}." >&2
      printf '%s\n' "${value}"
      return 0
    fi
  done
  return 1
}

discover_remote_rke2_version_from_nodes() {
  local node
  local raw_version
  local normalized_version

  for node in "$@"; do
    node="${node//[[:space:]]/}"
    if [ -z "${node}" ]; then
      continue
    fi
    raw_version="$(discover_remote_rke2_version "${node}")"
    normalized_version="$(normalize_rke2_version "${raw_version}")"
    if [ -n "${normalized_version}" ]; then
      echo "Discovered RKE2 version from ${node}." >&2
      printf '%s\n' "${normalized_version}"
      return 0
    fi
  done
  return 1
}

rke2_version_drift_detected() {
  local requested
  local node
  local raw_version
  local installed_version
  local nodes=("$@")

  requested="$(normalize_rke2_version "${MIGRATION_RKE2_VERSION:-${RKE2_VERSION:-}}")"
  if [ -z "${requested}" ]; then
    return 1
  fi
  if [ "${#nodes[@]}" -eq 0 ] && [ -n "${MIGRATION_RKE2_NODES:-}" ]; then
    IFS=',' read -r -a nodes <<< "${MIGRATION_RKE2_NODES}"
  fi
  for node in "${nodes[@]}"; do
    node="${node//[[:space:]]/}"
    if [ -z "${node}" ]; then
      continue
    fi
    raw_version="$(discover_remote_rke2_version "${node}" 2>/dev/null || true)"
    installed_version="$(normalize_rke2_version "${raw_version}")"
    if [ -z "${installed_version}" ]; then
      continue
    fi
    if [ "${installed_version}" != "${requested}" ]; then
      echo "Requested RKE2 version ${requested}, but ${node} is running ${installed_version}; automatic cluster reconciliation is required." >&2
      return 0
    fi
  done
  return 1
}

write_kubeconfig_from_available_node() {
  local endpoint_host="$1"
  local endpoint_port="$2"
  local node
  local status
  local saw_missing_kubeconfig=false
  local saw_fetch_error=false

  for node in "${rke2_nodes[@]}"; do
    node="${node//[[:space:]]/}"
    if [ -z "${node}" ]; then
      continue
    fi
    if write_kubeconfig_from_node "${node}" "${endpoint_host}" "${endpoint_port}"; then
      return 0
    fi
    status=$?
    if [ "${status}" -eq 2 ]; then
      saw_missing_kubeconfig=true
    else
      saw_fetch_error=true
    fi
  done

  if [ "${saw_fetch_error}" != "true" ] && [ "${saw_missing_kubeconfig}" = "true" ]; then
    return 2
  fi
  return 1
}

prepare_remote_ansible_tmp_dirs() {
  local node
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local remote_tmp="/tmp/.ansible-${ssh_user}/tmp"
  local remote_tmp_parent="/tmp/.ansible-${ssh_user}"
  local ssh_options=()

  mapfile -t ssh_options < <(ssh_options_for_node)

  for node in "$@"; do
    node="${node//[[:space:]]/}"
    if [ -z "${node}" ]; then
      continue
    fi
    ssh "${ssh_options[@]}" "${ssh_user}@${node}" 'sh -s' -- "${remote_tmp_parent}" "${remote_tmp}" >/dev/null 2>&1 <<'REMOTE_PREPARE_ANSIBLE_TMP' || {
remote_tmp_parent="$1"
remote_tmp="$2"
umask 077
mkdir -p "${remote_tmp}"
chmod 700 "${remote_tmp_parent}" "${remote_tmp}"
REMOTE_PREPARE_ANSIBLE_TMP
        echo "Could not pre-create Ansible remote tmp ${remote_tmp} on ${node}; continuing and letting Ansible report details." >&2
      }
  done
}

run_cluster_repair() {
  extra_args=()
  if [ -n "${ANSIBLE_ARGS:-}" ]; then
    # shellcheck disable=SC2206
    extra_args=(${ANSIBLE_ARGS})
  fi

  echo "Reconciling bootstrap and RKE2 from ${INVENTORY_PATH}."
  ANSIBLE_CONFIG="${ANSIBLE_CONFIG_PATH}" \
    "${ANSIBLE_PLAYBOOK_BIN}" \
    -i "${INVENTORY_PATH}" \
    ansible/playbooks/bootstrap.yml \
    -e "cluster_engine=${ENGINE}" \
    -e "deployment_environment=${ENVIRONMENT}" \
    "${extra_args[@]}"

  ANSIBLE_CONFIG="${ANSIBLE_CONFIG_PATH}" \
    "${ANSIBLE_PLAYBOOK_BIN}" \
    -i "${INVENTORY_PATH}" \
    ansible/playbooks/install-cluster.yml \
    -e "cluster_engine=${ENGINE}" \
    -e "deployment_environment=${ENVIRONMENT}" \
    "${extra_args[@]}"
}

auto_repair_cluster_enabled() {
  case "${MIGRATION_AUTO_REPAIR_CLUSTER:-auto}" in
    true|True|TRUE|1|yes|Yes|YES|always|Always|ALWAYS)
      return 0
      ;;
    false|False|FALSE|0|no|No|NO|never|Never|NEVER)
      return 1
      ;;
    auto|Auto|AUTO)
      [ -n "${MIGRATION_RKE2_NODES:-}" ] || [ -f "${FALLBACK_INVENTORY_PATH}" ]
      return
      ;;
    *)
      echo "Unsupported MIGRATION_AUTO_REPAIR_CLUSTER=${MIGRATION_AUTO_REPAIR_CLUSTER}; use auto, true, or false." >&2
      return 1
      ;;
  esac
}

minimum_reachable_repair_nodes() {
  local original_node_count="$1"
  local configured="${MIGRATION_REPAIR_MIN_REACHABLE_RKE2_NODES:-auto}"

  if [ "${configured}" != "auto" ]; then
    printf '%s\n' "${configured}"
    return 0
  fi
  if [ "${original_node_count}" -ge 3 ]; then
    printf '2\n'
    return 0
  fi
  printf '1\n'
}

kubernetes_api_ready() {
  if ! command -v kubectl >/dev/null 2>&1; then
    return 0
  fi
  KUBECONFIG="${OPERATOR_KUBECONFIG_PATH}" kubectl get --raw=/readyz --request-timeout="${MIGRATION_KUBE_API_READY_TIMEOUT:-15s}" >/dev/null 2>&1 &&
    KUBECONFIG="${OPERATOR_KUBECONFIG_PATH}" kubectl get --raw=/version --request-timeout="${MIGRATION_KUBE_API_VERSION_TIMEOUT:-15s}" >/dev/null 2>&1 &&
    KUBECONFIG="${OPERATOR_KUBECONFIG_PATH}" kubectl get --raw=/openapi/v2 --request-timeout="${MIGRATION_KUBE_API_OPENAPI_TIMEOUT:-60s}" >/dev/null 2>&1
}

kubernetes_api_ready_verbose() {
  local output

  if ! command -v kubectl >/dev/null 2>&1; then
    return 0
  fi
  if ! output="$(KUBECONFIG="${OPERATOR_KUBECONFIG_PATH}" kubectl get --raw=/readyz --request-timeout="${MIGRATION_KUBE_API_READY_TIMEOUT:-15s}" 2>&1)"; then
    echo "Kubernetes API /readyz probe failed: ${output}" >&2
    return 1
  fi
  if ! output="$(KUBECONFIG="${OPERATOR_KUBECONFIG_PATH}" kubectl get --raw=/version --request-timeout="${MIGRATION_KUBE_API_VERSION_TIMEOUT:-15s}" 2>&1)"; then
    echo "Kubernetes API /version probe failed: ${output}" >&2
    return 1
  fi
  if ! output="$(KUBECONFIG="${OPERATOR_KUBECONFIG_PATH}" kubectl get --raw=/openapi/v2 --request-timeout="${MIGRATION_KUBE_API_OPENAPI_TIMEOUT:-60s}" 2>&1)"; then
    echo "Kubernetes API /openapi/v2 probe failed: ${output}" >&2
    return 1
  fi
  return 0
}

start_kubernetes_api_tunnel() {
  local node="$1"
  local remote_port="$2"
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local remote_host="${MIGRATION_KUBE_API_TUNNEL_REMOTE_HOST:-${node}}"
  local requested_port="${MIGRATION_KUBE_API_TUNNEL_PORT:-16443}"
  local socket_dir="${TMPDIR:-/tmp}/urban-platform-kubeapi"
  local socket_path
  local port
  local max_port
  local ssh_options=("-o" "ExitOnForwardFailure=yes")
  local node_ssh_options=()
  local ssh_error

  mapfile -t node_ssh_options < <(ssh_options_for_node)
  ssh_options+=("${node_ssh_options[@]}")

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
    echo "Trying SSH tunnel 127.0.0.1:${port} -> ${node}:${remote_host}:${remote_port}" >&2
    ssh_error="$(mktemp)"
    if ssh "${ssh_options[@]}" -fN -M -S "${socket_path}" \
      -L "127.0.0.1:${port}:${remote_host}:${remote_port}" \
      "${ssh_user}@${node}" 2>"${ssh_error}"; then
      rm -f "${ssh_error}"
      echo "${port}"
      return 0
    fi
    cat "${ssh_error}" >&2 || true
    rm -f "${socket_path}"
    if ! grep -Eiq 'address already in use|bind.*failed|cannot listen|port .* already' "${ssh_error}"; then
      rm -f "${ssh_error}"
      return 1
    fi
    rm -f "${ssh_error}"
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

  mapfile -t ssh_options < <(ssh_options_for_node)

  ssh -S "${socket_path}" -O exit "${ssh_options[@]}" "${ssh_user}@${node}" >/dev/null 2>&1 || true
  rm -f "${socket_path}"
}

show_remote_rke2_diagnostics() {
  local node="$1"

  echo "Remote RKE2 diagnostics for ${node}:" >&2
  remote_sudo_sh "${node}" <<'REMOTE_DIAGNOSTICS' >&2 || true
set -u
for service in rke2-server rke2-agent; do
  state="$(systemctl is-active "${service}" 2>/dev/null || true)"
  if [ -n "${state}" ] && [ "${state}" != "unknown" ]; then
    echo "${service}: ${state}"
  fi
done

if command -v ss >/dev/null 2>&1; then
  echo "listening RKE2 API ports:"
  ss -ltnp 2>/dev/null | awk 'NR == 1 || /:6443/ || /:9345/' || true
fi

echo "local /readyz probe:"
if [ -x /var/lib/rancher/rke2/bin/kubectl ]; then
  /var/lib/rancher/rke2/bin/kubectl --kubeconfig /etc/rancher/rke2/rke2.yaml get --raw=/readyz --request-timeout=10s || true
elif command -v kubectl >/dev/null 2>&1; then
  kubectl --kubeconfig /etc/rancher/rke2/rke2.yaml get --raw=/readyz --request-timeout=10s || true
elif command -v curl >/dev/null 2>&1; then
  curl -ksS --max-time 10 https://127.0.0.1:6443/readyz || true
else
  echo "kubectl/curl is not available"
fi
REMOTE_DIAGNOSTICS
}

if [ "${ENGINE}" != "rke2" ]; then
  echo "Skipping automatic kubeconfig repair for ENGINE=${ENGINE}; using existing kubectl context."
  exit 0
fi

repair_required_due_to_version_drift=false

if [ "${OPERATOR_KUBECONFIG_FORCE_REPAIR:-false}" != "true" ] && [ -s "${OPERATOR_KUBECONFIG_PATH}" ] && command -v kubectl >/dev/null 2>&1 && kubernetes_api_ready; then
  if rke2_version_drift_detected; then
    if ! auto_repair_cluster_enabled; then
      echo "Existing operator kubeconfig is ready, but installed RKE2 does not match MIGRATION_RKE2_VERSION." >&2
      echo "Enable MIGRATION_AUTO_REPAIR_CLUSTER=true or run the cluster upgrade/rebuild workflow before importing workloads." >&2
      exit 1
    fi
    repair_required_due_to_version_drift=true
  else
    echo "Existing operator kubeconfig is ready: ${OPERATOR_KUBECONFIG_PATH}"
    exit 0
  fi
fi

validate_become_password_input

if [ ! -f "${INVENTORY_PATH}" ] && [ -z "${MIGRATION_RKE2_NODES:-}" ] && [ -f "${FALLBACK_INVENTORY_PATH}" ]; then
  discovered_rke2_nodes="$(
    sed -nE "s/^[[:space:]]*ansible_host:[[:space:]]*['\"]?([^'\"]+)['\"]?[[:space:]]*$/\1/p" "${FALLBACK_INVENTORY_PATH}" \
      | paste -sd, -
  )"
  if [ -n "${discovered_rke2_nodes}" ]; then
    export MIGRATION_RKE2_NODES="${discovered_rke2_nodes}"
    echo "Recovered MIGRATION_RKE2_NODES from ${FALLBACK_INVENTORY_PATH}."
  fi
fi
recover_become_password_from_fallback_inventory

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
  prompt_for_become_password_if_needed "${rke2_nodes[@]}"
  echo "Existing operator kubeconfig is not ready; probing RKE2 nodes from MIGRATION_RKE2_NODES for a reachable API endpoint."

  explicit_cluster_vip="${MIGRATION_CLUSTER_VIP:-${CLUSTER_VIP:-}}"
  discovered_cluster_vip=""
  if [ -z "${explicit_cluster_vip}" ]; then
    for node in "${rke2_nodes[@]}"; do
      node="${node//[[:space:]]/}"
      if [ -z "${node}" ]; then
        continue
      fi
      discovered_cluster_vip="$(discover_remote_cluster_vip "${node}")"
      if [ -n "${discovered_cluster_vip}" ]; then
        break
      fi
    done
  fi
  cluster_vip="${explicit_cluster_vip:-${discovered_cluster_vip:-${first_rke2_node}}}"
  cluster_vip_matches_node=false
  for node in "${rke2_nodes[@]}"; do
    node="${node//[[:space:]]/}"
    if [ "${cluster_vip}" = "${node}" ]; then
      cluster_vip_matches_node=true
      break
    fi
  done
  use_load_balancers=false
  if [ -n "${explicit_cluster_vip}" ] || { [ -n "${discovered_cluster_vip}" ] && [ "${cluster_vip_matches_node}" != "true" ]; }; then
    use_load_balancers=true
  fi
  if [ -n "${explicit_cluster_vip}" ] || [ -n "${discovered_cluster_vip}" ]; then
    kubernetes_api_port="${MIGRATION_KUBERNETES_API_VIP_PORT:-${KUBERNETES_API_VIP_PORT:-7443}}"
  else
    kubernetes_api_port="${MIGRATION_KUBERNETES_API_VIP_PORT:-${KUBERNETES_API_VIP_PORT:-6443}}"
  fi

  if [ -s "${OPERATOR_KUBECONFIG_PATH}" ]; then
    original_kubeconfig="$(mktemp)"
    existing_kubeconfig_ready=false
    endpoint_specs=()
    tls_server_name="${MIGRATION_KUBE_API_TLS_SERVER_NAME:-${cluster_vip}}"
    cp "${OPERATOR_KUBECONFIG_PATH}" "${original_kubeconfig}"

    for node in "${rke2_nodes[@]}"; do
      node="${node//[[:space:]]/}"
      if [ -n "${node}" ]; then
        endpoint_specs+=("${node}:6443")
      fi
    done
    if [ -n "${explicit_cluster_vip}" ] || [ -n "${discovered_cluster_vip}" ]; then
      endpoint_specs+=("${cluster_vip}:${kubernetes_api_port}")
    fi

    for endpoint_spec in "${endpoint_specs[@]}"; do
      endpoint_host="${endpoint_spec%:*}"
      endpoint_port="${endpoint_spec##*:}"
      if [ -z "${endpoint_host}" ] || [ -z "${endpoint_port}" ]; then
        continue
      fi
      echo "Trying existing operator kubeconfig against https://${endpoint_host}:${endpoint_port}"
      if rewrite_existing_kubeconfig_endpoint "${endpoint_host}" "${endpoint_port}" "${tls_server_name}" && kubernetes_api_ready_verbose; then
        echo "Operator kubeconfig ready: ${OPERATOR_KUBECONFIG_PATH} (endpoint https://${endpoint_host}:${endpoint_port})"
        existing_kubeconfig_ready=true
        break
      fi
    done

    if [ "${existing_kubeconfig_ready}" != "true" ] && [ "${MIGRATION_KUBE_API_TUNNEL:-auto}" != "false" ]; then
      echo "Existing kubeconfig was not ready through direct endpoints; trying SSH tunnel fallback."
      for tunnel_node in "${rke2_nodes[@]}"; do
        tunnel_node="${tunnel_node//[[:space:]]/}"
        if [ -z "${tunnel_node}" ]; then
          continue
        fi
        if ! tunnel_port="$(start_kubernetes_api_tunnel "${tunnel_node}" "6443")"; then
          echo "Could not open an SSH tunnel through ${tunnel_node}; trying the next node." >&2
          continue
        fi
        if rewrite_existing_kubeconfig_endpoint "127.0.0.1" "${tunnel_port}" "${tls_server_name}" && kubernetes_api_ready_verbose; then
          echo "Operator kubeconfig ready: ${OPERATOR_KUBECONFIG_PATH} (endpoint https://127.0.0.1:${tunnel_port} via SSH tunnel ${tunnel_node})"
          existing_kubeconfig_ready=true
          break
        fi
        echo "Kubernetes API was not ready through SSH tunnel via ${tunnel_node}; trying the next node." >&2
        stop_kubernetes_api_tunnel "${tunnel_node}" "6443" "${tunnel_port}"
      done
    fi

    if [ "${existing_kubeconfig_ready}" = "true" ]; then
      rm -f "${original_kubeconfig}"
      if rke2_version_drift_detected "${rke2_nodes[@]}"; then
        if ! auto_repair_cluster_enabled; then
          echo "Existing operator kubeconfig is ready, but installed RKE2 does not match MIGRATION_RKE2_VERSION." >&2
          echo "Enable MIGRATION_AUTO_REPAIR_CLUSTER=true or run the cluster upgrade/rebuild workflow before importing workloads." >&2
          exit 1
        fi
        repair_required_due_to_version_drift=true
      else
        exit 0
      fi
    else
      install -m 0600 "${original_kubeconfig}" "${OPERATOR_KUBECONFIG_PATH}"
      rm -f "${original_kubeconfig}"
      if ! auto_repair_cluster_enabled; then
        echo "Existing operator kubeconfig could not reach the Kubernetes API through the VIP, node APIs, or SSH tunnel fallback." >&2
        echo "Set MIGRATION_SSH_USER/MIGRATION_SSH_KEY if SSH tunneling is required, or fix the VIP/API path and rerun." >&2
        exit 1
      fi
    fi
  fi

  ansible_user_for_nodes="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  cluster_domain="${MIGRATION_CLUSTER_DOMAIN:-${CLUSTER_DOMAIN:-}}"
  if [ -z "${cluster_domain}" ]; then
    cluster_domain="$(discover_remote_value_from_nodes "cluster domain" discover_remote_cluster_domain "${rke2_nodes[@]}" || true)"
  fi
  cluster_domain="${cluster_domain:-cluster.local}"

  rke2_version="${MIGRATION_RKE2_VERSION:-${RKE2_VERSION:-}}"
  rke2_version_source="provided"
  if [ -z "${rke2_version}" ]; then
    rke2_version="$(discover_remote_rke2_version_from_nodes "${rke2_nodes[@]}" || true)"
    rke2_version_source="discovered"
  fi
  rke2_version="$(normalize_rke2_version "${rke2_version}")"
  if [ -z "${rke2_version}" ]; then
    echo "Could not discover a pinned RKE2 version from any MIGRATION_RKE2_NODES host." >&2
    echo "No node returned a version like v1.36.1+rke2r2, and this automation will not choose an unpinned latest version." >&2
    echo "Set MIGRATION_RKE2_VERSION=v1.36.1+rke2r2 once for a fresh cluster install." >&2
    exit 1
  fi

  rke2_token="${MIGRATION_RKE2_TOKEN:-${RKE2_TOKEN:-}}"
  rke2_token_source="provided"
  if [ -z "${rke2_token}" ]; then
    rke2_token="$(discover_remote_value_from_nodes "RKE2 token" discover_remote_rke2_token "${rke2_nodes[@]}" || true)"
    rke2_token_source="discovered"
  fi
  if [ -z "${rke2_token}" ]; then
    if [ "${rke2_version_source}" = "discovered" ]; then
      echo "RKE2 is already installed on ${first_rke2_node}, but the existing cluster token could not be read." >&2
      echo "Fix passwordless sudo for ${ansible_user_for_nodes} or set MIGRATION_BECOME_PASSWORD_FILE; existing clusters must reuse the real RKE2 token." >&2
      exit 1
    fi
    rke2_token="$(generate_rke2_token)"
    rke2_token_source="generated"
  fi
  if [ -z "${rke2_token}" ]; then
    echo "Could not discover or generate an RKE2 token for the temporary inventory." >&2
    echo "Install openssl or python3 on the operator, or export MIGRATION_RKE2_TOKEN before running this target." >&2
    exit 1
  fi
  export MIGRATION_RKE2_TOKEN="${rke2_token}"

  become_password="$(migration_become_password)"

  keepalived_auth_pass="${MIGRATION_KEEPALIVED_AUTH_PASS:-${KEEPALIVED_AUTH_PASS:-}}"
  keepalived_auth_source="provided"
  keepalived_interface="${MIGRATION_KEEPALIVED_INTERFACE:-${KEEPALIVED_INTERFACE:-}}"
  if [ "${use_load_balancers}" = "true" ]; then
    if [ -z "${keepalived_auth_pass}" ]; then
      keepalived_auth_pass="$(discover_remote_value_from_nodes "Keepalived auth" discover_remote_keepalived_auth_pass "${rke2_nodes[@]}" || true)"
      keepalived_auth_source="discovered"
    fi
    if [ -z "${keepalived_auth_pass}" ]; then
      keepalived_auth_pass="$(generate_keepalived_auth_pass)"
      keepalived_auth_source="generated"
    fi
    if [ -z "${keepalived_auth_pass}" ]; then
      echo "Could not discover or generate a Keepalived auth password for the temporary inventory." >&2
      echo "Install openssl or python3 on the operator, or export MIGRATION_KEEPALIVED_AUTH_PASS before running this target." >&2
      exit 1
    fi
    if [ -z "${keepalived_interface}" ]; then
      keepalived_interface="$(discover_remote_value_from_nodes "Keepalived interface" discover_remote_keepalived_interface "${rke2_nodes[@]}" || true)"
    fi
    keepalived_interface="${keepalived_interface:-eth0}"
  fi

  if [ "${MIGRATION_SKIP_UNREACHABLE_RKE2_NODES:-auto}" != "false" ]; then
    original_rke2_node_count="${#rke2_nodes[@]}"
    mapfile -t reachable_rke2_nodes < <(filter_ssh_reachable_nodes "${rke2_nodes[@]}")
    minimum_reachable_nodes="$(minimum_reachable_repair_nodes "${original_rke2_node_count}")"
    if [ "${#reachable_rke2_nodes[@]}" -eq 0 ]; then
      echo "No RKE2 nodes are reachable over SSH; cannot run automatic cluster repair." >&2
      exit 1
    fi
    if auto_repair_cluster_enabled && [ "${#reachable_rke2_nodes[@]}" -lt "${minimum_reachable_nodes}" ]; then
      echo "Only ${#reachable_rke2_nodes[@]}/${original_rke2_node_count} RKE2 node(s) are reachable over SSH." >&2
      echo "Automatic HA repair requires at least ${minimum_reachable_nodes} reachable node(s) to protect embedded-etcd quorum." >&2
      echo "Power on or reconnect the missing VM(s), or override MIGRATION_REPAIR_MIN_REACHABLE_RKE2_NODES only for an intentional lab recovery." >&2
      exit 1
    fi
    if [ "${#reachable_rke2_nodes[@]}" -lt "${original_rke2_node_count}" ]; then
      echo "Continuing automatic cluster repair with ${#reachable_rke2_nodes[@]}/${original_rke2_node_count} SSH-reachable RKE2 nodes."
    fi
    rke2_nodes=("${reachable_rke2_nodes[@]}")
    first_rke2_node="${rke2_nodes[0]}"
    if [ -z "${explicit_cluster_vip}" ] && [ -z "${discovered_cluster_vip}" ]; then
      cluster_vip="${first_rke2_node}"
    fi
  fi

  {
    printf 'all:\n'
    printf '  vars:\n'
    printf '    ansible_user: %s\n' "$(yaml_quote "${ansible_user_for_nodes}")"
    printf '    ansible_python_interpreter: /usr/bin/python3\n'
    printf '    ansible_remote_tmp: %s\n' "$(yaml_quote "/tmp/.ansible-${ansible_user_for_nodes}/tmp")"
    if [ -n "${MIGRATION_SSH_KEY:-}" ]; then
      printf '    ansible_ssh_private_key_file: %s\n' "$(yaml_quote "${MIGRATION_SSH_KEY}")"
    fi
    if [ -n "${become_password}" ]; then
      printf '    ansible_become_password: %s\n' "$(yaml_quote "${become_password}")"
    fi
    printf '    cluster_engine: rke2\n'
    printf '    cluster_vip: %s\n' "$(yaml_quote "${cluster_vip}")"
    printf '    cluster_domain: %s\n' "$(yaml_quote "${cluster_domain}")"
    printf '    rke2_token: %s\n' "$(yaml_quote "${rke2_token}")"
    printf '    rke2_version: %s\n' "$(yaml_quote "${rke2_version}")"
    printf '    kubernetes_api_vip_port: %s\n' "${kubernetes_api_port}"
    if [ "${use_load_balancers}" = "true" ]; then
      printf '    keepalived_auth_pass: %s\n' "$(yaml_quote "${keepalived_auth_pass}")"
      printf '    keepalived_interface: %s\n' "$(yaml_quote "${keepalived_interface}")"
    fi
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
      printf '          ansible_host: %s\n' "$(yaml_quote "${node}")"
      printf '          node_ip: %s\n' "$(yaml_quote "${node}")"
      index=$((index + 1))
    done
    printf '    rke2_agents:\n'
    printf '      hosts: {}\n'
    printf '    load_balancers:\n'
    if [ "${use_load_balancers}" = "true" ]; then
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
    else
      printf '      hosts: {}\n'
    fi
  } > "${FALLBACK_INVENTORY_PATH}"
  chmod 0600 "${FALLBACK_INVENTORY_PATH}" 2>/dev/null || true
  INVENTORY_PATH="${FALLBACK_INVENTORY_PATH}"
  echo "Generated temporary operator inventory from MIGRATION_RKE2_NODES: ${INVENTORY_PATH}"
  echo "Temporary inventory RKE2 inputs: token ${rke2_token_source}, version ${rke2_version_source} (${rke2_version}), cluster domain ${cluster_domain:+ready}."
  if [ "${use_load_balancers}" = "true" ]; then
    echo "Temporary inventory HA inputs: cluster VIP ready, Keepalived auth ${keepalived_auth_source}, interface ${keepalived_interface}."
  else
    echo "Temporary inventory HA inputs: no cluster VIP detected; using direct node API endpoints."
  fi
  echo "Operator kubeconfig endpoint candidates will use port ${kubernetes_api_port}"
  prepare_remote_ansible_tmp_dirs "${rke2_nodes[@]}"
  if [ "${repair_required_due_to_version_drift}" = "true" ]; then
    run_cluster_repair
    export MIGRATION_AUTO_REPAIR_CLUSTER=false
    echo "Retrying operator kubeconfig after automatic RKE2 version reconciliation."
    exec bash "$0"
  fi
  if [ -n "${explicit_cluster_vip}" ] || [ -n "${discovered_cluster_vip}" ]; then
    endpoint_candidates=("${cluster_vip}")
  else
    endpoint_candidates=("${rke2_nodes[@]}")
  fi

  selected_endpoint=""
  fresh_cluster=false
  for endpoint_candidate in "${endpoint_candidates[@]}"; do
    endpoint_candidate="${endpoint_candidate//[[:space:]]/}"
    if [ -z "${endpoint_candidate}" ]; then
      continue
    fi
    echo "Trying Kubernetes API endpoint https://${endpoint_candidate}:${kubernetes_api_port}"
    if write_kubeconfig_from_available_node "${endpoint_candidate}" "${kubernetes_api_port}"; then
      if kubernetes_api_ready; then
        selected_endpoint="${endpoint_candidate}"
        break
      fi
      echo "Kubernetes API endpoint https://${endpoint_candidate}:${kubernetes_api_port} is not ready from this operator; trying the next endpoint." >&2
      continue
    fi
    kubeconfig_status=$?
    if [ "${kubeconfig_status}" -eq 2 ]; then
      fresh_cluster=true
      echo "Skipping remaining endpoint probes until RKE2 creates the first kubeconfig." >&2
      break
    else
      echo "Could not fetch kubeconfig before probing https://${endpoint_candidate}:${kubernetes_api_port}; this is expected on a fresh cluster." >&2
      continue
    fi
  done

  if [ -z "${selected_endpoint}" ]; then
    if [ "${MIGRATION_KUBE_API_TUNNEL:-auto}" = "false" ] && [ "${fresh_cluster}" != "true" ]; then
      echo "No Kubernetes API endpoint from MIGRATION_RKE2_NODES became ready." >&2
      echo "Check RKE2 server health/firewall rules, or set MIGRATION_CLUSTER_VIP and MIGRATION_KUBERNETES_API_VIP_PORT to the reachable API endpoint." >&2
      exit 1
    fi
    if [ "${fresh_cluster}" = "true" ]; then
      echo "Fresh RKE2 cluster detected; skipping SSH tunnel fallback until bootstrap creates kubeconfig." >&2
    else
      echo "No node API endpoint was reachable directly; trying SSH tunnel fallback." >&2
      for tunnel_node in "${rke2_nodes[@]}"; do
        tunnel_node="${tunnel_node//[[:space:]]/}"
        if [ -z "${tunnel_node}" ]; then
          continue
        fi
        if ! tunnel_port="$(start_kubernetes_api_tunnel "${tunnel_node}" "6443")"; then
          echo "Could not open an SSH tunnel through ${tunnel_node}; trying the next node." >&2
          continue
        fi
        if write_kubeconfig_from_available_node "127.0.0.1" "${tunnel_port}"; then
          if kubernetes_api_ready; then
            selected_endpoint="127.0.0.1:${tunnel_port} via SSH tunnel ${tunnel_node}"
            break
          fi
          echo "Kubernetes API was not ready through SSH tunnel via ${tunnel_node}; trying the next node." >&2
          stop_kubernetes_api_tunnel "${tunnel_node}" "6443" "${tunnel_port}"
          continue
        fi
        kubeconfig_status=$?
        if [ "${kubeconfig_status}" -eq 2 ]; then
          fresh_cluster=true
          echo "RKE2 kubeconfig is still absent; stopping tunnel probes and proceeding to repair." >&2
          stop_kubernetes_api_tunnel "${tunnel_node}" "6443" "${tunnel_port}"
          break
        fi
        echo "Could not fetch kubeconfig through SSH tunnel via ${tunnel_node}; trying the next node." >&2
        stop_kubernetes_api_tunnel "${tunnel_node}" "6443" "${tunnel_port}"
      done
    fi

    if [ -z "${selected_endpoint}" ]; then
      if [ "${fresh_cluster}" = "true" ]; then
        echo "RKE2 has not created a kubeconfig yet; automatic cluster reconciliation will install the first server." >&2
      else
        echo "Kubernetes API was not ready through direct endpoints or SSH tunnel fallback." >&2
        echo "Check RKE2 service health and passwordless sudo for ${ansible_user_for_nodes}." >&2
        for diagnostic_node in "${rke2_nodes[@]}"; do
          diagnostic_node="${diagnostic_node//[[:space:]]/}"
          if [ -n "${diagnostic_node}" ]; then
            show_remote_rke2_diagnostics "${diagnostic_node}"
          fi
        done
      fi
      if auto_repair_cluster_enabled; then
        run_cluster_repair
        export MIGRATION_AUTO_REPAIR_CLUSTER=false
        echo "Retrying operator kubeconfig after automatic cluster reconciliation."
        exec bash "$0"
      fi
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
  kubernetes_api_ready_verbose >/dev/null
fi

echo "Operator kubeconfig ready: ${OPERATOR_KUBECONFIG_PATH}"
