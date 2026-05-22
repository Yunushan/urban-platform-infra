# Release Runbook And Evidence Gates

Article 11 adds a public-safe release runbook gate. It connects release
artifact evidence, change approval, rollback ownership, smoke tests, cutover
readiness, and environment evidence without publishing tags, deploying
workloads, approving tickets, or switching traffic.

## Plan Command

Generate the production release runbook plan:

```bash
make release-runbook-plan RELEASE_RUNBOOK_PROFILE=production-release IMPORT_REDACT=true
```

The command writes:

- `reports/release-runbook-plan.md`
- `reports/release-runbook-values.yaml`

Use `RELEASE_RUNBOOK_PROFILE=lab-release` for lab rehearsals and
`RELEASE_RUNBOOK_PROFILE=staging-release` before non-production promotion.

## Evidence Scope

The release runbook gate expects public-safe reports such as:

- release evidence verification
- environment profile evidence bundle
- change management plan
- smoke-test plan
- cutover gate plan
- disaster recovery plan

Private approval indexes, ticket URLs, approver names, attestation logs,
registry paths, DNS names, and customer-impact notes must stay in approved
private systems.

## Disabled By Default

The generated Helm overlay keeps `releaseRunbook.enabled` and
`releaseRunbook.execution.enabled` set to `false`. A private production overlay
can later choose a publisher or deployer integration after ownership, RBAC,
branch protection, release signing, and rollback expectations are approved.

## Recommended Sequence

```bash
make release-evidence RELEASE_TAG=v0.1.0
make verify-release-evidence RELEASE_TAG=v0.1.0
make environment-profile-plan ENV_PROFILE=production IMPORT_REDACT=true
make change-management-plan CHANGE_MANAGEMENT_PROFILE=production-cab IMPORT_REDACT=true
make smoke-test-plan SMOKE_TEST_PROFILE=production-smoke IMPORT_REDACT=true
make cutover-gate-plan CUTOVER_GATES_PROFILE=production-cutover IMPORT_REDACT=true
make release-runbook-plan RELEASE_RUNBOOK_PROFILE=production-release IMPORT_REDACT=true
```

The release runbook complements cutover gates. It does not approve production
deployment by itself.
