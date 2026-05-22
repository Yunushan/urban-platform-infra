# Production Cutover And Smoke-Test Gates

Cutover gates are disabled by default. They provide a public-safe readiness
plan for the moment between a successful import/deploy rehearsal and an approved
traffic switch. The planner does not modify DNS, approve change tickets, run
customer-facing smoke tests, switch ingress routes, or delete rollback evidence.

```bash
make cutover-gate-plan CUTOVER_GATES_PROFILE=production-cutover IMPORT_REDACT=true
```

The command writes:

- `reports/cutover-gate-plan.md`
- `reports/cutover-gate-values.yaml`

The generated values file keeps `cutoverGates.enabled=false`; it is an explicit
intent overlay for review, not an automation trigger.

## Gate Inputs

The production profile checks for:

- import preflight and capacity reports
- import recovery plan and post-migration check artifacts
- release evidence verification
- registry promotion or image preload evidence
- backup/restore and database restore validation evidence
- DNS/TLS evidence and ingress host ownership
- smoke-test plan, synthetic checks, rollback plan, and restore point evidence
- change ticket, approval evidence, observation window, and owner handoff

Private URLs, tickets, approver names, DNS names, registry paths, database
connection strings, and smoke-test endpoints must stay in approved private
systems. When `IMPORT_REDACT=true`, the public report uses placeholders for
private evidence paths.

## Recommended Sequence

```bash
make import-preflight PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true
make import-recovery-plan IMPORT_REDACT=true
make release-evidence RELEASE_TAG=v0.1.0
make verify-release-evidence RELEASE_TAG=v0.1.0
make registry-promotion-plan REGISTRY_PROMOTION_PROFILE=production IMPORT_REDACT=true
make database-migration-plan DB_MIGRATION_PROFILE=production IMPORT_REDACT=true
make change-management-plan CHANGE_MANAGEMENT_PROFILE=production-cab IMPORT_REDACT=true
make smoke-test-plan SMOKE_TEST_PROFILE=production-smoke IMPORT_REDACT=true
make cutover-gate-plan CUTOVER_GATES_PROFILE=production-cutover IMPORT_REDACT=true
```

## Production Rule

Treat `PASS` as "the public-safe checklist is complete", not as permission to
switch traffic. The actual cutover still needs the private approval path,
maintenance window, smoke-test owner, rollback owner, and post-cutover watch.
