# Kafka Profiles

Kafka is enabled by default with a backward-compatible Confluent 7.9 ZooKeeper
profile. Newer Kafka runtimes are opt-in because Confluent 8.x and Apache
Kafka 4.x use KRaft and should be rolled out as a planned platform change.
The production overlay selects Apache Kafka 4.3 through Strimzi/KRaft; the
Confluent/ZooKeeper default below remains the compatibility profile for lab and
legacy deployments.

## Supported Profiles

| Profile | Provider | Runtime | Operator |
|---|---|---|---|
| `confluent-7.9-zookeeper` | Confluent Community broker | `confluentinc/cp-kafka:7.9.6` + ZooKeeper | None |
| `confluent-8.2-kraft` | Confluent Community broker | `confluentinc/cp-kafka:8.2.0` | None |
| `apache-4.2-kraft` | Apache Kafka | `apache/kafka:4.2.0` | None |
| `apache-4.3-kraft` | Apache Kafka | `apache/kafka:4.3.0` | None |
| `apache-4.2-strimzi` | Apache Kafka | `Kafka` + `KafkaNodePool` CRs | Strimzi |
| `apache-4.3-strimzi` | Apache Kafka | `Kafka` + `KafkaNodePool` CRs | Strimzi |

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
make install-operators DEPLOY_ENABLE_STRIMZI=true CONFIRM_PROD=true
```

For lab or import clusters, prefer the one-command wrapper:

```bash
make deploy-strimzi-kafka
```

The installer configures the Strimzi operator to watch the platform namespace
by default. Override `STRIMZI_WATCH_NAMESPACES` for a comma-separated namespace
list, or set `STRIMZI_WATCH_ANY_NAMESPACE=true` only when you intentionally want
one operator to reconcile Kafka clusters across all namespaces.
In preload lab workflows, the installer also stages `quay.io/strimzi/operator`
and `quay.io/strimzi/kafka` onto discovered RKE2 nodes before Helm creates
Strimzi pods.

For production, point the installer at the same promoted operator image used by
the private values overlay. The installer passes the digest and pull secret to
the official Strimzi chart and preloads that exact reference when preloading is
enabled:

```bash
make install-operators \
  DEPLOY_ENABLE_STRIMZI=true \
  CONFIRM_PROD=true \
  STRIMZI_OPERATOR_IMAGE_REGISTRY=registry.production.example/platform \
  STRIMZI_OPERATOR_IMAGE_REPOSITORY=quay.io/strimzi \
  STRIMZI_OPERATOR_IMAGE_DIGEST=sha256:<reviewed-strimzi-operator-image-digest> \
  STRIMZI_OPERATOR_IMAGE_PULL_SECRETS=registry-credentials \
  STRIMZI_KAFKA_IMAGE=registry.production.example/platform/quay.io/strimzi/kafka@sha256:<reviewed-kafka-image-digest>
```

Then deploy Kafka as Strimzi-managed custom resources:

```bash
kubectl -n urban-platform delete resourcequota urban-platform-infra-quota --ignore-not-found

helm upgrade --install urban-platform-infra helm/urban-platform-infra \
  --namespace urban-platform \
  --set namespace.resourceQuota.enabled=false \
  --set messaging.kafka.versionProfile=apache-4.2-strimzi \
  --set messaging.kafka.provider=strimzi \
  --set messaging.kafka.mode=operator \
  --set messaging.kafka.strimzi.apiVersion=kafka.strimzi.io/v1 \
  --set messaging.kafka.strimzi.kafkaVersion=4.2.0 \
  --set messaging.kafka.zookeeper.enabled=false
