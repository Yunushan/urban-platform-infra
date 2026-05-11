#!/usr/bin/env bash
set -euo pipefail
ENV="${ENV:-prod}"
ENGINE="${ENGINE:-rke2}"
CONFIRM_PROD="${CONFIRM_PROD:-false}"
INVENTORY="inventories/${ENV}/hosts.yml"

if [ ! -f "$INVENTORY" ]; then
  echo "Missing inventory $INVENTORY. Copy inventories/example/hosts.yml first." >&2
  exit 1
fi
if [ "$ENV" = "prod" ] && [ "$CONFIRM_PROD" != "true" ]; then
  echo "Refusing to mutate prod without CONFIRM_PROD=true. Run preflight/check targets first." >&2
  exit 2
fi
ansible-galaxy collection install -r ansible/requirements.yml
ansible-playbook -i "$INVENTORY" ansible/playbooks/preflight.yml -e cluster_engine="$ENGINE" -e deployment_environment="$ENV"
ansible-playbook -i "$INVENTORY" ansible/playbooks/bootstrap.yml -e cluster_engine="$ENGINE" -e deployment_environment="$ENV"
ansible-playbook -i "$INVENTORY" ansible/playbooks/install-cluster.yml -e cluster_engine="$ENGINE" -e deployment_environment="$ENV"
