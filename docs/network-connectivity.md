# Network Connectivity And Service Mesh

## Article 21 Baseline

Network connectivity support is optional architecture and disabled by default.
The baseline keeps the chart's existing NetworkPolicy rules, then uses a
public-safe planner to review ingress class ownership, DNS, TLS, Kubernetes API
egress, external egress, and service mesh readiness before stricter controls
are enabled.

Use this gate before removing broad lab egress, enabling strict production
egress, or adopting Linkerd/Istio.

## Profiles

`config/network-connectivity.yaml` defines:

| Profile | Purpose | Runtime Change |
|---|---|---|
| `disabled` | Keep existing NetworkPolicy defaults | None |
| `lab-baseline` | Review lab connectivity without blocking imports | None |
| `production-restricted` | Prepare restricted NetworkPolicy and explicit egress contracts | None |
| `mesh-linkerd` | Plan lightweight mTLS/telemetry with Linkerd | None |
| `mesh-istio` | Plan enterprise mesh policy with Istio | None |

## Planner

```bash
make network-connectivity-plan \
  NETWORK_CONNECTIVITY_PROFILE=production-restricted \
  NETWORK_CONNECTIVITY_DNS_TLS_EVIDENCE=true \
  IMPORT_REDACT=true
```

The planner writes:

- `reports/network-connectivity-plan.md`
- `reports/network-connectivity-values.yaml`

The generated values overlay keeps `networkConnectivity.enabled=false`. It is
an intent document for review, not an automatic mesh install or NetworkPolicy
mutation.

## Service Mesh Guardrails

- Start with default NetworkPolicy and explicit health probe checks.
- Keep mTLS permissive until operators, database migrations, ingress routes,
  and rollback paths are verified.
- Keep mesh providers disabled in committed defaults.
- Linkerd is the lighter first candidate for small clusters.
- Istio needs stronger capacity, ownership, and rollout discipline.

## Egress Guardrails

- Lab profiles can keep shared web egress while dependencies are still being
  discovered.
- Production profiles should move toward explicit CIDRs, private egress
  gateways, or reviewed FQDN policy.
- Public reports must not print node names, VIPs, private hostnames, internal
  service names, or CIDR inventories.
