# High-Level Design

This document describes the public-safe high-level design for the
`urban-platform-infra` deployment workspace. It intentionally avoids real
customer names, private service names, private IP addresses, credentials,
database names, and full import reports.

Use placeholders such as `node-01`, `cluster-vip`, `platform.example.internal`,
and `private-registry.example.internal` in committed documentation. Keep real
environment values in private inventories, secret managers, or files under the
operator private directory.

## Goals

- Deploy an operator-managed Kubernetes platform for imported and native
  application workloads.
- Support a low-resource lab path and a production HA path without changing
  templates by hand.
- Migrate Compose-based projects into Kubernetes through repeatable checks,
  image promotion or preload, secret cleanup, database dump/restore, and
  generated routing/storage manifests.
- Keep public repository content safe to share while allowing a trusted
  operator machine to hold private migration state.

## Non-Goals

- Do not commit private application source, full Compose imports, database
  dumps, real host paths, or real secrets.
- Do not raw-copy PostgreSQL data directories across major versions or cluster
  topologies.
- Do not treat a single-node or two-node lab as production HA.
- Do not rely on Docker socket mounts inside Kubernetes workloads.

## Logical Architecture

```text
Operators
  |
  | make targets, Ansible, Helmfile, Helm, import automation
  v
Operator machine
  |
  +-- private workspace: reports, DB target map, dumps, generated secrets
  +-- image staging: registry push or RKE2 preload archives
  +-- delivery planning: operator-managed, Argo CD, or Flux GitOps handoff
  +-- rollout planning: rolling update, canary, blue-green, and rollback gates
  +-- scaling planning: right-sizing, HPA, VPA, KEDA, and capacity gates
  +-- evidence planning: control mapping, audit-pack, retention, and export gates
  +-- incident planning: alert routes, escalation, runbooks, drills, and review gates
  +-- change planning: tickets, approvals, maintenance windows, freeze checks, and rollback gates
  +-- cutover planning: DNS/TLS, smoke tests, rollback, approvals, and observation gates
  +-- smoke-test planning: rollout, service, ingress, database, and messaging probes
  +-- release runbook planning: artifacts, approvals, rollback, smoke-test, and cutover gates
  +-- cluster upgrade planning: RKE2 pins, version skew, snapshots, add-ons, and rollback gates
  +-- environment evidence bundles: public report index plus private evidence categories
  +-- recovery planning: RTO/RPO, restore drills, failover runbooks, and continuity gates
  |
  v
Kubernetes access
  |
  +-- direct API endpoint, VIP endpoint, or SSH tunnel fallback
  v
RKE2 cluster
  |
  +-- control plane: RKE2 server nodes, embedded etcd
  +-- HA edge: Keepalived, HAProxy, Traefik
  +-- platform operators: CloudNativePG, cert-manager, External Secrets, optional observability
  +-- platform chart: web gateway, workloads, databases, messaging, policies
  +-- imported workloads: generated Deployments, Services, Ingress candidates
```

## Deployment Profiles

| Profile | Intended Use | Shape | HA |
|---|---|---|---|
| `single-node` | Development, migration rehearsal, small lab | 1 server | No |
| `two-node-lab` | Lab with limited capacity | 1 server + 1 worker | No |
| `three-node-ha` | Default production profile | 3 server/load-balancer nodes | Yes |
| `multi-node-ha` | Larger production capacity | 3 or 5 servers + workers | Yes |

The default production contract is `three-node-ha`. Lab profiles reduce
replicas and disable heavy observability components, but they cannot make a
large application fit into less memory than it needs. For constrained labs,
deploy only a selected subset of workloads or use the import workflow as a
rehearsal path.

## Control Plane and Edge

RKE2 is the default Kubernetes engine. The HA profile places RKE2 servers on an
odd number of control-plane nodes so embedded etcd can keep quorum. HAProxy and
Keepalived provide a stable API and edge VIP when the environment has enough
capacity and network support.

Traffic flow:

```text
client DNS
  -> cluster-vip
  -> HAProxy or node edge listener
  -> Traefik ingress
  -> ClusterIP service
  -> workload pod
```

For labs, direct node API access or SSH tunnel fallback can be used when the VIP
is not ready. Production should use a stable VIP or DNS endpoint and monitored
load-balancer health.

## Platform Services

The platform chart owns the in-repo Kubernetes resources:

- namespace labels, LimitRange, and ResourceQuota
- service account and workload security defaults
- ingress and TLS integration
- web gateway profile
- application workload scaffolding
- PostgreSQL-family database resources through CloudNativePG
- Redis, Kafka, and related messaging components
- optional platform capabilities such as object storage, MQTT, RabbitMQ, NATS,
  identity, policy, workflow engines, secret backends, and service mesh
- optional observability profiles

Helmfile owns upstream operator and dependency charts, such as cert-manager,
External Secrets, CloudNativePG, and optional observability operators.

