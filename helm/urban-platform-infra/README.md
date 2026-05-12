# urban-platform-infra Helm chart

This chart renders the default HA application stack for `urban-platform-infra`.

## Common changes

```bash
# Render only
helm template urban-platform-infra . -n urban-platform -f values.yaml

# Install/upgrade
kubectl create namespace urban-platform --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install urban-platform-infra . -n urban-platform --cleanup-on-fail --set namespace.create=false -f values.yaml
```

Switches are handled in `values.yaml`:

- `global.cluster.engine`: `rke2`, `k3s`, `microk8s`, `docker`, `raw`
- `webserver.provider`: `nginx`, `apache-httpd`, `apache-tomcat`, `traefik`
- `databases.provider`: `cloudnative-pg` by default; use catalog profiles for alternatives
- `observability.profile`: `elasticsearch`, `loki`, `opensearch`, `graylog`, `clickhouse`
- Default observability stack: Elastic ECK + Prometheus/Grafana + OpenTelemetry Collector
- `ingress.tls.enabled`: enabled by default with HTTP to HTTPS redirect. Provide `ingress.tls.secretName` with a real certificate for production.

CloudNativePG and ECK CRs require operators. Install them with `make install-operators`.
The default pins expect CloudNativePG 1.29+ and ECK 3.4+ for PostgreSQL 18 and Elastic Stack 9.x support.
The chart renders a labeled Namespace by default for GitOps/policy checks; imperative `helm upgrade --install` paths should pre-create the namespace and set `namespace.create=false`.
