# Low-Level Design

This document describes the public-safe low-level design for the
`urban-platform-infra` automation and deployment implementation. It is written
for engineers and operators who need to understand how the repository executes
without exposing site-specific values.

Use placeholders such as `node-01`, `cluster-vip`, `namespace`, and
`private-registry.example.internal`. Keep real inventories, kubeconfigs,
reports, secret values, and database target details outside Git.

## Repository Components

| Path | Responsibility |
|---|---|
| `Makefile` | Operator entry points and workflow composition |
| `ansible/` | OS bootstrap, HAProxy/Keepalived, Kubernetes engine install |
| `config/` | Public-safe catalogs and deployment contracts |
| `deploy/helmfile.yaml.gotmpl` | Upstream operators and optional dependency charts |
| `helm/urban-platform-infra/` | Main platform Helm chart |
| `scripts/import_project.py` | Read-only Compose compatibility report |
| `scripts/migrate_project.py` | Guarded import and migration automation |
| `scripts/gitops_delivery_plan.py` | GitOps delivery and drift-control planning |
| `scripts/progressive_delivery_plan.py` | Progressive delivery and rollback readiness planning |
| `scripts/scaling_policy_plan.py` | Scaling policy and capacity automation readiness planning |
| `scripts/network_connectivity_plan.py` | Network connectivity, egress, and service mesh readiness planning |
| `scripts/access_governance_plan.py` | Access governance, RBAC, and tenant isolation readiness planning |
| `scripts/compliance_evidence_plan.py` | Compliance evidence and audit-pack readiness planning |
| `scripts/incident_response_plan.py` | Incident response and operational readiness planning |
| `scripts/change_management_plan.py` | Change management and maintenance-window readiness planning |
| `scripts/disaster_recovery_plan.py` | Disaster recovery and business continuity readiness planning |
| `scripts/tools/ensure-kubeconfig.sh` | Operator kubeconfig repair and RKE2 discovery |
| `scripts/tools/helmfile-sync-retry.sh` | Helmfile retries, API checks, pending release recovery |
| `scripts/tools/install-local-path-storage.sh` | Lab storage bootstrap and host path preparation |
| `scripts/validate.py` | Static repository contract validation |
| `docs/` | Public-safe operator, architecture, and runbook documentation |

## Deployment Execution Flow

`make deploy` prepares the cluster dependencies and deploys the platform chart:

```text
make deploy
  -> install-operators
       -> install Helm and Helmfile if missing
       -> repair operator kubeconfig
       -> ensure StorageClass
       -> helmfile sync upstream operators
       -> wait for required CRDs
  -> ensure-namespace
  -> recover-helm-release
  -> optional edge port configuration
  -> helm upgrade --install helm/urban-platform-infra
```

`make deploy-auto` sets lab/import-friendly recovery flags before calling
`deploy`. It is intended for lab or import recovery, not as a substitute for a
reviewed production rollout plan.

## Import Execution Flow

`make import-auto` is the one-command migration path:

```text
make import-auto
  -> operator-kubeconfig
       -> verify existing kubeconfig
       -> generate temporary inventory from MIGRATION_RKE2_NODES when needed
       -> discover RKE2 token, version, cluster domain, VIP, and HA inputs
       -> try direct API, VIP API, and SSH tunnel fallback
       -> optionally reconcile bootstrap and RKE2 once when API is unhealthy
  -> import-migrate MIGRATION_STAGE=all MIGRATION_EXECUTE=true
       -> prepare
       -> secrets
       -> images
       -> databases
       -> manifests
       -> validate
```

`make import-migrate` can run individual stages for troubleshooting, but the
normal operator path is `import-auto`.

## Public and Private State

Committed public state:

- Helm chart defaults
- example inventories
- deployment topology contracts
- image and service catalogs
- documentation and validation policy

Private operator state:

- `/var/lib/urban-platform/private/import-check-private.md`
- `/var/lib/urban-platform/private/db-targets.yaml`
- `/var/lib/urban-platform/private/db-dumps/`
- `/var/lib/urban-platform/private/images/`
- generated kubeconfigs
- site-specific inventories
- real TLS material and secret values

`reports/` may contain redacted outputs suitable for tickets. Full reports must
stay ignored or external to the repository.

## Configuration Inputs

Common Make variables:

