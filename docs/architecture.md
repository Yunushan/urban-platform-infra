# Architecture

`urban-platform-infra` separates infrastructure, platform services, and application services.

```text
Users / operators
      |
      v
DNS -> VIP -> HAProxy/Keepalived -> RKE2 API / Ingress / Webserver
                                      |
                                      +-- Application services (`example-app-*`)
                                      +-- Messaging: Kafka, ZooKeeper, Redis/Sentinel
                                      +-- Data: CloudNativePG PostgreSQL/PostGIS/TimescaleDB clusters
                                      +-- Observability: Elasticsearch/Kibana/Logstash or Loki/OpenSearch/Graylog/ClickHouse
```

## Principles

- Configuration-first switching: no template rewrites for common changes.
- HA by default: three RKE2 server nodes, replicated stateless services, PDBs, HPA, and topology spread.
- Operator-backed data services where practical.
- Private-repository safe: no real secrets committed.
- Multi-profile deployment: RKE2, K3s, MicroK8s, Docker, and raw installation scaffolding.

For the detailed logical and physical diagrams, request flows, stateful-service
boundaries, failure domains, and topology review checklist, see the
[Canonical Topology](topology.md). The [HLD](hld.md) explains the architectural
decisions; the [LLD](lld.md) maps them to repository paths and Kubernetes
contracts.
