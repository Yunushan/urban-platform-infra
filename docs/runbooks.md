# Runbooks

These runbooks are safe for the public repository. Keep private IPs, internal hostnames, credentials, customer details, and disclosure-sensitive system names out of this file.

## Deployment Replicas Unavailable

Alert: `CityIntersectionDeploymentReplicasUnavailable`

1. Check the deployment and events:

```bash
kubectl -n urban-platform get deploy,po
kubectl -n urban-platform describe deploy <deployment>
kubectl -n urban-platform get events --sort-by=.lastTimestamp
```

2. Check image pulls, scheduling, probes, and resource pressure.
3. Roll back if the issue follows a recent deployment:

```bash
helm history urban-platform-infra -n urban-platform
helm rollback urban-platform-infra <REVISION> -n urban-platform
```

## StatefulSet Replicas Unavailable

Alert: `CityIntersectionStatefulSetReplicasUnavailable`

1. Identify the affected dependency:

```bash
kubectl -n urban-platform get sts,po,pvc
kubectl -n urban-platform describe sts <statefulset>
```

2. Check PVC binding, node pressure, anti-affinity placement, and recent restarts.
3. Avoid deleting multiple stateful pods at once. Restore quorum first, then repair replicas one at a time.

## Container Restarts

Alert: `CityIntersectionContainerRestartingTooOften`

1. Inspect the restart reason:

```bash
kubectl -n urban-platform describe pod <pod>
kubectl -n urban-platform logs <pod> --previous
```

2. Check memory limits, startup time, dependency connection errors, and probe thresholds.
3. If restarts started after a release, compare values and image tags with the previous Helm revision.

## HPA Saturated

Alert: `CityIntersectionHPASaturated`

1. Check HPA and pod resource usage:

```bash
kubectl -n urban-platform get hpa
kubectl -n urban-platform top pods
```

2. Increase capacity only after confirming the load is expected.
3. If saturation is caused by a dependency outage, fix the dependency before scaling the caller.

## Persistent Volume Filling

Alert: `CityIntersectionPersistentVolumeFilling`

1. Identify the PVC and owning workload:

```bash
kubectl -n urban-platform get pvc
kubectl -n urban-platform describe pvc <pvc>
```

2. Check retention settings, log growth, Kafka topics, Redis persistence, Elasticsearch shards, and database backups.
3. Expand storage only after confirming the growth source and backup health.

## Kafka Under-Replicated Partitions

Alert: `UrbanPlatformKafkaUnderReplicatedPartitions`

1. Confirm the Strimzi resources are reconciled without an active warning:

```bash
kubectl -n urban-platform get kafka,kafkanodepool,pods,pvc
kubectl -n urban-platform describe kafka kafka
kubectl -n urban-platform describe kafkanodepool dual-role
```

2. Check node readiness, storage latency and capacity, broker restarts, and zone/host placement before restarting anything.
3. Restore one failed broker or storage path at a time. Do not delete multiple broker PVCs or pods together.
4. Verify `UnderReplicatedPartitions` returns to zero and remains there before closing the incident.

## ClickHouse Sink Consumer Lag

Alert: `UrbanPlatformClickHouseSinkConsumerLagHigh`

1. Check the reconciled worker and task state without printing connector credentials:

```bash
kubectl -n urban-platform get kafkaconnect,kafkaconnector,kafkatopic,kafkauser
kubectl -n urban-platform describe kafkaconnector clickhouse-bemobile-sink
kubectl -n urban-platform get pods -l strimzi.io/cluster=clickhouse-connect
```

2. Compare source ingress rate, consumer lag by partition, task CPU/memory, ClickHouse insert latency, and ClickHouse part/merge pressure.
   For self-managed ClickHouse, also verify Keeper quorum health, the configured
   `keeper_map_path_prefix`, and the connector KeeperMap state table.
3. Scale tasks only up to the source partition count. Increase partitions or ClickHouse capacity before increasing tasks beyond the effective parallelism.
4. Confirm lag is falling steadily and no records are entering the DLQ before declaring recovery.

## ClickHouse Sink DLQ

Alert: `UrbanPlatformClickHouseSinkDeadLetterQueueActive`

1. Treat any DLQ write as a data-correctness incident. Record the topic, partition, offset range, connector generation, and deployment revision without copying payloads into tickets or logs.
2. Inspect connector status and sanitized task errors:

```bash
kubectl -n urban-platform describe kafkaconnector clickhouse-bemobile-sink
kubectl -n urban-platform logs -l strimzi.io/cluster=clickhouse-connect --tail=200
```

3. Validate the source schema, `topic2TableMap`, ClickHouse table schema, permissions, and disk/merge health.
4. Do not replay or delete the DLQ until the fix is deployed, the replay is idempotent, and the affected offset range is preserved for audit.
5. Close the incident only after the DLQ stops growing, lag returns below threshold, and row-count/checksum reconciliation passes.

## Kafka To ClickHouse Production Reconciliation

Use one fail-closed command instead of manually applying Strimzi resources,
preloading images, or waiting on each custom resource separately:

```bash
make kafka-clickhouse-reconcile \
  KAFKA_CLICKHOUSE_PRIVATE_VALUES=/var/lib/urban-platform/private/values-production-private.yaml \
  KAFKA_CLICKHOUSE_KUBECONFIG=/root/.kube/config \
  KAFKA_CLICKHOUSE_APPLY=true
```

Without `KAFKA_CLICKHOUSE_APPLY=true`, the command only validates and writes a
sanitized plan. Apply mode requires the complete 84-point static contract,
established operator APIs, a matching available Strimzi operator, a Ready
external secret store, expandable retained storage, and three failure domains
before Helm can change the cluster. Helm 4 uses `--rollback-on-failure`; the
post-deploy gate must pass twice consecutively at or above `92/100`.

Inspect the public-safe outputs after any failure:

```bash
sed -n '1,200p' reports/kafka-clickhouse-reconcile.md
sed -n '1,200p' reports/kafka-clickhouse-readiness.md
```

## Observability Checks

```bash
make status
make observability-status
kubectl -n observability get pods,svc
kubectl -n urban-platform get prometheusrules.monitoring.coreos.com
```
