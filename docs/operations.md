# Operations

## Deploy

```bash
make validate
make install-operators
make deploy
```

The deployment target installs Helm and Helmfile when missing, applies the
templated operator Helmfile, waits for CNPG and ECK CRDs, then installs the
platform chart. The low-resource lab profile keeps Elasticsearch, Kibana,
Grafana, Loki, ClickHouse, Logstash, Prometheus, and OpenTelemetry disabled
unless their deploy flags are explicitly enabled.

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
The chart does not render CloudNativePG's deprecated
`spec.monitoring.enablePodMonitor` field by default. Create PodMonitor resources
explicitly when database scraping is required.
For lab clusters or small disks, override all CloudNativePG PVCs with
`databases.storageOverride.size` and, when the cluster does not have a default
StorageClass, `databases.storageOverride.className`.
`make install-operators` checks for a StorageClass before installing stateful
workloads. When no StorageClass exists, `INSTALL_LOCAL_PATH_STORAGE=auto`
installs Rancher local-path provisioner as a default lab StorageClass. Set
`INSTALL_LOCAL_PATH_STORAGE=false` when production storage is managed separately.
When the `local-path` StorageClass already exists, `deploy-auto` still
reconciles the provisioner and prepares `LOCAL_PATH_STORAGE_PATH`
(`/opt/local-path-provisioner` by default) on the RKE2 nodes over SSH. This
sets writable permissions and a container-compatible SELinux label so helper
pods do not fail with `mkdir: Permission denied`.

For an import/lab deployment, use the automatic recovery path instead of
manually uninstalling stuck releases or deleting Pending PVCs:

```bash
make deploy-auto \
  OPERATOR_KUBECONFIG="$OPERATOR_KUBECONFIG" \
  KUBECONFIG="$KUBECONFIG" \
  DEPLOY_INGRESS_HOST="$DEPLOY_INGRESS_HOST" \
  DEPLOY_CLUSTER_VIP="$DEPLOY_CLUSTER_VIP"
```

`deploy-auto` installs local-path storage when needed, recovers a failed or
`uninstalling` `urban-platform-infra` Helm release, removes stale resources from
that release, recreates the lab Kafka/ZooKeeper/Redis StatefulSets when their
storage template must change, and deletes only Pending PVCs by default, even
when the previous Helm release is already `deployed`. It uses one lab replica
and compact local-path storage sizes and classes for PostgreSQL, Kafka,
ZooKeeper, Redis, and any explicitly enabled observability backend. Bound PVCs are preserved unless
`DEPLOY_RECOVER_DELETE_PVCS=true` is set explicitly. It also disables Redis
Sentinel for the one-replica lab profile and skips sanitized placeholder
workloads whose images are still `example-app-*`, avoiding wasted memory and
repeated image pulls until real application images are imported or configured.
If the API is reachable but `/readyz` reports embedded-etcd readiness failures,
operator kubeconfig repair runs in `auto` mode when migration node addresses are
available. `deploy-auto` and `import-auto` still force that guarded RKE2 repair
pass explicitly.
If the VIP kubeconfig times out after `import-auto`, the kubeconfig helper reuses
the temporary migration inventory and falls back to an SSH tunnel to the RKE2 API.
When the SSH user needs sudo for RKE2 token or kubeconfig discovery,
`deploy-auto` prompts once on the terminal and reuses that password only for the
current run. Set `MIGRATION_BECOME_PASSWORD_PROMPT=false` for non-interactive
runs that must fail instead of prompting.
If one migration node is temporarily SSH-unreachable during automatic RKE2
repair, the generated recovery inventory excludes that node and reconciles the
reachable servers first. A three-node HA repair requires at least two
SSH-reachable servers by default to preserve embedded-etcd quorum. Set
`MIGRATION_SKIP_UNREACHABLE_RKE2_NODES=false` to make an unreachable node fail
the repair immediately, or override
`MIGRATION_REPAIR_MIN_REACHABLE_RKE2_NODES` only for an intentional lab
recovery.
If `/tmp/urban-platform-import-inventory.yml` is not present, pass
`MIGRATION_RKE2_NODES=node-1,node-2,node-3` once so the helper can rebuild that
inventory.
Operator Helmfile sync is retried automatically when the Kubernetes API returns
transient VIP TLS handshake timeouts; each retry refreshes the operator
kubeconfig first. When migration node addresses are available, the operator
kubeconfig prefers direct RKE2 node API endpoints before falling back to the VIP.
Before every Helmfile attempt, the wrapper waits for consecutive successful
`/readyz`, `/version`, and `/openapi/v2` probes so large charts do not start
while the API server is still brownout-prone.
If a previous Helm attempt leaves an operator release in a `pending-*` state, the
wrapper waits for it to finish, rolls it back to the last deployed revision when
needed, and removes a stale pending Helm secret only as a final recovery step.

The operator step uses `helmfile sync`, so the Helm diff plugin is not required
on the operator machine.

## Observe

```bash
make status
make observability-status
```

`make install-operators` installs the required operators and only installs optional observability charts when their flags are enabled. For the 4-core/4 GiB lab profile, those observability services are off by default. Re-enable only what you need, for example with `DEPLOY_ENABLE_PROMETHEUS=true DEPLOY_ENABLE_GRAFANA=true` for metrics dashboards or `DEPLOY_ENABLE_ELASTICSEARCH=true DEPLOY_ENABLE_KIBANA=true DEPLOY_ENABLE_LOGSTASH=true` for Elastic, then enable `monitoring.enabled=true` in a production override file when the Prometheus Operator CRDs are present.

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

Default lab pipeline: application logs go to stdout/stderr and heavy observability backends are disabled. Production pipelines such as OpenTelemetry Collector -> Logstash -> Elasticsearch -> Kibana, or Prometheus/Grafana for metrics and dashboards, are configured in `config/observability.yaml` and enabled through deploy flags or values overrides.

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