| Variable | Purpose | Public-Safe Example |
|---|---|---|
| `PROJECT_PATH` | External Compose project path | `/path/to/compose-project` |
| `INVENTORY` | Ansible inventory | `inventories/prod/hosts.yml` |
| `VALUES` | Platform Helm values | `helm/urban-platform-infra/values.yaml` |
| `MIGRATION_RKE2_NODES` | RKE2 node addresses or names | `node-01,node-02,node-03` |
| `MIGRATION_SSH_USER` | SSH user for node operations | `ansible` |
| `MIGRATION_IMAGE_MODE` | Image movement mode | `registry`, `preload`, or `skip` |
| `MIGRATION_CLUSTER_VIP` | Kubernetes API/edge VIP override | `cluster-vip` |
| `MIGRATION_RKE2_VERSION` | Fresh-install RKE2 version override | `vX.Y.Z+rke2rN` |
| `MIGRATION_ALLOW_SECRET_MATERIAL` | Allow literal secret import on trusted operator | `true` or `false` |

Optional capability deploy flags are disabled by default. Examples include
`DEPLOY_ENABLE_MINIO`, `DEPLOY_ENABLE_RABBITMQ`,
`DEPLOY_ENABLE_KEYCLOAK`, `DEPLOY_ENABLE_EMQX`, `DEPLOY_ENABLE_NATS`,
`DEPLOY_ENABLE_VAULT`, `DEPLOY_ENABLE_KYVERNO`,
`DEPLOY_ENABLE_TEMPORAL`, `DEPLOY_ENABLE_ARGO_WORKFLOWS`,
`DEPLOY_ENABLE_LINKERD`, and `DEPLOY_ENABLE_ISTIO`.

Private inventories should pin real values. Temporary inventory generation is a
recovery and import convenience for operator runs where a private inventory is
not available.

## Kubernetes Access Repair

`scripts/tools/ensure-kubeconfig.sh` follows this order:

1. Validate the existing operator kubeconfig when present.
2. Recover `MIGRATION_RKE2_NODES` from the fallback temporary inventory when
   possible.
3. Generate a temporary inventory from `MIGRATION_RKE2_NODES` when the private
   inventory is missing.
4. Discover existing RKE2 values from reachable nodes:
   - token
   - installed version
   - cluster domain
   - cluster VIP and API port
   - Keepalived auth and interface
5. Write a kubeconfig that points to the selected endpoint.
6. Try direct node endpoints, VIP endpoint, and SSH tunnel fallback.
7. If the API is listening but not ready and auto-repair is enabled, run the
   bootstrap and install-cluster playbooks once, then retry kubeconfig repair.

The helper must not print secrets. It may print discovered non-secret values,
such as the selected RKE2 version.

## Ansible Design

Ansible owns host-level changes:

- package prerequisites
- sysctl and kernel modules
- Chrony
- HAProxy and Keepalived
- RKE2, K3s, MicroK8s, Docker, or raw scaffolding
- edge port preparation

Production RKE2 inputs are validated before mutation. Required values include a
non-placeholder token, a pinned RKE2 version, cluster domain, VIP, and
Keepalived settings for HA profiles.

The RKE2 version format is:

```text
vMAJOR.MINOR.PATCH+rke2rN
```

Example:

```text
vX.Y.Z+rke2rN
```

Do not document a real production pin in public files if the version is
site-sensitive.

## Helmfile Design

Helmfile installs upstream components that the main chart depends on or can use:

- cert-manager
- External Secrets
- CloudNativePG
- ECK
- kube-prometheus-stack
- OpenTelemetry Collector
- Loki
- Velero
- MinIO
- RabbitMQ
- Keycloak
- EMQX
- NATS
- Vault
- Kyverno
- Temporal
- Argo Workflows
- Linkerd and Istio
- ClickHouse
- other optional observability components

The retry wrapper waits for API stability, handles stale pending releases, and
then runs:

```text
helmfile -f deploy/helmfile.yaml.gotmpl sync
```

Most heavy observability components are disabled by default for low-resource
labs.

## GitOps Delivery Design

GitOps delivery is represented as an intent layer rather than a default runtime
controller. `config/gitops-delivery.yaml` defines disabled operator-managed,
lab Argo CD, production Argo CD, and production Flux profiles. The planner
writes a public-safe report plus a Helm values overlay:

```text
make gitops-delivery-plan
  -> select profile
  -> validate private repo, protected branch, signed-release, and drift controls
  -> write reports/gitops-delivery-plan.md
  -> write reports/gitops-delivery-values.yaml
```

Operator-managed Helm and Helmfile remain the break-glass path. Automated
prune and enforced drift should stay disabled until rollback ownership, private
overlays, controller access, release evidence, and admission policy are ready.

