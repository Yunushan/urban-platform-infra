# Operator Workflows

This page collects the main one-command workflows so operators do not have to stitch together ad hoc command chains. The commands are safe to copy because they use placeholders for private paths, node names, hosts, and registry values.

## Local Readiness

Run this before deployment, import, or release work:

```bash
make operator-ready
```

It runs the local setup, workstation doctor, CI contract check, private-data audit, capacity preflight, repository validation, image-policy validation, YAML lint, and ShellCheck path in one place. Reports written under `reports/` are ignored by Git and public-safe unless a command explicitly says it generated a private report.

## Capacity Preflight

Before a deploy or import tries to mutate a constrained lab, run the fail-fast local capacity guard:

```bash
make capacity-preflight
```

It writes `reports/capacity-preflight.md` from committed values and public-safe sizing inputs. It fails on hard CPU, memory, pod-count, unsafe lab batch, or production-without-evidence errors, and warns when a first-wave lab overlay is required.

## Cluster Health

When the Kubernetes API, VIP, HAProxy, Keepalived, SSH, sudo, or kubeconfig path is unclear:

```bash
make cluster-doctor MIGRATION_RKE2_NODES=node-01,node-02,node-03
```

Use the guarded repair path only when you intend to reconcile kubeconfig/RKE2 health:

```bash
make cluster-repair MIGRATION_RKE2_NODES=node-01,node-02,node-03
```

## Lab Deployment

For a constrained lab, generate the public-safe profile overlay first, then run the auto-recovery deployment path:

```bash
make environment-profile-plan ENV_PROFILE=lab IMPORT_REDACT=true
make capacity-preflight
make lab-deploy-plan
make deploy-auto HELM_EXTRA_ARGS="-f reports/environment-profile-values.yaml -f reports/lab-deploy-values.yaml"
```

`deploy-auto` keeps lab storage compact, skips placeholder workloads, installs local-path storage when needed, and recovers common failed Helm release states. The lab deploy overlay keeps the first wave bounded when `capacity-preflight` warns about database or optional-component pressure.

The environment profile command also writes
`reports/environment-profile-evidence-bundle.md`, which lists the public reports
and private evidence categories expected for the selected lab, staging, or
production profile.

## Project Import Planning

Start with a read-only compatibility report:

```bash
make import-check PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true
```

Generate an operator action plan without cluster access:

```bash
make import-plan PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true
```

## Project Import Execution

Use one command for the normal lab import path after the plan looks correct:

```bash
make capacity-preflight
make import-auto PROJECT_PATH=/path/to/compose-project \
  IMPORT_REDACT=true \
  MIGRATION_ALLOW_SECRET_MATERIAL=true \
  MIGRATION_IMAGE_MODE=preload \
  MIGRATION_RKE2_NODES=node-01,node-02,node-03 \
  MIGRATION_SSH_USER=ansible
```

`import-auto` repairs or discovers operator kubeconfig, runs cluster preflight, batches oversized lab imports, preloads images when selected, applies guarded secret handling, runs database migration stages when target maps are configured, applies generated manifests, and writes public-safe validation reports.

## Import Recovery

After a failed or interrupted import, generate the public-safe recovery plan
before changing state or forcing stages to rerun:

```bash
make import-recovery-plan IMPORT_REDACT=true
```

The report explains which stateful scopes are already completed, whether the
next run can resume safely, which cleanup actions are operator-local only, and
which rollback actions require reviewing generated manifests or private backup
evidence. Use `MIGRATION_FORCE_RERUN=true` only after that plan says the rerun
is intentional.

## Production Cutover

Before switching production traffic, run the cutover gate plan:

```bash
make environment-profile-plan ENV_PROFILE=production IMPORT_REDACT=true
make smoke-test-plan SMOKE_TEST_PROFILE=production-smoke IMPORT_REDACT=true
make cutover-gate-plan CUTOVER_GATES_PROFILE=production-cutover IMPORT_REDACT=true
make release-runbook-plan RELEASE_RUNBOOK_PROFILE=production-release IMPORT_REDACT=true
```

The report combines import preflight, capacity, recovery, release evidence,
registry/preload, backup, database restore, DNS/TLS, smoke-test, rollback,
change approval, and post-cutover watch readiness. It does not modify DNS,
approve tickets, switch ingress routes, or run customer-facing smoke tests.
The release runbook step adds the final artifact, approval, rollback, smoke-test,
cutover, and evidence-bundle checklist without publishing or deploying.

## Release Evidence

When Helm is available locally:

```bash
make release-evidence RELEASE_TAG=v0.1.0
make verify-release-evidence RELEASE_TAG=v0.1.0
make release-runbook-plan RELEASE_RUNBOOK_PROFILE=production-release IMPORT_REDACT=true
```

The evidence set includes chart package, rendered manifest, SPDX SBOM, release evidence manifest, and SHA-256 checksums. The release runbook ties that public artifact evidence to private approval, rollback, smoke-test, cutover, and owner-review records.

## Cluster Upgrade Planning

Before changing RKE2 or Kubernetes versions:

```bash
make cluster-upgrade-plan CLUSTER_UPGRADE_PROFILE=production-upgrade IMPORT_REDACT=true
```

The plan checks version skew, target RKE2 pin format, etcd snapshot evidence,
backup/restore readiness, add-on compatibility, maintenance window, rollback,
and post-upgrade smoke-test readiness. It does not drain nodes, restart RKE2,
patch inventories, or mutate the cluster.