```

For the Apache Kafka 4.3 Strimzi profile, use the same command with
`apache-4.3-strimzi` and `messaging.kafka.strimzi.kafkaVersion=4.3.0`. The
selected Strimzi operator release must advertise support for that Kafka
version before the cluster is reconciled. Kafka 4.3 requires Strimzi `1.1.0`
or newer; the installer now rejects the incompatible Strimzi `1.0.x` and Kafka
4.3 combination before it changes the cluster.

The chart creates a `kafka` service alias to the Strimzi bootstrap service.
Lab plaintext profiles use `kafka:9092`; the production TLS-only profile uses
`kafka:9093` and requires a Strimzi-generated client certificate.
For imported lab clusters, keep the namespace ResourceQuota disabled or raised
before enabling Strimzi; otherwise the operator cannot create the broker pod
when existing imported workloads already exceed the quota.

## Enterprise ClickHouse Sink

`values-production.yaml` defines an opt-in, production-oriented path from the
managed `beMobile` topic to ClickHouse. It adds three Kafka Connect workers,
ClickHouse Kafka Connect `1.4.0`, broker mTLS, least-privilege ACLs, a durable
DLQ, metrics, alerts, and zone-aware placement. The public values file is a
contract, not a directly deployable environment: its endpoint, registry image,
and remote secret keys are deliberate placeholders.

The supplied connector tuning and the production baseline differ in the areas
that protect data correctness and recovery:

| Setting | Supplied value | Production baseline |
|---|---:|---:|
| `tasks.max` | `24` | `6`, never greater than source partitions |
| `exactlyOnce` | `false` | `true` |
| `ignorePartitionsWhenBatching` | `true` | `false` |
| `wait_for_async_insert` | `0` | `1` |
| `errors.retry.timeout` | `60` ms | `300000` ms |
| `errors.retry.delay.max.ms` | not set | `10000` ms |
| `errors.tolerance` | `none` | `all` with a monitored RF=3 DLQ |
| `errors.log.include.messages` | `true` | `false` |
| `consumer.override.max.poll.records` | `50000` | `10000` initial ceiling |
| `consumer.override.fetch.max.wait.ms` | `200` | `500` ms |
| `consumer.override.heartbeat.interval.ms` | `10000` | `3000` ms |
| Sink consumer group | implicit | explicit `connect-clickhouse-bemobile-sink`, with an exact ACL and matching lag alert |
| `consumer.override.isolation.level` | not set | `read_committed` |
| ClickHouse endpoint | fixed IP, port `8123` | DNS, TLS port `8443`, strict validation |
| Credentials | connector fields | `ExternalSecret` to environment provider |
| Internal buffering | implicit | explicitly disabled with exactly-once mode |

Under the repository's enterprise rubric, the supplied connector JSON is an
estimated `38/100`: it has useful throughput tuning, but it does not prove
broker/topic HA and loses most correctness, secret-delivery, TLS, failure
recovery, and live-evidence points. The production profile can earn `100/100`,
but only after the private immutable inputs and reconciled live resources pass
the read-only gate; values YAML alone is intentionally capped at `84/100`.

Six tasks are a starting point, not a universal maximum. Increase source topic
partitions first, then use a manual load test to justify increasing tasks. Keep
`tasks.max` at or below the source partition count; idle tasks add operational
cost without adding throughput.

Start from
`helm/urban-platform-infra/values-kafka-clickhouse-private.example.yaml`, copy
it outside Git, and replace its deployment-specific values:

```yaml
global:
  imageRegistry: registry.production.example/platform
  imagePullSecrets:
    - registry-credentials

secretManagement:
  externalSecrets:
    registryCredentials:
      data:
        - secretKey: .dockerconfigjson
          remoteRef:
            key: production/registry/dockerconfigjson
    clickhouseSinkCredentials:
      data:
        - secretKey: username
          remoteRef:
            key: production/clickhouse/sink-username
        - secretKey: password
          remoteRef:
            key: production/clickhouse/sink-password

messaging:
  kafka:
    image:
      repository: quay.io/strimzi/kafka
      tag: 1.1.0-kafka-4.3.0
      digest: sha256:<reviewed-kafka-image-digest>
    strimzi:
      operatorImage:
        repository: quay.io/strimzi/operator
        tag: 1.1.0
        digest: sha256:<reviewed-strimzi-operator-image-digest>
      connect:
        image:
          repository: clickhouse-kafka-connect
          tag: 1.4.0
          digest: sha256:<reviewed-image-digest>
        networkPolicy:
          egressCidrs:
            - 192.0.2.44/32
        connector:
          hostname: clickhouse.production.example
