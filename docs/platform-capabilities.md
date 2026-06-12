# Optional Platform Capabilities

This document describes optional enterprise platform capabilities that can be
enabled after capacity, storage, security, and restore/rollback plans are
reviewed. Everything here is disabled by default.

The default lab profile is intentionally small. Do not enable these components
on a constrained lab cluster unless you are testing that specific capability.

## Recommended Enablement Order

| Order | Capability | Recommended Role | Default |
|---|---|---|---|
| 1 | MinIO / S3-compatible object storage | Uploads, artifacts, backups, dumps, release evidence, cold storage | Disabled |
| 2 | MQTT | IoT, sensors, field devices, edge events through EMQX or Mosquitto | Disabled |
| 3 | RabbitMQ | Work queues, retry queues, delayed jobs, non-stream messaging | Disabled |
| 4 | Keycloak | OIDC/SAML SSO, users, groups, roles, admin identity | Disabled |
| 5 | Kafka Schema Registry | Kafka event contract governance | Disabled |
| 6 | Kafka Connect | Data ingest/egress connectors and CDC runtime | Disabled |
| 7 | Debezium | Database change data capture through Kafka Connect | Disabled |
| 8 | Vault | Enterprise secret, PKI, and dynamic credential backend | Disabled |
| 9 | Kyverno | Kubernetes admission policy and image/resource guardrails | Disabled |
| 10 | NATS | Lightweight low-latency pub/sub and edge service messaging | Disabled |
| 11 | Temporal | Durable service workflows and long-running orchestration | Disabled |
| 12 | Argo Workflows | Kubernetes-native batch, migration, and operational workflows | Disabled |
| 13 | Service mesh | mTLS, traffic policy, retries, and mesh telemetry through Linkerd or Istio | Disabled |

## Values Contract

The chart exposes a public-safe catalog under `platformCapabilities`:

```yaml
platformCapabilities:
  enabled: false
  objectStorage:
    minio:
      enabled: false
  messaging:
    mqtt:
      enabled: false
    rabbitmq:
      enabled: false
    nats:
      enabled: false
  kafkaEcosystem:
    strimziOperator:
      enabled: false
    schemaRegistry:
      enabled: false
    kafkaConnect:
      enabled: false
    debezium:
      enabled: false
  identity:
    keycloak:
      enabled: false
  secrets:
    vault:
      enabled: false
  policy:
    kyverno:
      enabled: false
  workflows:
    temporal:
      enabled: false
    argoWorkflows:
      enabled: false
  serviceMesh:
    enabled: false
```

## Helmfile Install Flags

The Helmfile contains disabled optional releases for components that have
standard Helm chart paths in this workspace. They install only when the matching
flag is set intentionally.

```bash
make install-operators DEPLOY_ENABLE_MINIO=true
make install-operators DEPLOY_ENABLE_RABBITMQ=true
make install-operators DEPLOY_ENABLE_KEYCLOAK=true
make install-operators DEPLOY_ENABLE_EMQX=true
make install-operators DEPLOY_ENABLE_NATS=true
make install-operators DEPLOY_ENABLE_STRIMZI=true
make install-operators DEPLOY_ENABLE_VAULT=true
make install-operators DEPLOY_ENABLE_KYVERNO=true
make install-operators DEPLOY_ENABLE_TEMPORAL=true
make install-operators DEPLOY_ENABLE_ARGO_WORKFLOWS=true
make install-operators DEPLOY_ENABLE_LINKERD=true
make install-operators DEPLOY_ENABLE_ISTIO=true
```

Strimzi is available as an opt-in operator install path for Apache Kafka 4.x
KRaft clusters. Kafka Schema Registry, Kafka Connect, Debezium, and Mosquitto
are modeled in the capability catalog because teams often choose an enterprise
distribution, operator, managed service, or custom chart for those pieces. Add
the selected implementation as a private overlay or a reviewed chart integration
when the target architecture is known.

## Lab Guidance

For a small three-node lab with limited memory:

- keep all optional capabilities disabled by default
- enable only one capability at a time
- prefer external MinIO, Keycloak, Vault, or UrBackup-like services when node
  memory is constrained
- keep Temporal, service mesh, and full Kafka ecosystem components out of the
  lab unless the test specifically requires them
- run `make validate` and a Helm dry run before enabling a production profile

## Production Guidance

Before enabling a capability in production:

- confirm node and storage capacity
- declare DNS, ingress, TLS, and secret references
- set resource requests and limits
- define backup and restore behavior
- add policy controls for allowed images and namespaces
- document ownership, alerts, and runbooks
