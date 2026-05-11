# Cluster Bootstrap Safety

Bootstrap is the riskiest part of this repository because it changes remote hosts, installs cluster services, and renders token-bearing configuration. The default workflow is now preflight-first and confirmation-gated for production.

## Required Flow

```bash
cp inventories/example/hosts.yml inventories/prod/hosts.yml
$EDITOR inventories/prod/hosts.yml

make preflight ENV=prod ENGINE=rke2
make bootstrap-check ENV=prod ENGINE=rke2
make install-cluster-check ENV=prod ENGINE=rke2

make bootstrap ENV=prod ENGINE=rke2 CONFIRM_PROD=true
make install-cluster ENV=prod ENGINE=rke2 CONFIRM_PROD=true
```

`bootstrap` and `install-cluster` refuse to mutate `ENV=prod` unless `CONFIRM_PROD=true` is present.

## Inventory Requirements

Production inventory must replace every placeholder:

- `rke2_token` or `k3s_token` must come from Ansible Vault, SOPS, or another secret workflow.
- `rke2_version` must be pinned, for example `vX.Y.Z+rke2rN`.
- `cluster_vip` and `cluster_domain` must point to your real control-plane endpoint.
- `keepalived_auth_pass` must be set through a secret workflow.
- Every host must define `ansible_host`; `node_ip` should be explicit when it differs.

Do not commit real inventory, tokens, VIPs, node addresses, or disclosure-related infrastructure names.

## Ansible Safety Defaults

- SSH host key checking is enabled.
- Preflight checks validate inventory shape and required secret/version inputs before mutating hosts.
- Check-mode targets use `--check --diff`.
- Token-bearing RKE2, K3s, and Keepalived templates have diffs disabled.
- RKE2 control-plane install is staged: first server, then remaining servers one at a time, then agents in batches.
- RKE2 kubeconfig mode is `0600`, and RKE2 secrets encryption is enabled.
- HAProxy and Keepalived templates are validated before replacement.

## Operator Notes

Use `ANSIBLE_ARGS` for a controlled limit or extra vars:

```bash
make bootstrap-check ENV=prod ENGINE=rke2 ANSIBLE_ARGS="--limit cip-cp-01"
```

Use `ansible-vault` or your existing secret manager for inventory secrets; never rely on placeholder values outside the example inventory.

## References

- Ansible check mode and diff mode: https://docs.ansible.com/projects/ansible/latest/playbook_guide/playbooks_checkmode.html
- Ansible playbook syntax check: https://docs.ansible.com/ansible/2.9/cli/ansible-playbook.html
- RKE2 configuration file: https://docs.rke2.io/install/configuration
- RKE2 secrets encryption: https://docs.rke2.io/security/secrets_encryption