GitOps delivery is optional and disabled by default. Operator-managed Helm
remains the break-glass and lab path. Argo CD or Flux can reconcile the Helm
chart only after private repository URLs, protected branches, environment
overlays, release evidence, and drift policy are reviewed through the public-safe
GitOps delivery plan.

Progressive delivery is also optional and disabled by default. Standard Helm
rolling updates remain the baseline until operators review rollout controller
ownership, SLO-backed analysis, traffic-splitting support, GitOps handoff, smoke
tests, and rollback drill evidence through the public-safe progressive delivery
plan.

Scaling policy automation is optional and disabled by default. Fixed replicas
and lab capacity gates remain the baseline until operators review workload
requests, metrics adapters, SLO alerting, load-test evidence, event-trigger
contracts, and autoscaler ownership through the public-safe scaling policy plan.

Network connectivity automation is optional and disabled by default. Existing
NetworkPolicy defaults remain the baseline until operators review ingress class
ownership, DNS, TLS, Kubernetes API egress, external egress contracts, service
mesh capacity, and rollback behavior through the public-safe network
connectivity plan.

Access governance automation is optional and disabled by default. The chart
keeps service account token automount disabled while operators review
least-privilege RBAC, OIDC/SSO group mapping, Kubernetes audit retention,
break-glass access, and tenant namespace boundaries through the public-safe
access governance plan.

Compliance evidence automation is optional and disabled by default. Public
reports can summarize readiness, but private evidence indexes, full reports,
restore drills, access reviews, incident drills, retention targets, checksums,
and attestations stay under trusted operator or object-storage ownership until
the public-safe compliance evidence plan is approved.

Incident response automation is optional and disabled by default. Alert routes,
paging integrations, escalation rosters, runbook indexes, stakeholder maps,
incident timelines, and post-incident reviews stay private while operators use
the public-safe incident response plan to prove operational readiness.

Change management automation is optional and disabled by default. Change
tickets, CAB approvals, maintenance windows, freeze calendars, stakeholder
notices, rollback plans, smoke-test evidence, deployment evidence, and
post-change reviews stay private while operators use the public-safe change
management plan to prove release readiness.

Smoke-test automation is optional and disabled by default. Kubernetes rollout
checks, Service DNS checks, HTTP/TLS route checks, TCP backend probes, database
connection checks, messaging connection checks, synthetic monitors, and
owner-reviewed result evidence stay private while operators use the public-safe
smoke-test plan to prove post-migration readiness.

Release runbook automation is optional and disabled by default. Release artifact
evidence, SBOM/checksum/attestation review, private change approvals, rollback
plans, smoke-test plans, cutover gates, environment evidence bundles, and owner
reviews stay private while operators use the public-safe release runbook plan
to prove production promotion readiness.

Cluster upgrade automation is optional and disabled by default. RKE2 target
pins, Kubernetes version skew, etcd snapshot evidence, add-on compatibility,
maintenance windows, node health, rollback plans, and post-upgrade smoke tests
stay private while operators use the public-safe cluster upgrade plan to prove
upgrade readiness before any node drain, service restart, or version change.

Disaster recovery automation is optional and disabled by default. RTO/RPO
objectives, dependency maps, backup replication, recovery sites, restore drill
logs, failover runbooks, supplier contacts, continuity communications, outage
timelines, and post-drill reviews stay private while operators use the
public-safe disaster recovery plan to prove business continuity readiness.

## Import and Migration Design

The import workflow has two levels:

- `import-check` is read-only. It scans the Compose project, compares it with
  selected platform values, and writes a compatibility report.
- `import-auto` is the guarded execution path. It prepares private operator
  state, verifies Kubernetes access, and runs stages for secrets, images,
  databases, manifests, and validation.

Migration stages:

```text
prepare
  -> private report, DB target map, action plan
secrets
  -> Kubernetes Secret manifests from approved literal secret material
images
  -> private registry promotion or RKE2 preload archives
databases
  -> pg_dump and pg_restore into target PostgreSQL-family services
  -> optional engine target scaffolds for MySQL, MariaDB, Microsoft SQL Server, MongoDB, and SQLite
manifests
  -> imported Deployments, Services, ConfigMaps, and Ingress candidates
validate
  -> import-check and cluster object checks
```

All private discovery output stays in ignored reports or the operator private
directory. Redacted reports are safe for tickets and public discussion.

## Database Strategy

PostgreSQL, PostGIS, and TimescaleDB major-version moves use logical
dump/restore. The workflow must not reuse a PostgreSQL 16 data directory as a
PostgreSQL 18 Kubernetes volume.

Target databases should be operator-managed where possible. The generated DB
target map points to Kubernetes service names and secret references rather than
hard-coded credentials.

Optional engines are supported as explicit target profiles instead of hidden
side effects. The importer detects MySQL, MariaDB, Microsoft SQL Server,
MongoDB, and SQLite signals, writes private target-map scaffolds, and waits for
the matching operator, managed service, or external endpoint profile before an
engine-specific dump/restore runner is enabled.

