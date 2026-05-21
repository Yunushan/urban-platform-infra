# Scaling Policy And Capacity Automation

## Article 20 Baseline

Scaling policy support is optional architecture and disabled by default. The
committed chart keeps fixed replicas, lab capacity gates, and manual capacity
review as the baseline. Use the scaling policy planner to decide when HPA, VPA,
KEDA, or cluster autoscaler ownership is ready.

The planner is public-safe. It does not install autoscaling controllers, mutate
workloads, read private metrics, create KEDA triggers, or print node names,
queue names, tenant names, or customer service names.

## Profiles

`config/scaling-policy.yaml` defines:

| Profile | Purpose | Runtime effect by default |
|---|---|---|
| `disabled` | Committed default | No autoscaling automation |
| `lab-rightsize` | Capacity and request review for small labs | Report-only |
| `production-hpa` | HPA readiness with metrics, SLO, load-test, and capacity evidence | Report-only |
| `event-driven-keda` | Queue, stream, or schedule based scaling readiness | Report-only |
| `enterprise-autoscaling` | HPA plus VPA recommendation mode and externally owned cluster autoscaler | Report-only |

## One Command

```bash
make scaling-policy-plan \
  SCALING_POLICY_PROFILE=production-hpa \
  SCALING_POLICY_METRICS_SOURCE=prometheus-adapter \
  SCALING_POLICY_LOAD_TEST_EVIDENCE=true \
  IMPORT_REDACT=true
```

The command writes:

- `reports/scaling-policy-plan.md`
- `reports/scaling-policy-values.yaml`

Generated values keep `scalingPolicy.enabled=false` and
`autoscaling.enabled=false` so operators can review intent before enabling any
runtime behavior.

## Recommended Sequence

1. Run `make lab-deploy-plan` and review CPU, memory, pod, and database counts.
2. Keep fixed replicas for the first lab or import deployment.
3. Install and verify metrics-server or Prometheus Adapter before HPA.
4. Enable HPA for one low-risk stateless workload before broad rollout.
5. Add KEDA only after private trigger metadata and secret references are ready.
6. Keep VPA in `Off` or `Initial` mode until HPA interaction is reviewed.
7. Treat cluster autoscaler as an infrastructure-owned component, not a public
   chart default.

## Production Guardrails

- Capacity report reviewed.
- Workload requests and limits reviewed.
- Metrics pipeline installed and queried.
- SLO burn-rate or saturation alerts reviewed.
- Load-test or replay evidence reviewed.
- Rollback and progressive delivery gates reviewed.

Keep `scalingPolicy.enabled=false` in committed defaults. Enable runtime scaling
only through private environment overlays after the above gates pass.
