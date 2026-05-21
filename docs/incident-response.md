# Incident Response And Operational Readiness

## Article 24 Baseline

Incident response support is optional architecture and disabled by default. The
baseline gives operators a public-safe way to plan alert routes, escalation,
runbooks, communications, drills, rollback ownership, post-incident review, and
evidence handoff before production on-call automation is enabled.

The planner does not page anyone, create tickets, open incidents, configure
Alertmanager, update a pager service, or store contact rosters.

## Profiles

`config/incident-response.yaml` defines:

| Profile | Purpose | Runtime Change |
|---|---|---|
| `disabled` | Keep committed chart defaults | None |
| `lab-readiness` | Review lab alerts, runbooks, and rollback ownership | None |
| `staging-drill` | Rehearse incident drills, runbooks, escalation, and PIR | None |
| `production-oncall` | Prepare production alerting, paging, comms, and evidence | None |
| `regulated-incident` | Plan external reporting and regulated incident ownership | None |

## Planner

```bash
make incident-response-plan \
  INCIDENT_RESPONSE_PROFILE=production-oncall \
  INCIDENT_RESPONSE_INCIDENT_DRILL=true \
  INCIDENT_RESPONSE_POST_INCIDENT_REVIEW=true \
  IMPORT_REDACT=true
```

The planner writes:

- `reports/incident-response-plan.md`
- `reports/incident-response-values.yaml`

The generated values overlay keeps `incidentResponse.enabled=false`. It records
readiness intent for private overlays instead of notifying people or creating
runtime incident-management resources.

## Guardrails

- Do not commit contact names, phone numbers, email addresses, pager service
  IDs, ticket URLs, stakeholder maps, or incident timelines.
- Keep alert routes, escalation rosters, and communication templates in approved
  private systems.
- Production paging should not be enabled until alert ownership, quiet hours,
  rollback paths, and post-incident review ownership are proven.
- Link private incident drill evidence into the compliance evidence plan only
  after redaction and export approval.
