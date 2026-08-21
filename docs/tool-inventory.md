# Tool Inventory

The machine-readable contract is [`config/tooling.yaml`](../config/tooling.yaml), and the checker is [`scripts/tools/tool_inventory.py`](../scripts/tools/tool_inventory.py). It distinguishes mandatory tools from optional accelerators and supports alternatives such as Docker or Podman.

## Scopes

- `validation`: repository syntax, policy, YAML, and shell checks.
- `deployment`: Ansible, Helm, Helmfile, kubectl, SSH, and TLS tooling.
- `import`: image, database, and RKE2 preload prerequisites.
- `load-test`: the built-in Python fallback plus optional k6, Locust, JMeter, Gatling, Artillery, Fortio, Vegeta, wrk2, Apache Kafka performance tools, PostgreSQL pgbench, and I/O tools.
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

The default load-test runner is k6, but no load-test tool is mandatory for repository validation or deployment. The native Python runner remains an explicit fallback. Optional tools are shown as `OPTIONAL-MISSING`; mandatory tools fail the check unless `--no-fail` is used deliberately for an inventory-only inspection.

CI runs the inventory in non-blocking mode because the CI image already owns its prerequisite installation. Operator readiness and deployment hosts should run the relevant scope without `--no-fail` before mutation.
