# Lab Capacity And Progressive Deploy

The default lab path is designed for constrained RKE2 validation clusters, not
for full production load. A three-node lab with 4 CPU cores and 4 GiB RAM per
node can rehearse the platform and selected imported workloads, but it should
not start every database, optional capability, observability backend, and
application service at once.

## Article 10 Baseline

Generate the public-safe lab capacity plan:

```bash
make capacity-preflight
make lab-deploy-plan
```

The command writes:

- `reports/capacity-preflight.md`: public-safe fail-fast capacity guard for
  deploy/import intent
- `reports/lab-deploy-plan.md`: public-safe capacity and progressive deploy
  report
- `reports/lab-deploy-values.yaml`: optional first-wave lab override

For a 3-node, 4-core, 4 GiB lab:

```bash
make lab-deploy-plan \
  LAB_DEPLOY_PROFILE=three-node-4g \
  LAB_DEPLOY_NODE_COUNT=3 \
  LAB_DEPLOY_NODE_CPU=4 \
  LAB_DEPLOY_NODE_MEMORY=4Gi
```

Then, after review, a first-wave lab deploy can use the generated override:

```bash
make capacity-preflight
make deploy-auto HELM_EXTRA_ARGS="-f reports/lab-deploy-values.yaml"
```

For autoscaling or right-sizing decisions, run the separate scaling policy
planner after the lab capacity report:

```bash
make scaling-policy-plan SCALING_POLICY_PROFILE=lab-rightsize IMPORT_REDACT=true
```

## Progressive Waves

Use small waves instead of a single all-at-once deployment:

1. Foundation: namespace, storage class, operators, kubeconfig, and cluster
   health.
2. Edge: Traefik, web gateway, TLS, and one root application route.
3. Core data: a small database subset, Kafka, ZooKeeper, and Redis.
4. Imported workloads: one import batch at a time.
5. Optional observability: Prometheus/Grafana or logging/search only after
   capacity is proven.

## Lab Guardrails

- Keep `global.replicaOverride=1`.
- Keep `global.skipPlaceholderWorkloads=true`.
- Keep autoscaling disabled until metrics are installed.
- Keep observability, backups, and optional platform capabilities disabled.
- Disable Kafka UI and Zabbix agent for the first pass unless those features
  are under test.
- Enable only a small database subset first.
- Use `MIGRATION_IMPORT_BATCH=1`, then continue with later batches after each
  health check passes.
- Keep `MIGRATION_IMPORT_BATCH=auto` for `import-auto`; never use `all` on a
  constrained lab until capacity has been proven.

## Production Difference

Production should not use the generated lab override. It needs a real capacity
plan, HA replicas, private-registry image promotion, backup/restore evidence,
monitoring CRDs, and database target maps reviewed before `MIGRATION_PROFILE`
is changed to `production`.

For production dry runs, pass a private evidence path to the preflight and keep
that evidence outside the repository:

```bash
make capacity-preflight \
  CAPACITY_PREFLIGHT_ENV_PROFILE=production \
  CAPACITY_PREFLIGHT_EVIDENCE=/path/to/private/capacity-evidence.md
```
