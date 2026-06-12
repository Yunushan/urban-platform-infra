# Kafka Profiles

Kafka is enabled by default with a backward-compatible Confluent 7.9 ZooKeeper
profile. Newer Kafka runtimes are opt-in because Confluent 8.x and Apache
Kafka 4.x use KRaft and should be rolled out as a planned platform change.

## Supported Profiles

| Profile | Provider | Runtime | Operator |
|---|---|---|---|
| `confluent-7.9-zookeeper` | Confluent Community broker | `confluentinc/cp-kafka:7.9.6` + ZooKeeper | None |
| `confluent-8.2-kraft` | Confluent Community broker | `confluentinc/cp-kafka:8.2.0` | None |
| `apache-4.2-kraft` | Apache Kafka | `apache/kafka:4.2.0` | None |
| `apache-4.3-kraft` | Apache Kafka | `apache/kafka:4.3.0` | None |
| `apache-4.2-strimzi` | Apache Kafka | `Kafka` + `KafkaNodePool` CRs | Strimzi |

The Confluent 8.2 broker image is configured as a community broker option.
Confluent enterprise features such as commercial Control Center/RBAC/audit
capabilities require separate licensing and should be enabled only through a
private production overlay.

## Confluent 8.2 KRaft

```bash
helm upgrade --install urban-platform-infra helm/urban-platform-infra \
  --namespace urban-platform \
  --set messaging.kafka.versionProfile=confluent-8.2-kraft \
  --set messaging.kafka.provider=confluent \
  --set messaging.kafka.mode=kraft \
  --set messaging.kafka.image.repository=confluentinc/cp-kafka \
  --set-string messaging.kafka.image.tag=8.2.0 \
  --set messaging.kafka.zookeeper.enabled=false
```

## Apache Kafka 4.2 Or 4.3 KRaft

```bash
helm upgrade --install urban-platform-infra helm/urban-platform-infra \
  --namespace urban-platform \
  --set messaging.kafka.versionProfile=apache-4.3-kraft \
  --set messaging.kafka.provider=apache \
  --set messaging.kafka.mode=kraft \
  --set messaging.kafka.image.repository=apache/kafka \
  --set-string messaging.kafka.image.tag=4.3.0 \
  --set messaging.kafka.zookeeper.enabled=false
```

Use `apache-4.2-kraft` and `4.2.0` when a target system must stay on the 4.2
line.

## Apache Kafka With Strimzi

Install the operator first:

```bash
make install-operators DEPLOY_ENABLE_STRIMZI=true
```

The installer configures the Strimzi operator to watch the platform namespace
by default. Override `STRIMZI_WATCH_NAMESPACES` for a comma-separated namespace
list, or set `STRIMZI_WATCH_ANY_NAMESPACE=true` only when you intentionally want
one operator to reconcile Kafka clusters across all namespaces.

Then deploy Kafka as Strimzi-managed custom resources:

```bash
helm upgrade --install urban-platform-infra helm/urban-platform-infra \
  --namespace urban-platform \
  --set messaging.kafka.versionProfile=apache-4.2-strimzi \
  --set messaging.kafka.provider=strimzi \
  --set messaging.kafka.mode=operator \
  --set messaging.kafka.strimzi.apiVersion=kafka.strimzi.io/v1 \
  --set messaging.kafka.strimzi.kafkaVersion=4.2.0 \
  --set messaging.kafka.zookeeper.enabled=false
```

The chart creates a `kafka` service alias to the Strimzi bootstrap service so
imported workloads can keep using `kafka:9092`.
Strimzi operator `1.0.0` supports Kafka `4.2.0` but not `4.3.0`; use the
direct `apache-4.3-kraft` profile when you need Kafka `4.3.0` before Strimzi
adds support for it.

## Production Notes

- Mirror selected Kafka images into a private registry and pin digests before
  production rollout.
- Keep ZooKeeper and KRaft profiles separate; do not switch existing persistent
  Kafka volumes between modes without a migration plan.
- Prefer Strimzi for production Kafka on Kubernetes when teams need operator
  management for Kafka, KafkaNodePool, users, topics, rolling updates, and TLS.
- Keep Kafka disabled or single-replica in small labs unless the test requires
  messaging behavior.
