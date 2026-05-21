# Progressive Delivery And Rollback

## Article 19 Baseline

Progressive delivery is optional and disabled by default. The default chart
continues to use normal Kubernetes Deployment rollouts plus Helm rollback. This
article adds public-safe planning for canary, blue-green, analysis gates, and
rollback ownership before teams enable Argo Rollouts, Flagger, service mesh
traffic shifting, or controller-specific private overlays.

The planner does not install rollout controllers, mutate clusters, create
traffic-splitting objects, read private metrics queries, or print customer
service names.

## Profiles

| Profile | Purpose | Controller | Strategy |
|---|---|---|---|
| `disabled` | Default Helm rollout path | none | rolling update |
| `lab-canary` | Small-batch lab rehearsal | native | canary intent |
| `production-canary` | Production canary readiness | Argo Rollouts | canary |
| `production-blue-green` | Production preview and promotion gate | Argo Rollouts | blue-green |

## One Command

```bash
make progressive-delivery-plan \
  PROGRESSIVE_DELIVERY_PROFILE=production-canary \
  IMPORT_REDACT=true
```

The command writes:

- `reports/progressive-delivery-plan.md`
- `reports/progressive-delivery-values.yaml`

## Production Readiness

Before enabling production progressive delivery:

- Run the GitOps delivery plan and assign a rollback owner.
- Promote images through private registry digest pins.
- Review runtime hardening and admission policies.
- Define SLO-backed promotion metrics and smoke tests.
- Complete a rollback drill before automatic rollback is trusted.
- Keep `autoPromotion=false` until the analysis gates are proven.

## Controller Notes

`native` mode is a planning profile only; it models small lab waves without
installing a rollout controller. Production canary and blue-green profiles
expect a private controller installation, such as Argo Rollouts or Flagger,
plus private metric analysis templates.

## Public-Safe Rules

- Do not commit private analysis queries, customer route names, or rollout
  experiments.
- Do not enable destructive automation without a rollback drill.
- Do not enable automatic promotion without production SLO coverage.
- Keep `progressiveDelivery.enabled=false` in committed defaults.
