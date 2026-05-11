# Operations

## Deploy

```bash
make validate
make install-operators
make deploy
```

## Observe

```bash
make status
make observability-status
```

Install kube-prometheus-stack with `make install-operators`, then enable `monitoring.enabled=true` in a production override file when the Prometheus Operator CRDs are present.

Service objectives live in `config/slo.yaml`. Alert runbooks live in `docs/runbooks.md`.

## Upgrade Image Tags

Edit `helm/city-intersection-platform/values.yaml` or use dependency automation to propose changes. Production overrides should use private-registry digest pins after image promotion.

## Backup

Recommended before production:

- CloudNativePG scheduled backups to S3-compatible storage.
- Elasticsearch snapshots to S3-compatible storage.
- Kafka topic backup or MirrorMaker/replication strategy.
- Redis RDB/AOF persistence and backup.
- GitOps repository backup.

## Logs

Default pipeline: Logstash -> Elasticsearch -> Kibana. Optional pipelines are configured in `config/observability.yaml`.

## Monthly Review

- Review SLO error budget burn from `config/slo.yaml`.
- Review alert volume and remove noisy alerts.
- Review capacity pressure, restart trends, and storage growth.
- Confirm every alert has a current runbook.
- Confirm release evidence exists for deployed chart artifacts.

## Rollback

```bash
helm history city-intersection-project -n city-intersection
helm rollback city-intersection-project <REVISION> -n city-intersection
```