```

The reserved example hostname, documentation CIDR, and digest placeholders are
intentionally rejected by the readiness gate. Do not deploy the example file
directly; the private copy must contain the promoted registry, pull secret,
real DNS name, narrowly scoped egress CIDR, and reviewed digests.

The promoted image must be based on the matching Strimzi Kafka image and
contain the official ClickHouse connector `1.4.0`. The optional Strimzi build
configuration pins the upstream ZIP with SHA-512, but production disables
in-cluster builds and requires a scanned, signed, SBOM-backed private image.
The production profile also sets `messaging.kafka.strimzi.useCustomKafkaImage`
so the promoted, digest-pinned `messaging.kafka.image` is written to
`Kafka.spec.kafka.image`, Kafka Exporter, and Cruise Control. The promoted
`strimzi.operatorImage` is used by the Topic and User Operators. The live gate
compares the exact broker and cluster-operator references and verifies all four
component overrides in the reconciled Kafka resource; mutable defaults cannot
earn the supply-chain points.
When ClickHouse uses a private CA, include that CA in the promoted Java trust
store; `?sslmode=STRICT` intentionally rejects an untrusted certificate.
For self-managed ClickHouse, exactly-once mode additionally requires a healthy
ClickHouse Keeper deployment and `keeper_map_path_prefix` on the server. Set
`messaging.kafka.strimzi.connect.connector.keeperOnCluster` to the ClickHouse
cluster name when the connector must create its KeeperMap state table with
`ON CLUSTER`. ClickHouse Cloud supplies the Keeper-backed capability, so that
field can remain empty there. A connector task that cannot initialize
KeeperMap must remain failed and cannot pass the live readiness gate.

After installing Strimzi, External Secrets, and Prometheus Operator CRDs, first
run the reconciliation command in its default plan-only mode:

```bash
make kafka-clickhouse-reconcile \
  KAFKA_CLICKHOUSE_PRIVATE_VALUES=/var/lib/urban-platform/private/values-production-private.yaml \
  KAFKA_CLICKHOUSE_KUBECONFIG=/root/.kube/config
```

No cluster resources change in plan mode. After reviewing the sanitized report,
explicitly apply the same immutable inputs:

```bash
make kafka-clickhouse-reconcile \
  KAFKA_CLICKHOUSE_PRIVATE_VALUES=/var/lib/urban-platform/private/values-production-private.yaml \
  KAFKA_CLICKHOUSE_KUBECONFIG=/root/.kube/config \
  KAFKA_CLICKHOUSE_APPLY=true \
  KAFKA_CLICKHOUSE_MINIMUM=100
```

This is one bounded operation: it renders locally, verifies established v1
CRDs, the matching Strimzi operator, a Ready external secret store, an
expandable `Retain` StorageClass, and three distinct Ready failure domains.
It then uses rollback-protected Helm reconciliation and requires two
consecutive passing live observations. It does not preload images, patch
resources, delete PVCs, or print private values. Missing prerequisites stop
the command before cluster mutation.

For a later read-only recheck without a Helm deployment, run the 100-point
gate directly:

```bash
make kafka-clickhouse-readiness \
  KAFKA_CLICKHOUSE_PRIVATE_VALUES=/var/lib/urban-platform/private/values-production-private.yaml \
  KAFKA_CLICKHOUSE_KUBECONFIG=/root/.kube/config \
  KAFKA_CLICKHOUSE_LIVE=true \
  KAFKA_CLICKHOUSE_MINIMUM=100
```

The public profile alone scores `76/100`: it proves repository controls but
cannot prove a private endpoint, immutable promoted image, or live health. A
private overlay raises the maximum static score to `84/100`; live broker/topic
and Connect/connector evidence are required to reach `100/100`.

## Fast Health Checks

Use the Strimzi checks when `messaging.kafka.provider=strimzi`:

```bash
kubectl -n urban-platform get kafka,kafkanodepool
kubectl -n urban-platform get kafkatopic,kafkauser,kafkaconnect,kafkaconnector
kubectl -n urban-platform wait kafka/kafka --for=condition=Ready --timeout=60s
kubectl -n urban-platform get pods -l strimzi.io/cluster=kafka
kubectl -n urban-platform get endpoints kafka kafka-kafka-bootstrap
```

Use the direct StatefulSet checks when `messaging.kafka.provider` is `apache`
or `confluent`:

```bash
kubectl -n urban-platform rollout status statefulset/kafka --timeout=120s
kubectl -n urban-platform get pods,endpoints | grep -Ei 'kafka|zookeeper'
kubectl -n urban-platform exec statefulset/kafka -- kafka-broker-api-versions.sh --bootstrap-server kafka:9092 | head -40
```

## Production Notes

- Mirror selected Kafka images into a private registry and pin digests before
  production rollout.
- Keep ZooKeeper and KRaft profiles separate; do not switch existing persistent
  Kafka volumes between modes without a migration plan.
- Prefer Strimzi for production Kafka on Kubernetes when teams need operator
  management for Kafka, KafkaNodePool, users, topics, rolling updates, and TLS.
- Keep Kafka disabled or single-replica in small labs unless the test requires
  messaging behavior.
