# Import Resume, Recovery, And Cleanup

This document is public-safe. It describes how to recover a failed or interrupted
project import without exposing project paths, service names, node names, image
names, database connection strings, registry credentials, or secret values.

## Recovery Plan

After any failed or interrupted import, generate the recovery plan before
changing state:

```bash
make import-recovery-plan IMPORT_REDACT=true
```

The plan writes `reports/import-migration/import-recovery-plan.md`. It reads
the private `MIGRATION_STATE_FILE`, summarizes which stateful scopes completed,
checks expected public artifacts, and explains whether the next retry should
resume, force rerun, or use a separate rehearsal state file.

## Safe Retry

The first recovery action should normally be the same `make import-auto ...`
command that failed. With `MIGRATION_RESUME=true`, completed service-secret,
image, database, and manifest scopes are skipped when their scope still matches.
Preflight and validation continue to run on every retry because cluster health
can change between runs.

Use `MIGRATION_FORCE_RERUN=true` when a completed scope intentionally needs to
run again, such as rebuilding images after a source change or reapplying
manifests after reviewing generated YAML. Use
`MIGRATION_STATE_FILE=/path/to/private/rehearsal-state.yaml` when a lab
rehearsal should not share resume history with another run.

## Cleanup Boundaries

Operator-side imported image tags, local preload archives, and dangling build
cache can be cleaned by the image stage when
`MIGRATION_CLEANUP_OPERATOR_IMAGES=true` and
`MIGRATION_PRUNE_OPERATOR_CACHE=true`.

Node-side RKE2/containerd images, private database dumps, private target maps,
and the private state file are not deleted automatically. They are recovery
evidence or runtime dependencies. Archive or expire them through the selected
backup and retention process instead of deleting them during retry.

## Rollback Boundaries

Generated import manifests are separate from the Helm release. Imported
workloads, Traefik route candidates, direct Kubernetes Secrets, and database
restore targets should be rolled back only after reviewing the generated files
and the private action plan.

Database dump/restore is not automatically reversed. Use a known backup,
snapshot, or reviewed target restore process. Helm rollback remains the
break-glass path for chart-managed platform resources, not for every generated
import artifact.
