# Change Management And Maintenance Windows

## Article 25 Baseline

Change management support is optional architecture and disabled by default. The
baseline gives operators a public-safe way to plan change records, approvals,
risk and impact assessment, maintenance windows, freeze checks, rollback,
smoke tests, post-change review, and evidence handoff before production change
automation is enabled.

The planner does not open tickets, approve changes, update calendars, notify
stakeholders, or store approver names.

## Profiles

`config/change-management.yaml` defines:

| Profile | Purpose | Runtime Change |
|---|---|---|
| `disabled` | Keep committed chart defaults | None |
| `lab-change` | Review repeatable lab deploy, smoke-test, and rollback behavior | None |
| `staging-approval` | Rehearse tickets, approval, impact, window, and review evidence | None |
| `production-cab` | Prepare production CAB, freeze, stakeholder, rollout, and review gates | None |
| `regulated-change` | Plan regulated approvals and external evidence ownership | None |

## Planner

```bash
make change-management-plan \
  CHANGE_MANAGEMENT_PROFILE=production-cab \
  CHANGE_MANAGEMENT_FREEZE_CHECK=true \
  CHANGE_MANAGEMENT_STAKEHOLDER_NOTICE=true \
  CHANGE_MANAGEMENT_POST_CHANGE_REVIEW=true \
  IMPORT_REDACT=true
```

The planner writes:

- `reports/change-management-plan.md`
- `reports/change-management-values.yaml`

The generated values overlay keeps `changeManagement.enabled=false`. It records
readiness intent for private overlays instead of mutating a ticketing system or
publishing maintenance windows.

## Guardrails

- Do not commit ticket URLs, approver names, calendar entries, maintenance
  windows, customer impact notes, or private change records.
- Keep production CAB and regulated approval workflows in approved private
  change-management systems.
- Production rollout should not proceed until rollback, smoke-test, freeze,
  stakeholder, and post-change-review evidence is reviewed.
- Link private change evidence into the compliance evidence plan after redaction
  and export approval.