## Progressive Delivery Design

Progressive delivery is represented as a disabled-by-default intent layer.
`config/progressive-delivery.yaml` defines rolling-update, lab canary,
production canary, and production blue-green profiles. The planner writes a
public-safe report plus a Helm values overlay:

```text
make progressive-delivery-plan
  -> select profile
  -> validate controller, traffic provider, GitOps, SLO, and rollback gates
  -> write reports/progressive-delivery-plan.md
  -> write reports/progressive-delivery-values.yaml
```

The Helm chart keeps `progressiveDelivery.enabled=false` by default. Operators
can review Argo Rollouts, Flagger, native, Traefik, Linkerd, or Istio rollout
intent without installing controllers or creating traffic-shift resources from
public configuration. Standard Helm rollback remains the break-glass path until
private analysis templates, smoke tests, and rollback drills are ready.

## Scaling Policy Design

Scaling policy is represented as a disabled-by-default intent layer.
`config/scaling-policy.yaml` defines disabled, lab right-sizing, production HPA,
event-driven KEDA, and enterprise autoscaling profiles. The planner writes a
public-safe report plus a Helm values overlay:

```text
make scaling-policy-plan
  -> select profile
  -> validate metrics, capacity report, SLO, event source, and load-test gates
  -> write reports/scaling-policy-plan.md
  -> write reports/scaling-policy-values.yaml
```

The Helm chart keeps `scalingPolicy.enabled=false` and `autoscaling.enabled=false`
by default. HPA, VPA, KEDA, and cluster autoscaler behavior should be enabled
only through reviewed private overlays after metrics, workload requests, load
tests, and rollback gates are ready.

## Network Connectivity Design

Network connectivity is represented as a disabled-by-default intent layer.
`config/network-connectivity.yaml` defines disabled, lab baseline, production
restricted NetworkPolicy, Linkerd mesh, and Istio mesh readiness profiles. The
planner writes a public-safe report plus a Helm values overlay:

```text
make network-connectivity-plan
  -> select profile
  -> validate traffic inventory, DNS/TLS, egress, and mesh readiness gates
  -> write reports/network-connectivity-plan.md
  -> write reports/network-connectivity-values.yaml
```

The Helm chart keeps `networkConnectivity.enabled=false` by default while the
existing chart NetworkPolicy defaults remain active. Stricter egress and service
mesh settings should be enabled only through reviewed private overlays after
DNS, TLS, health probes, capacity, and rollback paths are proven.

## Access Governance Design

Access governance is represented as a disabled-by-default intent layer.
`config/access-governance.yaml` defines disabled, lab audit, production RBAC,
OIDC/SSO, and multi-tenant readiness profiles. The planner writes a public-safe
report plus a Helm values overlay:

```text
make access-governance-plan
  -> select profile
  -> validate RBAC inventory, identity, audit, break-glass, and tenant gates
  -> write reports/access-governance-plan.md
  -> write reports/access-governance-values.yaml
```

The Helm chart keeps `accessGovernance.enabled=false` by default. Public
overlays do not grant roles, create users, configure OIDC providers, or create
tenant namespaces. Those controls belong in reviewed private overlays after
group mapping, audit retention, and break-glass procedures are proven.

## Compliance Evidence Design

Compliance evidence is represented as a disabled-by-default intent layer.
`config/compliance-evidence.yaml` defines disabled, lab evidence, staging
control review, production audit pack, and regulated retention profiles. The
planner writes a public-safe report plus a Helm values overlay:

```text
make compliance-evidence-plan
  -> select profile
  -> validate control map, private evidence index, release, drill, and retention gates
  -> write reports/compliance-evidence-plan.md
  -> write reports/compliance-evidence-values.yaml
```

The Helm chart keeps `complianceEvidence.enabled=false` by default. Public
overlays do not collect evidence, export private reports, create retention
buckets, or claim certification. Full evidence indexes and audit archives belong
in trusted private storage after control ownership and export approval are
reviewed.

## Incident Response Design

Incident response is represented as a disabled-by-default intent layer.
`config/incident-response.yaml` defines disabled, lab readiness, staging drill,
production on-call, and regulated incident profiles. The planner writes a
public-safe report plus a Helm values overlay:

```text
make incident-response-plan
  -> select profile
  -> validate alert routes, escalation, pager, runbook, drill, and PIR gates
  -> write reports/incident-response-plan.md
  -> write reports/incident-response-values.yaml
```

