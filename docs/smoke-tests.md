# Post-Migration Smoke Tests And Health Probes

The smoke-test planner defines the checks that must pass after an import,
restore, deployment, or cutover. It is disabled by default and public-safe:
committed files describe probe intent, while private endpoints, credentials,
database DSNs, service names, and customer identifiers stay on the operator
machine or in the approved private evidence system.

## Plan Command

Generate the production smoke-test plan without running active probes:

```bash
make smoke-test-plan SMOKE_TEST_PROFILE=production-smoke IMPORT_REDACT=true
```

The command writes:

- `reports/smoke-test-plan.md`
- `reports/smoke-test-values.yaml`

Use `SMOKE_TEST_PROFILE=lab-smoke` for constrained lab imports and
`SMOKE_TEST_PROFILE=staging-smoke` for route or integration rehearsals.

## Probe Categories

Profiles can require these categories:

- Kubernetes rollout status for generated Deployments and StatefulSets.
- ClusterIP Service DNS and endpoint readiness.
- Ingress HTTP/TLS route checks through the selected ingress class.
- TCP backend port reachability.
- Database connection checks for PostgreSQL, PostGIS, and TimescaleDB,
  including extension readiness.
- Messaging connection checks for Redis and Kafka.
- messaging broker evidence from private runners when the profile requires it.
- External synthetic transactions from a private runner.

## Execution Model

The planner does not run private probes from CI. Active smoke tests should run
only from a trusted operator workstation, a private Kubernetes Job, or an
approved external monitor with network access to the target environment.

The generated Helm overlay keeps `smokeTesting.enabled` and
`smokeTesting.execution.enabled` set to `false`. Operators can use the overlay
as review evidence, then enable an execution runner in a private values file
when ownership, RBAC, network policy, and rollback expectations are approved.

## Cutover Use

For production cutover, generate smoke-test intent before the cutover gate:

```bash
make smoke-test-plan SMOKE_TEST_PROFILE=production-smoke IMPORT_REDACT=true
make cutover-gate-plan CUTOVER_GATES_PROFILE=production-cutover IMPORT_REDACT=true
```

Smoke-test evidence complements the cutover gate. It does not approve DNS
changes, traffic switching, rollback ownership, or customer-facing release
approval by itself.
