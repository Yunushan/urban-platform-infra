# urban-platform-infra Helm chart

This chart renders the default HA application stack for `urban-platform-infra`.

## Common changes

```bash
# Render only
helm template urban-platform-infra . -n urban-platform -f values.yaml

# Install/upgrade
kubectl get namespace urban-platform >/dev/null 2>&1 || kubectl create namespace urban-platform
helm upgrade --install urban-platform-infra . -n urban-platform --cleanup-on-fail --set namespace.create=false -f values.yaml
```

Switches are handled in `values.yaml`:

- `global.cluster.engine`: `rke2`, `k3s`, `microk8s`, `docker`, `raw`
- `ingress.className`: `traefik` by default, set `nginx` for ingress-nginx. RKE2 controls the bundled Traefik version unless inventory opts into an upstream chart pin.
- `webserver.provider`: `nginx`, `apache-httpd`, `apache-tomcat`, `traefik`
- `databases.provider`: `cloudnative-pg` by default; use catalog profiles for alternatives
- `observability.profile`: `disabled`, `elasticsearch`, `loki`, `opensearch`, `graylog`, `clickhouse`, `grafana`
- Default observability stack: disabled for 4-core/4 GiB lab nodes. Enable components with values or deploy env flags such as `DEPLOY_ENABLE_PROMETHEUS=true DEPLOY_ENABLE_GRAFANA=true`, `DEPLOY_ENABLE_ELASTICSEARCH=true DEPLOY_ENABLE_KIBANA=true DEPLOY_ENABLE_LOGSTASH=true`, `DEPLOY_ENABLE_LOKI=true`, and `DEPLOY_ENABLE_CLICKHOUSE=true`.
- `ingress.tls.enabled`: enabled by default with HTTP to HTTPS redirect. The chart renders cert-manager `Issuer` and `Certificate` resources by default, so cert-manager creates `ingress.tls.secretName` without the chart rendering a plain Kubernetes Secret. For production, set `ingress.tls.selfSigned.enabled=false` and provide `ingress.tls.certManager.issuerName`, set `ingress.tls.createSecret=false` and point `ingress.tls.secretName` at an existing TLS secret, or enable the `secretManagement.externalSecrets.ingressTls` mapping.
- `secretManagement.providerAdapters`: disabled-by-default adapter contracts for direct Kubernetes Secret import, External Secrets Operator, Vault-backed External Secrets, SOPS, and Sealed Secrets. External Secrets is the only chart-rendered runtime sync path; SOPS and Sealed Secrets are encrypted-Git handoff modes.
- `imagePromotionController`: disabled-by-default production registry promotion intent. Use `make registry-promotion-plan` to generate the report and public-safe override template before setting private `global.imageRegistry`, `global.imagePullSecrets`, and digest-pinned production images.
- `runtimeHardening`: disabled-by-default admission readiness intent. Use `make runtime-hardening-plan` before moving from lab audit mode to restricted Pod Security, read-only root filesystems, digest-only images, or signed-image admission.
- `gitOpsDelivery`: disabled-by-default delivery and drift-control intent. Use `make gitops-delivery-plan` before enabling Argo CD or Flux automation, and keep private repository URLs, deploy keys, and environment overlays out of public values.
- `progressiveDelivery`: disabled-by-default rollout strategy intent. Use `make progressive-delivery-plan` before enabling canary, blue-green, Argo Rollouts, Flagger, SLO analysis, or automatic rollback behavior.
- `scalingPolicy`: disabled-by-default autoscaling and right-sizing intent. Use `make scaling-policy-plan` before enabling HPA, VPA, KEDA, or cluster-autoscaler automation.
- `networkConnectivity`: disabled-by-default network and mesh intent. Use `make network-connectivity-plan` before tightening egress, changing DNS/TLS contracts, or enabling Linkerd/Istio.
- `accessGovernance`: disabled-by-default access and tenant isolation intent. Use `make access-governance-plan` before enabling OIDC/SSO, new RBAC overlays, tenant namespaces, or break-glass procedures.
- `complianceEvidence`: disabled-by-default evidence and audit-pack intent. Use `make compliance-evidence-plan` before collecting private evidence, mapping controls, packaging audit artifacts, or enabling retention automation.
- `incidentResponse`: disabled-by-default incident response intent. Use `make incident-response-plan` before enabling paging, alert-routing, communication, runbook, drill, or post-incident review integrations.
- `changeManagement`: disabled-by-default change management and maintenance-window intent. Use `make change-management-plan` before enabling ticket, approval, freeze-check, rollback, smoke-test, deployment-evidence, or post-change review integrations.
- `disasterRecovery`: disabled-by-default disaster recovery and business continuity intent. Use `make disaster-recovery-plan` before enabling recovery-site, replication, restore-drill, failover, DNS cutover, continuity, or post-drill review integrations.
- `ingress.host`: optional canonical host. When it is empty, the chart uses `global.cluster.domain` for HTTPS routes and the self-signed certificate.