## Image Strategy

Production should use a private registry with scanned and pinned images. Labs
can use RKE2 preload mode when a registry is not available.

| Mode | Use Case | Behavior |
|---|---|---|
| `registry` | Production and repeatable environments | build/tag/push to private registry |
| `preload` | Lab and disconnected tests | save images as tar archives and import to RKE2 nodes |
| `skip` | Routing-only or partial migration | leave image movement out of the run |

The operator machine is a staging point only. Preload archives and local import
tags are cleaned up unless explicitly preserved for troubleshooting.

The optional registry promotion controller adds a disabled-by-default planning
layer before production registry mode. It records the required image pull
secret, private registry target, digest pins, scan/SBOM/signature evidence, and
promotion record without exposing private registry names in public reports.

## Secret Strategy

Committed files define secret contracts and references, not secret values.
Runtime secret material belongs in one of:

- External Secrets
- SOPS
- Sealed Secrets
- Vault or another approved secret manager
- the operator private directory for one-time migration execution

`MIGRATION_ALLOW_SECRET_MATERIAL=true` is an explicit operator approval to read
literal Compose secret values on the trusted operator machine and convert them
to Kubernetes Secrets.

## Backup Strategy

Backup and restore support is optional architecture and disabled by default.
The public repository defines the contracts; each environment owns the actual
object-store buckets, credentials, retention approvals, and restore evidence.

Backup layers:

- CloudNativePG Barman object-store backups for PostgreSQL-family databases
- Velero namespace and persistent-volume metadata backups when explicitly
  installed
- RKE2 embedded etcd snapshots copied off the nodes
- imported image archive retention for RKE2 preload rehearsals
- external adapters such as UrBackup, restic, Kopia, or Borg for host, VM,
  legacy Compose, and operator artifact backups
- secret recovery from the approved secret source of truth

Cold storage is the preferred target for durable backup artifacts. Backup
enablement should be paired with restore drills before production cutover. See
[Backup And Restore](backup-restore.md).

## Resource Strategy

The default chart is lab-friendly: one replica, disabled heavy observability,
resource defaults, and quota controls. That protects the cluster from runaway
imports, but it does not guarantee that a large project can fit into small
nodes.

Storage tiers are optional architecture. The chart supports a hot tier for
active PVCs, a warm tier for compressed or lower-traffic data, and a cold tier
for backups, import dumps, old logs, and release evidence. Labs can enable only
hot storage, such as a local-path class. Production should use durable hot
storage and object-store-backed cold retention. See [Storage Tiers](storage-tiers.md).

For low-resource labs:

- keep observability disabled unless specifically testing it
- keep optional platform capabilities disabled unless specifically testing one
  capability
- run only the services needed for the current rehearsal
- keep databases compact and storage small
- prefer image preload only when a private registry is unavailable
- validate pod requests against node allocatable memory before applying a full
  imported workload set

For production:

- use HA topology
- use private registry digest pins
- use real DNS and TLS
- use durable storage classes
- enable monitoring and alerting after operator CRDs are present
- enable backup layers only after object storage and restore drills are ready
- enable optional platform capabilities from the reviewed capability catalog
- test failover, restore, and rollback paths

## Reliability and Operations

The platform favors guarded automation:

- kubeconfig repair before mutating cluster operations
- retry wrappers around Helmfile and Helm deploys
- recovery helpers for failed Helm releases and stale lab resources
- validation scripts for repo policy, chart defaults, and import safety
- optional GitOps drift planning before automated reconciliation is enabled
- optional progressive delivery planning before traffic shifting is enabled
- optional scaling policy planning before autoscaling controllers are enabled
- optional network connectivity planning before stricter egress or service mesh is enabled
- optional access governance planning before OIDC, RBAC, or tenant isolation is enabled
- runbooks for deployment, stateful workload, and observability failures

## Public-Safe Boundaries

Safe to commit:

- placeholder architecture and topology diagrams
- sanitized commands
- redacted reports
- schema, policy, and template logic
- example inventories with placeholder values

Do not commit:

- real node IP addresses or hostnames
- real kubeconfigs
- full import reports from customer projects
- database dumps
- registry credentials
- secret values
- private image names when disclosure-sensitive

## Related Documents

- [Low-Level Design](lld.md)
- [Architecture](architecture.md)
- [Deployment Topologies](deployment-topologies.md)
- [Optional Platform Capabilities](platform-capabilities.md)
- [Project Import Compatibility](project-import.md)
- [Backup And Restore](backup-restore.md)
- [GitOps Delivery](gitops-delivery.md)
- [Progressive Delivery](progressive-delivery.md)
- [Scaling Policy](scaling-policy.md)
- [Network Connectivity](network-connectivity.md)
- [Access Governance](access-governance.md)
- [Release Runbook](release-runbook.md)
- [Cluster Upgrade](cluster-upgrade.md)
- [Operations](operations.md)
- [Secrets Management](secrets-management.md)
- [Supply Chain](supply-chain.md)
