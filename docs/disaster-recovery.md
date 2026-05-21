# Disaster Recovery And Business Continuity

## Article 26 Baseline

Disaster recovery and business continuity support is optional and disabled by
default. The goal is to let operators plan recovery objectives, dependency
mapping, backup replication, restore drills, failover runbooks, communication
paths, manual workarounds, supplier ownership, and post-drill review without
publishing private recovery details.

## Profiles

| Profile | Purpose | Default automation |
|---|---|---|
| `disabled` | Baseline with no DR/BCP automation | None |
| `lab-dr` | Selected-workload restore rehearsal in constrained labs | None |
| `staging-rehearsal` | Non-production restore and failover runbook rehearsal | None |
| `production-dr` | Production DR readiness for critical services | None |
| `regulated-bcp` | Regulated continuity profile with evidence gates | None |

## Planner

Generate a public-safe plan:

```bash
make disaster-recovery-plan \
  DISASTER_RECOVERY_PROFILE=production-dr \
  DISASTER_RECOVERY_POST_DRILL_REVIEW=true \
  IMPORT_REDACT=true
```

The command writes:

- `reports/disaster-recovery-plan.md`
- `reports/disaster-recovery-values.yaml`

The generated values overlay keeps `disasterRecovery.enabled=false`. It records
the selected DR/BCP intent so private overlays can later wire real recovery
sites, object stores, DNS cutover, replication, and continuity systems.

## Public Safety

Public reports must not include real recovery site names, DNS names, node
addresses, supplier contacts, backup bucket names, outage timelines, customer
impact notes, or private restore evidence.

Keep these in private systems:

- RTO/RPO approvals
- dependency and criticality maps
- backup replication evidence
- RKE2 etcd, database, and namespace restore logs
- failover runbooks and DNS cutover records
- supplier and customer communication lists
- post-drill review evidence

## Promotion Guidance

- Use `lab-dr` to prove a small selected restore path.
- Use `staging-rehearsal` to prove namespace restore, RKE2 etcd restore, and
  application smoke tests.
- Use `production-dr` only after backup plans, change management, incident
  response, and compliance evidence records are reviewed.
- Use `regulated-bcp` when recovery evidence must feed an audit pack or formal
  continuity review.

Disaster recovery readiness should be proven with restore drills before any
production continuity claim is made.