## Root application route

The default public route is intended for the imported gateway workload, `workloads.app-27`, at `/`. The default image is a placeholder and is skipped when `DEPLOY_SKIP_PLACEHOLDER_WORKLOADS=true`, so the root HTTPS route returns Traefik `404` until a real image is supplied.

`PROJECT_PATH` intentionally has no committed default. Set it from a private shell environment, ignored local env file, or CI secret-backed variable. The import tooling searches that tree recursively for `compose.yaml`, `compose.yml`, `docker-compose.yaml`, `docker-compose.yml`, and compose-named YAML files.

For operator-driven deploys, pass the real login/frontend image through the deploy environment:

```bash
DEPLOY_ROOT_WORKLOAD=app-27 \
DEPLOY_ROOT_IMAGE_REPOSITORY="$APP_IMAGE_REPOSITORY" \
DEPLOY_ROOT_IMAGE_TAG="$APP_IMAGE_TAG" \
DEPLOY_ROOT_CONTAINER_PORT=5000 \
DEPLOY_ROOT_SERVICE_PORT=5000 \
DEPLOY_ROOT_PROBE_PORT=5000 \
DEPLOY_INGRESS_HOST="$DEPLOY_INGRESS_HOST" \
DEPLOY_TLS_SECRET_NAME="$DEPLOY_TLS_SECRET_NAME" \
make deploy
```

Traefik owns public `443` and terminates the self-signed certificate. The backend application only needs to listen on its container/service port, such as `5000`; it should not bind host port `443` inside Kubernetes.

## Default Access Ports

When observability is enabled, the deploy path exposes services on stable NodePorts and can configure HAProxy on the VIP to forward friendly ports:

| Service | VIP port | Internal NodePort |
| --- | ---: | ---: |
| Grafana | 3000 | 30300 |
| Loki gateway | 3100 | 30310 |
| Kibana | 5601 | 30561 |
| ClickHouse HTTP | 8123 | 30812 |
| ClickHouse native TCP | 9000 | 30900 |
| Elasticsearch HTTPS | 9200 | 30920 |

Set `DEPLOY_EDGE_OBSERVABILITY_PORTS=true` with `DEPLOY_CONFIGURE_EDGE_PORTS=true` to have `make deploy` update HAProxy/Keepalived for those VIP ports. Use a private space-separated CIDR allowlist to restrict public routes and edge ports:

```bash
DEPLOY_ALLOWED_CIDRS="$DEPLOY_ALLOWED_CIDRS" make deploy
```

The allowlist is applied to Traefik Ingress routes on `80`/`443` and to HAProxy-managed observability ports. Keep node firewalls closed for the raw NodePort range if direct node-IP access should not be allowed.

Do not commit real hosts, VIPs, node addresses, registry credentials, kubeconfigs, passwords, TLS keys, or company/customer identifiers. Keep those values in ignored local env files, private inventories, vault-backed config, External Secrets, or CI secret variables.

CloudNativePG and ECK CRs require operators. Install them with `make install-operators`.
The default pins expect CloudNativePG 1.29+ and ECK 3.4+ for PostgreSQL 18 and optional Elastic Stack 9.x support.
The chart renders a labeled Namespace plus default `LimitRange` and `ResourceQuota` guardrails by default for GitOps/policy checks; imperative `helm upgrade --install` paths should pre-create the namespace and set `namespace.create=false`.