The Helm chart keeps `incidentResponse.enabled=false` by default. Public
overlays do not page anyone, create tickets, configure Alertmanager, or expose
contact rosters. Production integrations belong in private overlays after
on-call ownership, escalation, communication, and review procedures are proven.

## Change Management Design

Change management is represented as a disabled-by-default intent layer.
`config/change-management.yaml` defines disabled, lab change, staging approval,
production CAB, and regulated change profiles. The planner writes a public-safe
report plus a Helm values overlay:

```text
make change-management-plan
  -> select profile
  -> validate ticket, approval, risk, impact, window, freeze, and rollback gates
  -> write reports/change-management-plan.md
  -> write reports/change-management-values.yaml
```

The Helm chart keeps `changeManagement.enabled=false` by default. Public
overlays do not create tickets, mutate calendars, approve changes, or expose
approver rosters. Production integrations belong in private overlays after
approval ownership, maintenance windows, rollback plans, smoke tests, evidence,
and post-change review procedures are proven.

## Disaster Recovery Design

Disaster recovery is represented as a disabled-by-default intent layer.
`config/disaster-recovery.yaml` defines disabled, lab DR, staging rehearsal,
production DR, and regulated BCP profiles. The planner writes a public-safe
report plus a Helm values overlay:

```text
make disaster-recovery-plan
  -> select profile
  -> validate RTO/RPO, dependency, replication, restore, continuity, and evidence gates
  -> write reports/disaster-recovery-plan.md
  -> write reports/disaster-recovery-values.yaml
```

The Helm chart keeps `disasterRecovery.enabled=false` by default. Public
overlays do not configure recovery sites, mutate DNS, replicate data, restore
clusters, or expose supplier contacts. Production integrations belong in
private overlays after restore drills, failover runbooks, RTO/RPO measurements,
continuity communications, and post-drill review evidence are proven.

## Helm Chart Design

The main chart in `helm/urban-platform-infra` renders:

- Namespace, Pod Security labels, LimitRange, ResourceQuota
- ServiceAccount
- NetworkPolicies
- web gateway Deployment, Service, and Ingress
- application workload Deployments or StatefulSets
- Redis, Kafka, and ZooKeeper resources when enabled
- CloudNativePG database resources
- optional CloudNativePG backup configuration and ScheduledBackup resources
- optional observability resources
- optional platform capability contracts
- monitoring rules and ServiceMonitors when enabled

Replica behavior is controlled centrally through:

```yaml
global:
  defaultReplicas: 1
  replicaOverride: 1
```

Production overrides can raise replicas after capacity and HA testing.

## Storage Tier Design

The chart exposes optional `storageTiers.hot`, `storageTiers.warm`, and
`storageTiers.cold` values. Each tier can be left disabled. When the hot tier is
enabled and has a `storageClassName`, stateful chart components use it as a
fallback if their own storage class is empty.

Current hot-tier fallback users:

- CloudNativePG database clusters
- Kafka
- ZooKeeper
- Redis
- generic StatefulSet workloads

The cold tier includes an object-store contract for backups, import dumps,
snapshots, old logs, and release evidence. The chart does not create
provider-specific buckets or credentials; those remain environment-owned and
should be delivered through secret-management tooling.

## Backup Implementation

Backup support is controlled by disabled defaults:

```yaml
backup:
  enabled: false
databases:
  backup:
    enabled: false
```

`config/backup-policy.yaml` describes the public-safe backup layers and
`scripts/backup_plan.py` renders a report without applying cluster resources.

When `databases.backup.enabled=true`, the CloudNativePG template renders
`spec.backup.barmanObjectStore` only when an object-store target and Secret
reference are configured. `ScheduledBackup` resources are rendered only when
`databases.backup.schedule.enabled=true`.

The Helmfile Velero release is disabled by default and is installed only when
`INSTALL_VELERO=true` or `DEPLOY_ENABLE_VELERO=true` is passed. Velero protects
Kubernetes object and volume metadata; database recovery should use
database-native backup artifacts.

External backup providers are modeled under `backup.externalProviders`.
UrBackup, restic, Kopia, and Borg all default to `enabled: false`; UrBackup
also defaults to `installInCluster: false` because it is meant for external
host, VM, and legacy Compose backup infrastructure, not as the primary
Kubernetes/database backup engine.

## Imported Workload Manifests

`scripts/migrate_project.py` generates Kubernetes resources for imported
application and nginx-like services:

