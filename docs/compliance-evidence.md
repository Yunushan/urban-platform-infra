# Compliance Evidence And Audit Pack

## Article 23 Baseline

Compliance evidence support is optional architecture and disabled by default.
The baseline gives operators a public-safe way to plan evidence collection,
control mapping, audit-pack packaging, retention, and redacted report sharing
without committing private artifacts to Git.

The planner does not collect logs, archive reports, upload evidence, create
retention buckets, or claim SOC, ISO, PCI, HIPAA, or regulatory certification.

## Profiles

`config/compliance-evidence.yaml` defines:

| Profile | Purpose | Runtime Change |
|---|---|---|
| `disabled` | Keep committed chart defaults | None |
| `lab-evidence` | Summarize lab import and validation evidence | None |
| `staging-control-review` | Map staging controls and readiness evidence | None |
| `production-audit-pack` | Prepare production release, restore, access, and incident evidence | None |
| `regulated-retention` | Plan extended retention with external compliance ownership | None |

## Planner

```bash
make compliance-evidence-plan \
  COMPLIANCE_EVIDENCE_PROFILE=production-audit-pack \
  COMPLIANCE_EVIDENCE_RESTORE_DRILL=true \
  COMPLIANCE_EVIDENCE_ACCESS_REVIEW=true \
  COMPLIANCE_EVIDENCE_INCIDENT_DRILL=true \
  IMPORT_REDACT=true
```

The planner writes:

- `reports/compliance-evidence-plan.md`
- `reports/compliance-evidence-values.yaml`

The generated values overlay keeps `complianceEvidence.enabled=false`. It
records evidence readiness intent for private overlays instead of exporting
private evidence from public configuration.

Use the output as an audit pack readiness summary; full audit pack artifacts
must stay in approved private storage.

## Evidence Scope

The default evidence source list covers:

- import check, import preflight, capacity, resume, and batch reports
- image cache and registry promotion plans
- database and edge migration plans
- backup and restore readiness
- runtime hardening, network connectivity, access governance, and scaling plans
- GitOps, progressive delivery, and release evidence verification

## Guardrails

- Do not commit private evidence archives, full reports, user names, tenant
  names, node addresses, registry names, customer identifiers, or private paths.
- Store private evidence indexes under the trusted operator directory or in an
  approved object store.
- Keep evidence packaging and retention automation disabled until legal,
  platform, and security owners approve the target.
- Treat generated reports as readiness evidence, not certification.
