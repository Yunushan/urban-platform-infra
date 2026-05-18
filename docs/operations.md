# Operations

## Deploy

```bash
make validate
make install-operators
make deploy
```

The deployment target installs Helm and Helmfile when missing, applies the
templated operator Helmfile, waits for CNPG and ECK CRDs, then installs the
platform chart.

Before Helmfile, kubectl, or Helm touches the cluster, `make install-operators`
and `make deploy` run `scripts/tools/ensure-kubeconfig.sh`. That script fetches
the RKE2 kubeconfig from the first server, rewrites the API endpoint to the
configured VIP port, and writes it to `${KUBECONFIG}` or `~/.kube/config`. If
`${KUBECONFIG}` or `~/.kube/config` already exists and its Kubernetes API
`/readyz` endpoint responds, the script uses that kubeconfig as-is instead of
requiring an inventory just to install operator CRDs.

The default operator pins are intentionally current for this stack:
CloudNativePG 1.29+ is required for PostgreSQL 18 defaults, and ECK 3.4+ is
required for Kubernetes 1.34 and Elastic Stack 9.x.

The operator step uses `helmfile sync`, so the Helm diff plugin is not required
on the operator machine.

## Observe

```bash
make status
make observability-status
```

Install ECK, kube-prometheus-stack/Grafana, and OpenTelemetry Collector with `make install-operators`, then enable `monitoring.enabled=true` in a production override file when the Prometheus Operator CRDs are present.

Service objectives live in `config/slo.yaml`. Alert runbooks live in `docs/runbooks.md`.

## Upgrade Image Tags

Edit `helm/urban-platform-infra/values.yaml` or use dependency automation to propose changes. Production overrides should use private-registry digest pins after image promotion.

## Backup

Recommended before production:

- CloudNativePG scheduled backups to S3-compatible storage.
- Elasticsearch snapshots to S3-compatible storage.
- Kafka topic backup or MirrorMaker/replication strategy.
- Redis RDB/AOF persistence and backup.
- GitOps repository backup.

## Logs

Default pipeline: OpenTelemetry Collector -> Logstash -> Elasticsearch -> Kibana, with Prometheus/Grafana for metrics and dashboards. Optional pipelines are configured in `config/observability.yaml`.

## Monthly Review

- Review SLO error budget burn from `config/slo.yaml`.
- Review alert volume and remove noisy alerts.
- Review capacity pressure, restart trends, and storage growth.
- Confirm every alert has a current runbook.
- Confirm release evidence exists for deployed chart artifacts.

## Rollback

```bash
helm history urban-platform-infra -n urban-platform
helm rollback urban-platform-infra <REVISION> -n urban-platform
```
