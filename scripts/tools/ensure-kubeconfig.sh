#!/usr/bin/env bash
set -euo pipefail

ENVIRONMENT="${ENV:-prod}"
ENGINE="${ENGINE:-rke2}"
INVENTORY_PATH="${INVENTORY:-inventories/${ENVIRONMENT}/hosts.yml}"
ANSIBLE_CONFIG_PATH="${ANSIBLE_CONFIG:-ansible/ansible.cfg}"
ANSIBLE_PLAYBOOK_BIN="${ANSIBLE_PLAYBOOK:-ansible-playbook}"
OPERATOR_KUBECONFIG_PATH="${OPERATOR_KUBECONFIG:-${KUBECONFIG:-${HOME}/.kube/config}}"

if [ "${ENGINE}" != "rke2" ]; then
  echo "Skipping automatic kubeconfig repair for ENGINE=${ENGINE}; using existing kubectl context."
  exit 0
fi

if [ ! -f "${INVENTORY_PATH}" ]; then
  echo "Missing inventory ${INVENTORY_PATH}; cannot repair operator kubeconfig." >&2
  exit 1
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
  KUBECONFIG="${OPERATOR_KUBECONFIG_PATH}" kubectl version --request-timeout=10s >/dev/null
fi

echo "Operator kubeconfig ready: ${OPERATOR_KUBECONFIG_PATH}"
