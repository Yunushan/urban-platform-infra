# Helm Chart Hardening

This project treats the Helm chart as the production contract for the infrastructure deployment. Values should be explicit, schema-validated, and safe to render before they reach a cluster.

## Defaults

- Services default to `ClusterIP`; expose workloads through ingress or an intentionally configured load balancer.
- Pods use a dedicated service account by default with `automountServiceAccountToken: false`.
- Application workloads inherit global image pull policy, image pull secrets, topology spread constraints, pod security context, and container security context.
- Container security drops Linux capabilities by default for application workloads.
- The chart keeps third-party webserver container security context opt-in per provider because public upstream images may require image-specific runtime settings.

## Enterprise Controls

- `global.serviceAccount` controls service account creation, name, and token automount behavior.
- `global.imagePullPolicy` gives one place to enforce pull behavior across application workloads and webserver providers.
- Image definitions can use either `tag` or `digest`; digest values render as `repository@digest` for immutable deployments.
- `global.podSecurityContext` enables pod-level runtime defaults such as seccomp and `fsGroupChangePolicy`.
- `global.security` controls container-level settings for application workloads.
- `global.scheduling.topologySpread` enables zone and node spreading for replicated workloads.
- `webserver.service` controls service type, annotations, and load balancer source ranges.
- Per-workload `service.annotations` and `service.loadBalancerSourceRanges` support controlled cloud-provider integration when a workload must be directly exposed.

## Recommended Next Steps

1. Add production override files with private-registry digest pins after image promotion.
2. Add provider-specific webserver security contexts after validating each image can run non-root.
3. Add chart unit tests for service exposure, service account token behavior, and topology spread rendering.
4. Promote `namespace.podSecurity.enforce` from `baseline` to `restricted` after image runtime compatibility is verified.