- ConfigMaps for supported nginx configuration binds
- Deployments with one replica
- ClusterIP Services for exposed container ports
- Traefik Ingress candidates for converted edge routes

Generated resources are labeled:

```yaml
app.kubernetes.io/part-of: urban-platform-import
app.kubernetes.io/managed-by: urban-platform-import
```

Docker socket services are skipped by default. They should be replaced with
Kubernetes-native monitoring or least-privilege integrations.

## Image Migration Design

Registry mode:

```text
source image or build context
  -> registry promotion controller plan
  -> tag with import release
  -> push to private registry
  -> capture digest and evidence
  -> reference from Kubernetes manifests
```

The controller plan is generated by
`scripts/images/registry_promotion_controller.py`. It writes a public-safe
report and Helm override template, but it does not perform registry login or
image push. Actual image movement remains in `scripts/migrate_project.py` or an
external promotion pipeline.

Preload mode:

```text
source image or build context
  -> tag with import release
  -> save tar archive on operator
  -> stream archive to each RKE2 node
  -> import into RKE2 containerd when available
  -> remove local and node-side temporary archives
```

Skip mode leaves image movement out of scope for the run. Use it for partial
migration or routing-only rehearsals.

## Database Migration Design

Database migration uses logical dump/restore:

```text
source PostgreSQL-family service
  -> pg_dump custom-format dump
  -> target service from db-targets.yaml
  -> pg_restore with clean/if-exists/no-owner/no-acl behavior
```

The automation prefers local PostgreSQL client binaries. If they are missing,
it can run the selected PostgreSQL client image through the configured container
tool.

Database target entries can point to Kubernetes Secret references so operators
do not paste credentials into committed files.

Optional database engines use the same private target-map contract:

```text
source optional database service
  -> detected engine and port
  -> private target-map scaffold
  -> operator, managed, or external target profile
  -> engine-specific runner enabled after the target profile is declared
```

The first optional engine set covers MySQL, MariaDB, Microsoft SQL Server,
MongoDB, and SQLite. SQLite is treated as a dev/single-pod or externalization
case, not as an HA database.

## Routing and TLS Design

Traefik is the default RKE2 ingress controller. The import flow converts edge
gateway findings into Ingress candidates with `ingressClassName: traefik`.

TLS can be provided through:

- cert-manager generated certificates
- an existing Kubernetes TLS Secret
- External Secrets
- import-time certificate files on the trusted operator machine
- a self-signed fallback for lab testing

Production should use real DNS and an approved issuer.

## Resource Controls

The chart renders namespace resource controls by default:

- `LimitRange` for default CPU and memory requests/limits
- `ResourceQuota` for namespace-wide caps

These controls protect small clusters from unbounded imports. They do not
guarantee that every service can run in a constrained lab. For large imports,
operators should stage workloads in batches or use a larger cluster.

## Validation Gates

Validation is layered:

- `make validate` checks repository contracts and expected defaults.
- `make lint` runs YAML and Ansible/static checks.
- `make deploy-dry-run` renders the Helm chart.
- `make policy` checks rendered manifests.
- `make import-check` reports Compose compatibility issues.
- `make import-auto` finishes with migration validation when execution reaches
  the validation stage.

CI runs static, validation, security, and render lanes. Legacy Ansible/Python
pinning is preserved for compatibility.

## Failure Handling

Common recoverable failures:

- kubeconfig points at an unhealthy VIP
- RKE2 API is listening but not ready
- Helm release is pending or failed
- lab StorageClass is missing
- imported image exists on some nodes but not all
- PostgreSQL client binaries are missing on the operator
- source databases are unavailable during a rehearsal

The automation retries, repairs, skips non-critical lab-only blockers where
configured, and writes private action plans for follow-up. Production runs
should use stricter settings when incomplete migration is unacceptable.

## Public-Safe Review Checklist

Before committing documentation or generated files:

- Replace real node addresses with `node-01`, `node-02`, `node-03`.
- Replace real VIPs with `cluster-vip`.
- Replace real domains with `platform.example.internal`.
- Replace registry hosts with `private-registry.example.internal`.
- Remove real service names when they identify a private system.
- Remove secrets, tokens, kubeconfigs, and database DSNs.
- Keep full import reports outside Git.

## Related Documents

- [High-Level Design](hld.md)
- [Architecture](architecture.md)
- [Project Import Compatibility](project-import.md)
- [Backup And Restore](backup-restore.md)
- [Operations](operations.md)
- [Troubleshooting](troubleshooting.md)
- [Helm Hardening](helm-hardening.md)
