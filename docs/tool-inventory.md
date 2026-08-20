# Tool Inventory

The machine-readable contract is [`config/tooling.yaml`](../config/tooling.yaml), and the checker is [`scripts/tools/tool_inventory.py`](../scripts/tools/tool_inventory.py). It distinguishes mandatory tools from optional accelerators and supports alternatives such as Docker or Podman.

## Scopes

- `validation`: repository syntax, policy, YAML, and shell checks.
- `deployment`: Ansible, Helm, Helmfile, kubectl, SSH, and TLS tooling.
- `import`: image, database, and RKE2 preload prerequisites.
- `load-test`: the built-in Python runner plus optional external load/I/O tools.
- `all`: the union of the scopes above.

Check a scope and write a public-safe report:

```bash
make tool-inventory TOOL_INVENTORY_SCOPE=validation
make tool-inventory TOOL_INVENTORY_SCOPE=deployment
make tool-inventory TOOL_INVENTORY_SCOPE=import
make tool-inventory TOOL_INVENTORY_SCOPE=load-test
```

The report contains only tool names, versions, and generic availability. It does not inspect kubeconfig contents, private inventories, credentials, registry names, or command arguments beyond version probes.

## Mandatory And Optional Choices

The native Python load runner does not require k6, Vegeta, or hey. Docker and Podman are interchangeable for image workflows, while PostgreSQL client tooling is optional when the import path does not perform dump/restore work. Optional tools are shown as `OPTIONAL-MISSING`; mandatory tools fail the check unless `--no-fail` is used deliberately for an inventory-only inspection.

CI runs the inventory in non-blocking mode because the CI image already owns its prerequisite installation. Operator readiness and deployment hosts should run the relevant scope without `--no-fail` before mutation.
