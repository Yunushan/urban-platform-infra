<h1 align="center">Urban Platform Infra</h1>

<p align="center">
  <strong>Enterprise-first HA smart-city intersection platform workspace with 3-node RKE2, live service deployment, web gateway, databases, observability, and multi-platform installation scaffolding.</strong>
</p>

<p align="center">
  <img alt="build" src="https://img.shields.io/badge/build-ready-brightgreen">
  <img alt="release" src="https://img.shields.io/badge/release-v0.1.0-blue">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-0ea5e9">
  <img alt="nodes" src="https://img.shields.io/badge/default%20nodes-3-success">
  <img alt="cluster" src="https://img.shields.io/badge/default%20cluster-RKE2-0f766e">
  <img alt="os" src="https://img.shields.io/badge/default%20OS-Ubuntu%2024.04-e95420">
</p>

<p align="center">
  <img alt="runtime" src="https://img.shields.io/badge/runtime-RKE2%20%7C%20K3s%20%7C%20MicroK8s%20%7C%20Docker%20%7C%20Raw-111827">
  <img alt="ha" src="https://img.shields.io/badge/HA-HAProxy%20%7C%20Keepalived%20%7C%20Chrony-f59e0b">
  <img alt="web" src="https://img.shields.io/badge/web-nginx%20default%20%7C%20Apache%20HTTPD%20%7C%20Tomcat%20%7C%20Traefik-0891b2">
  <img alt="observability" src="https://img.shields.io/badge/observability-Grafana%20%7C%20Loki%20%7C%20Elastic%20%7C%20OpenSearch%20%7C%20Graylog%20%7C%20ClickHouse-7c3aed">
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> •
  <a href="docs/hld.md">HLD</a> •
  <a href="docs/lld.md">LLD</a> •
  <a href="#what-this-repository-deploys">Workloads</a> •
  <a href="#changeable-defaults">Change Defaults</a> •
  <a href="docs/high-availability.md">HA Guide</a> •
  <a href="docs/bootstrap-safety.md">Bootstrap Safety</a> •
  <a href="docs/helm-hardening.md">Helm Hardening</a> •
  <a href="docs/kubernetes-security-posture.md">Kubernetes Security</a> •
  <a href="docs/deployment-topologies.md">Topologies</a> •
  <a href="docs/environment-profiles.md">Environment Profiles</a> •
  <a href="docs/storage-tiers.md">Storage Tiers</a> •
  <a href="docs/platform-capabilities.md">Capabilities</a> •
  <a href="docs/backup-restore.md">Backup/Restore</a> •
  <a href="docs/local-toolchain.md">Local Toolchain</a> •
  <a href="docs/ci-validation.md">CI Validation</a> •
  <a href="docs/operator-workflows.md">Operator Workflows</a> •
  <a href="docs/project-import.md">Project Import</a> •
  <a href="docs/import-recovery.md">Import Recovery</a> •
  <a href="docs/three-node-rke2-tarball-deploy.md">3-Node Deploy</a> •
  <a href="docs/secrets-management.md">Secrets</a> •
  <a href="docs/secret-provider-adapters.md">Secret Providers</a> •
  <a href="docs/supply-chain.md">Supply Chain</a> •
  <a href="docs/image-governance.md">Images</a> •
  <a href="docs/registry-promotion-controller.md">Registry Promotion</a> •
  <a href="docs/runtime-hardening-admission.md">Runtime Hardening</a> •
  <a href="docs/gitops-delivery.md">GitOps Delivery</a> •
  <a href="docs/progressive-delivery.md">Progressive Delivery</a> •
  <a href="docs/scaling-policy.md">Scaling Policy</a> •
  <a href="docs/network-connectivity.md">Network Connectivity</a> •
  <a href="docs/access-governance.md">Access Governance</a> •
  <a href="docs/compliance-evidence.md">Compliance Evidence</a> •
  <a href="docs/incident-response.md">Incident Response</a> •
  <a href="docs/change-management.md">Change Management</a> •
  <a href="docs/cutover-gates.md">Cutover Gates</a> •
  <a href="docs/smoke-tests.md">Smoke Tests</a> •
  <a href="docs/release-runbook.md">Release Runbook</a> •
  <a href="docs/cluster-upgrade.md">Cluster Upgrade</a> •
  <a href="docs/disaster-recovery.md">Disaster Recovery</a> •
  <a href="docs/observability-slo.md">SLOs</a> •
  <a href="docs/platform-support.md">Platform Support</a> •
  <a href="docs/repository-setup.md">GitHub/GitLab</a> •
  <a href="docs/release-guide.md">Release Guide</a> •
  <a href="LICENSE">License</a>
</p>

---

A desktop/operator-first and production-ready deployment workspace for the **urban-platform-infra** stack. It is centered on a default **3-node RKE2 Kubernetes cluster** running on **Ubuntu 24.04**, with full Ubuntu 22.04/24.04/26.04, Debian 11/12/13, RHEL/Rocky Linux/AlmaLinux 7-10, Oracle Linux 10, and CentOS Stream 9-10 node profile support, HAProxy/Keepalived for the control-plane virtual IP, Chrony for time sync, Helm-based application deployment, Docker Swarm/Compose fallback, raw-install scaffolding, and GitHub/GitLab private-repository readiness.

The project is designed so defaults can be changed from configuration instead of editing templates: cluster engine, web server, database family, observability backend, registry, replica counts, hostnames, storage class, hot/warm/cold storage tiers, optional platform capabilities, backup/restore profile, TLS, image tags, and platform profile all live under `config/` and `helm/urban-platform-infra/values.yaml`.

Start with the public-safe [High-Level Design](docs/hld.md) and [Low-Level Design](docs/lld.md) when reviewing the architecture, migration flow, or operator responsibilities. Keep real inventories, node addresses, private reports, and secret material outside Git.

Control-node automation is tested in two lanes: a legacy enterprise lane with Python 3.11 and ansible-core 2.14.18, and a modern lane with Python 3.12/3.13/3.14 and ansible-core 2.20.5.

## Quick Start

```bash
git init urban-platform-infra
cd urban-platform-infra
# copy this repository content into the directory, or unzip the delivered artifact here

cp inventories/example/hosts.yml inventories/prod/hosts.yml
cp .env.example .env
$EDITOR inventories/prod/hosts.yml .env

make operator-ready
make preflight ENV=prod ENGINE=rke2
make bootstrap-check ENV=prod ENGINE=rke2
make install-cluster-check ENV=prod ENGINE=rke2
make bootstrap ENV=prod ENGINE=rke2 CONFIRM_PROD=true
make install-cluster ENV=prod ENGINE=rke2 CONFIRM_PROD=true
make install-operators
make deploy ENV=prod
make status
```

For deploying a previously packaged application archive onto three local RKE2 nodes, use the sanitized runbook in [`docs/three-node-rke2-tarball-deploy.md`](docs/three-node-rke2-tarball-deploy.md). It covers image build/preload, private inventory setup, RKE2 bootstrap, Helm deployment, and verification without committing real node addresses or credentials.

For local workstation setup and validation, run `make operator-ready`. It prepares the local Python toolchain, writes public-safe readiness and capacity reports, checks CI workflow contracts, audits private-data exposure, and runs validation/lint without exposing private operator data. See [`docs/operator-workflows.md`](docs/operator-workflows.md) and [`docs/local-toolchain.md`](docs/local-toolchain.md).

Existing Compose project compatibility check:

```bash
make import-check PROJECT_PATH=/path/to/compose-project INGRESS=traefik WEB=nginx DB=postgresql
make import-check PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true IMPORT_REPORT=reports/import-check-public.md
make environment-profile-plan ENV_PROFILE=lab IMPORT_REDACT=true
make import-migrate PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true
make import-preflight PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true MIGRATION_RKE2_NODES=node-01,node-02,node-03
make edge-migration-plan IMPORT_REDACT=true MIGRATION_INGRESS_HOST=app.example.invalid
make database-migration-plan IMPORT_REDACT=true
make import-migrate PROJECT_PATH=/path/to/compose-project MIGRATION_STAGE=databases MIGRATION_EXECUTE=true MIGRATION_ALLOW_SECRET_MATERIAL=true
make import-migrate PROJECT_PATH=/path/to/compose-project MIGRATION_STAGE=images MIGRATION_EXECUTE=true MIGRATION_IMAGE_MODE=preload MIGRATION_RKE2_NODES=node-01,node-02,node-03
make image-cache-plan MIGRATION_IMAGE_MODE=preload MIGRATION_RKE2_NODES=node-01,node-02,node-03
make backup-plan
make image-promotion-plan IMAGE_PROMOTION_REGISTRY=private-registry.example.invalid/platform
make registry-promotion-plan REGISTRY_PROMOTION_PROFILE=production-registry REGISTRY_PROMOTION_REGISTRY=private-registry.example.invalid/platform IMPORT_REDACT=true
make runtime-hardening-plan RUNTIME_HARDENING_PROFILE=lab-audit IMPORT_REDACT=true
make gitops-delivery-plan GITOPS_DELIVERY_PROFILE=lab-argocd IMPORT_REDACT=true
make progressive-delivery-plan PROGRESSIVE_DELIVERY_PROFILE=lab-canary IMPORT_REDACT=true
make scaling-policy-plan SCALING_POLICY_PROFILE=lab-rightsize IMPORT_REDACT=true
make network-connectivity-plan NETWORK_CONNECTIVITY_PROFILE=lab-baseline IMPORT_REDACT=true
make access-governance-plan ACCESS_GOVERNANCE_PROFILE=lab-audit IMPORT_REDACT=true
make compliance-evidence-plan COMPLIANCE_EVIDENCE_PROFILE=lab-evidence IMPORT_REDACT=true
make incident-response-plan INCIDENT_RESPONSE_PROFILE=lab-readiness IMPORT_REDACT=true
make change-management-plan CHANGE_MANAGEMENT_PROFILE=lab-change IMPORT_REDACT=true
make smoke-test-plan SMOKE_TEST_PROFILE=lab-smoke IMPORT_REDACT=true
make disaster-recovery-plan DISASTER_RECOVERY_PROFILE=lab-dr IMPORT_REDACT=true
make release-evidence RELEASE_TAG=v0.1.0
make verify-release-evidence RELEASE_TAG=v0.1.0
make release-runbook-plan RELEASE_RUNBOOK_PROFILE=lab-release IMPORT_REDACT=true
make cluster-upgrade-plan CLUSTER_UPGRADE_PROFILE=lab-upgrade IMPORT_REDACT=true
```

The read-only checker discovers Compose files, compares service images, ports,
database versions, web gateway choices, and secret-looking environment values
against the selected platform profile, then adds a redaction-aware migration
plan for secrets, database upgrades, Traefik routing, image promotion, and
volume/config conversion. `make import-migrate` generates guarded automation
scripts, automatically prepares the private operator workspace, supports staged
execution with `MIGRATION_STAGE`, and can move images through either registry or
RKE2 preload mode. `make image-cache-plan` writes a public-safe
`reports/image-cache-plan.md` before the heavy import path so operators can
confirm registry/preload mode, RKE2 node count, containerd import behavior, and
operator cache cleanup settings without exposing private node or registry data.
`make registry-promotion-plan` writes a disabled-by-default controller report
and Helm override template for private-registry promotion, image pull secrets,
digest pins, SBOM/scan/signature evidence, and lab preload fallback without
printing private registry names when redaction is enabled.
`make runtime-hardening-plan` writes a disabled-by-default runtime hardening and
admission policy plan so operators can progress from lab audit mode to
restricted Pod Security, read-only root filesystem checks, digest pins, and
signed-image admission without breaking import rehearsals.
`make gitops-delivery-plan` writes a disabled-by-default GitOps delivery and
drift-control plan for operator-managed, Argo CD, or Flux paths. It keeps
private repository URLs and values files out of public reports while recording
which checks must pass before automated reconciliation or drift enforcement.
`make progressive-delivery-plan` writes a disabled-by-default progressive
delivery and rollback plan for rolling-update, canary, and blue-green paths.
It records controller, traffic-shifting, SLO analysis, GitOps, and rollback
drill readiness before Argo Rollouts, Flagger, or service-mesh traffic shifting
is enabled.
`make scaling-policy-plan` writes a disabled-by-default scaling policy and
capacity automation plan for lab right-sizing, HPA, VPA, KEDA, and external
cluster-autoscaler ownership. It keeps runtime autoscaling disabled until
metrics, SLOs, capacity evidence, and load-test evidence are reviewed.
`make network-connectivity-plan` writes a disabled-by-default network
connectivity and service mesh plan for NetworkPolicy, DNS, TLS, Kubernetes API
egress, external egress contracts, and Linkerd/Istio readiness without printing
private routes, node names, VIPs, or CIDR inventories.
`make access-governance-plan` writes a disabled-by-default access governance
and tenant isolation plan for service accounts, least-privilege RBAC, OIDC/SSO,
audit logging, break-glass access, and namespace tenancy without printing users,
groups, tenant names, or identity provider URLs.
`make compliance-evidence-plan` writes a disabled-by-default compliance
evidence and audit-pack readiness plan for control mapping, redacted report
summaries, restore/access/incident evidence, retention, checksums, and
attestation sources without exporting private evidence or claiming
certification.
`make incident-response-plan` writes a disabled-by-default incident response and
operational readiness plan for alert routes, paging, escalation, runbooks,
communications, drills, post-incident review, rollback paths, and evidence
handoff without paging anyone or printing private contacts.
`make change-management-plan` writes a disabled-by-default change management
and maintenance-window plan for ticket, approval, risk, impact, freeze,
stakeholder notice, rollback, smoke-test, deployment evidence, and post-change
review gates without creating tickets, mutating calendars, or printing private
approvers.
`make smoke-test-plan` writes a disabled-by-default post-migration smoke-test
and health-probe plan for Kubernetes rollout, HTTP/TLS routes, TCP services,
database connections, messaging connections, synthetic checks, and private
owner-reviewed evidence without probing private endpoints from CI.
`make disaster-recovery-plan` writes a disabled-by-default disaster recovery
and business continuity plan for RTO/RPO, dependency maps, backup replication,
restore drills, failover runbooks, continuity communications, manual
workarounds, supplier ownership, and post-drill review without printing private
recovery sites or drill evidence.
`make release-runbook-plan` writes a disabled-by-default release runbook and
evidence gate plan that connects release artifacts, change approval, rollback,
smoke-test, cutover, and environment evidence before production promotion
without publishing, deploying, approving, or switching traffic.
`make cluster-upgrade-plan` writes a disabled-by-default cluster upgrade and
version-skew guardrail plan for RKE2/Kubernetes target pins, etcd snapshots,
add-on compatibility, maintenance windows, rollback, and post-upgrade smoke
tests without draining nodes, restarting services, or mutating inventories.
`make database-migration-plan` writes a public-safe
`reports/database-migration-plan.md` so operators can review target-map
readiness, PostgreSQL-family dump/restore behavior, optional-engine scaffolding,
and lab versus production source-skipping rules before the secret-bearing
database stage executes.
`make edge-migration-plan` writes a public-safe
`reports/edge-migration-plan.md` so operators can review Traefik/nginx edge
conversion, TLS mode, HTTP redirect, source allowlist, and backend-Service
readiness before generated route candidates are applied.
`make environment-profile-plan` writes a public-safe
`reports/environment-profile-plan.md` plus
`reports/environment-profile-values.yaml` and
`reports/environment-profile-evidence-bundle.md`, aligning lab/staging/production
intent across topology, Helm values, import profile, image mode, database
migration strictness, edge routing, backups, observability, smoke tests, cutover gates, and
release requirements before any mutating command runs.
`MIGRATION_PROFILE=lab` is the default and writes a
lab-safe values overlay plus small imported workload resource limits for
constrained clusters; use `MIGRATION_PROFILE=production` only after capacity and
cutover plans are ready. `import-auto` runs a cluster preflight before migration
actions and writes `reports/import-migration/import-preflight.md` plus
`reports/import-migration/import-capacity.md`, `import-batches.md`, and
`import-batches.yaml`. Lab imports default to `MIGRATION_IMPORT_BATCH=auto`, so
oversized Compose projects run the first pending bounded batch instead of
applying every generated workload at once. `MIGRATION_RESUME=true` records
completed mutation stages in a private state file so retry runs skip successful
batch stages and advance to the next pending batch. Run
`make import-recovery-plan IMPORT_REDACT=true` before forcing a rerun; it writes
a public-safe recovery and cleanup plan. Execution still
requires explicit operator opt-in. See [`docs/project-import.md`](docs/project-import.md)
and [`docs/import-recovery.md`](docs/import-recovery.md).
Before a production traffic switch, run
`make smoke-test-plan SMOKE_TEST_PROFILE=production-smoke IMPORT_REDACT=true`
and then
`make cutover-gate-plan CUTOVER_GATES_PROFILE=production-cutover IMPORT_REDACT=true`,
then
`make release-runbook-plan RELEASE_RUNBOOK_PROFILE=production-release IMPORT_REDACT=true`.
It confirms import, release, registry/preload, backup, database restore,
DNS/TLS, smoke-test, rollback, change-approval, and final release evidence
readiness without modifying traffic. See [`docs/smoke-tests.md`](docs/smoke-tests.md),
[`docs/cutover-gates.md`](docs/cutover-gates.md), and
[`docs/release-runbook.md`](docs/release-runbook.md).

Local Docker profile:

```bash
make docker-up
make docker-status
```

Private GitHub/GitLab setup:

```bash
scripts/repo/init-local-git.sh
scripts/repo/create-github-repo.sh        # requires GH_TOKEN or gh auth login
scripts/repo/create-gitlab-repo.sh        # requires GITLAB_TOKEN; defaults to visibility=private
scripts/repo/push-all-remotes.sh
```

## What this repository deploys

By default the Kubernetes profile deploys:

| Layer | Default | HA behavior |
|---|---|---|
| Cluster | RKE2 | 3 server nodes, fixed VIP, etcd quorum |
| Control-plane access | HAProxy + Keepalived | VIP failover on `7443` for the API and `9346` for RKE2 registration |
| Edge ingress | RKE2-bundled Traefik | Default ingress class `traefik`; RKE2 owns the bundled Traefik version, with an optional upstream chart pin mode, and nginx/ingress-nginx remains switchable |
| Time sync | Chrony | Installed on every node |
| Web gateway | `nginxinc/nginx-unprivileged:1.31.1` | Low-resource default replica, HTTPS redirect, swappable with Apache HTTPD, Tomcat, or Traefik |
| Application services | Sanitized `example-app-*` images | Skipped by default until real images are configured or imported |
| Kafka | `confluentinc/cp-kafka:7.9.6` + `confluentinc/cp-zookeeper:7.9.6` | One compact broker and ZooKeeper pod for the lab profile |
| Redis | `redis:8.6.2` | One compact Redis pod; Sentinel disabled by default |
| Optional capabilities | Disabled by default | MinIO, MQTT/EMQX, RabbitMQ, NATS, Keycloak, Vault, Kyverno, Temporal, Argo Workflows, Linkerd, Istio, and Kafka ecosystem profiles |
| PostgreSQL/PostGIS/TimescaleDB | `postgres:18.3`, `postgis/postgis:18-3.6`, `timescale/timescaledb:2.26.4-pg18` | CloudNativePG custom resources with one lab instance and 1 Gi storage override |
| Backup/restore | Disabled by default | Optional CloudNativePG Barman object-store backups, optional Velero Helmfile release, external UrBackup/restic/Kopia/Borg adapters, and public-safe backup planning |
| GitOps delivery | Disabled by default | Optional operator-managed, Argo CD, or Flux delivery and drift-control planning with private repo and branch protection guardrails |
| Progressive delivery | Disabled by default | Optional canary, blue-green, analysis-gate, and rollback readiness planning for native, Argo Rollouts, or Flagger paths |
| Scaling policy | Disabled by default | Optional lab right-sizing, HPA, VPA, KEDA, and cluster-autoscaler readiness planning with metrics and load-test guardrails |
| Network connectivity | Disabled by default | Optional NetworkPolicy, DNS, TLS, explicit egress, and Linkerd/Istio readiness planning without exposing private routes |
| Access governance | Disabled by default | Optional service-account, least-privilege RBAC, OIDC/SSO, audit, break-glass, and tenant isolation planning |
| Compliance evidence | Disabled by default | Optional control mapping, evidence index, audit-pack, retention, checksum, and attestation readiness planning |
| Incident response | Disabled by default | Optional alert routing, escalation, paging, runbook, communication, drill, and post-incident readiness planning |
| Change management | Disabled by default | Optional ticket, approval, maintenance-window, freeze, rollback, smoke-test, and post-change review readiness planning |
| Smoke tests | Disabled by default | Optional post-migration rollout, HTTP/TLS, TCP, database, messaging, synthetic, and evidence readiness planning |
| Release runbook | Disabled by default | Optional release artifact, change approval, rollback, smoke-test, cutover, and evidence gate planning |
| Cluster upgrade | Disabled by default | Optional RKE2/Kubernetes version-skew, etcd snapshot, add-on compatibility, rollback, and smoke-test planning |
| Disaster recovery | Disabled by default | Optional RTO/RPO, dependency mapping, backup replication, restore drill, failover, and business continuity readiness planning |
| Observability | Disabled by default | Elasticsearch, Kibana, Grafana, Loki, ClickHouse, Logstash, Prometheus, and OpenTelemetry are opt-in |
| Optional observability | Elastic ECK `9.4.1`, Grafana Loki, OpenSearch, Graylog, ClickHouse | Switchable by Helmfile env flags and values/profile |
| Agent monitoring | `zabbix/zabbix-agent2:ubuntu-7.4.10` | Switchable workload |

Supported topology profiles:

- `single-node`: one VM/server, non-HA.
- `two-node-lab`: one server plus one worker, lab/staging only.
- `three-node-ha`: default production HA.
- `multi-node-ha`: three or five control-plane nodes plus scalable workers.

The default operator bundle pins CloudNativePG 1.29+ and keeps ECK 3.4+
available so PostgreSQL 18 and optional Elastic Stack 9.x resources are
admitted on Kubernetes 1.34.

Topology contracts are in [`config/deployment-topologies.yaml`](config/deployment-topologies.yaml), Helm overrides are in [`helm/urban-platform-infra/topologies/`](helm/urban-platform-infra/topologies/), and starter inventories are in [`inventories/topologies/`](inventories/topologies/).

The image and port inventory is stored in [`config/services.catalog.yaml`](config/services.catalog.yaml). Helm values are stored in [`helm/urban-platform-infra/values.yaml`](helm/urban-platform-infra/values.yaml).

## Changeable defaults

```bash
# Change deployment flavor without template edits
python3 scripts/configure.py --engine k3s --ingress-controller traefik --webserver traefik --observability disabled
python3 scripts/configure.py --engine microk8s --webserver apache-httpd
python3 scripts/configure.py --database cockroachdb
python3 scripts/configure.py --database postgresql --ingress-controller nginx --webserver nginx --observability elasticsearch

# Or use Makefile wrappers
make configure ENGINE=k3s INGRESS=traefik WEB=traefik DB=postgresql OBS=loki
make deploy ENV=prod
```

Supported cluster profiles are defined in [`config/cluster-profiles.yaml`](config/cluster-profiles.yaml):

- `rke2` default production Kubernetes
- `k3s` lightweight/edge Kubernetes
- `microk8s` Canonical MicroK8s profile
- `docker` Docker Compose/Swarm fallback
- `raw` non-container service-install scaffolding

Supported ingress controllers are `traefik` and `nginx`; Traefik is the default RKE2 edge controller. Current operator guidance pins RKE2 as `v1.36.1+rke2r2`. By default `rke2_traefik_source: bundled` lets the pinned `rke2_version` choose the tested Traefik chart/image. If a deployment needs Traefik `v3.7.1`, set `rke2_traefik_source: upstream`, `rke2_traefik_chart_version: "40.2.0"`, and `rke2_traefik_image_tag: "v3.7.1"` in the private inventory. Supported web server profiles are defined in [`config/webservers.yaml`](config/webservers.yaml): `nginx`, `apache-httpd`, `apache-tomcat`, and `traefik`.

Supported database profiles are defined in [`config/databases.catalog.yaml`](config/databases.catalog.yaml), aligned with the database family list from endoflife.date. PostgreSQL is the default because your current stack already includes PostgreSQL, PostGIS, and TimescaleDB images. The import checker also detects optional MySQL, MariaDB, Microsoft SQL Server, MongoDB, and SQLite usage and writes private target-map scaffolds for those engines, while PostgreSQL-family dump/restore remains the automated migration path.

## Repository layout

```text
.
├── ansible/                         # Node bootstrap, HAProxy/Keepalived/Chrony, RKE2/K3s/MicroK8s/Docker/raw roles
├── config/                          # Cluster, services, database, webserver, observability, OS profiles
├── deploy/                          # Helmfile, Argo CD application, kustomize entrypoints
├── docs/                            # HLD, LLD, architecture, HA, operations, release, security, troubleshooting
├── helm/urban-platform-infra/ # Main Helm chart for the HA application platform
├── inventories/                     # Example 3-node inventory, production copy target
├── platform/                        # Linux/BSD/macOS/Windows helper scripts and raw templates
├── scripts/                         # Repo setup, image preload/push, configuration, health checks
├── tests/                           # Static checks and policy tests
├── .github/workflows/               # GitHub Actions CI/CD
└── .gitlab-ci.yml                   # GitLab private repo CI/CD
```

## Production checklist

1. Replace example IP addresses in `inventories/prod/hosts.yml`.
2. Set a real VIP and DNS record in `.env` and `helm/.../values.yaml`.
3. Vault bootstrap tokens and keepalived shared secrets before running mutating Ansible targets.
4. Pin `rke2_version` in production inventory, for example `v1.36.1+rke2r2`; keep `rke2_traefik_source: bundled` unless you intentionally need a specific upstream Traefik chart pin.
5. Push local/private images to a registry or preload them onto all RKE2 nodes with `scripts/images/preload-rke2.sh`.
6. Keep HTTPS redirect enabled; provide `ingress.tls.secretName` through cert-manager, External Secrets, SOPS, Sealed Secrets, or Vault before live production.
7. Review `config/secrets.contract.yaml` and put secret values in SOPS, External Secrets, Sealed Secrets, or Vault.
8. Choose storage classes for CloudNativePG, Kafka, Redis, Elasticsearch, and ClickHouse/OpenSearch if enabled; keep the low-resource lab storage overrides for 4-core/4 GiB nodes.
9. Run `make lint`, `make validate`, `make policy`, `make deploy-dry-run`, and Ansible check targets before production deploy.
10. Run `make image-policy` and use private-registry digest pins for production image overrides.
11. Run `make cluster-doctor` before `import-auto` or `deploy` if the API, VIP, HAProxy, Keepalived, or kubeconfig path is uncertain.
12. Run `make environment-profile-plan ENV_PROFILE=lab` or the matching staging/production profile before large deploy/import work; review `reports/environment-profile-values.yaml` before applying it.
13. Run `make lab-deploy-plan` before using a 4 GiB/node lab; apply `reports/lab-deploy-values.yaml` only after reviewing the progressive deploy plan.
14. Run `make observability-plan` and review `config/slo.yaml`; heavy observability is disabled by default for labs. Enable kube-prometheus-stack/Grafana, OpenTelemetry, Elasticsearch/Kibana, Loki, or ClickHouse only after the nodes have enough capacity, and set chart `monitoring.enabled=true` only after Prometheus Operator CRDs exist.
15. Review `config/backup-policy.yaml` and [`docs/backup-restore.md`](docs/backup-restore.md). Backups are disabled by default; enable CNPG, Velero, and external adapter layers such as UrBackup/restic/Kopia/Borg only after storage, secret references, and restore drills are ready.
16. Review `config/platform-capabilities.yaml` and [`docs/platform-capabilities.md`](docs/platform-capabilities.md). Optional capabilities are disabled by default; enable MinIO, MQTT, RabbitMQ, Keycloak, Vault, Kyverno, workflow engines, or service mesh only after capacity and ownership are clear.
17. Run `make gitops-delivery-plan` before enabling Argo CD or Flux automation. Keep private repo URLs, kubeconfigs, deploy keys, and environment overlays outside public reports; production GitOps should require protected branches and signed/evidenced releases.
18. Run `make progressive-delivery-plan` before enabling canary, blue-green, Argo Rollouts, Flagger, or service-mesh traffic shifting. Keep `autoPromotion=false` until SLO analysis, rollback drills, and GitOps ownership are reviewed.
19. Run `make scaling-policy-plan` before enabling HPA, VPA, KEDA, or cluster autoscaler automation. Keep runtime autoscaling disabled until metrics, SLO alerts, capacity reports, and load-test evidence are reviewed.
20. Run `make network-connectivity-plan` before tightening egress, removing shared lab web access, or enabling Linkerd/Istio. Keep service mesh disabled until DNS, TLS, health probes, capacity, and rollback ownership are reviewed.
21. Run `make access-governance-plan` before enabling OIDC/SSO, broad RBAC changes, tenant namespaces, or break-glass procedures. Keep user/group mappings and identity URLs outside public reports.
22. Run `make smoke-test-plan` before production cutover. Keep private endpoints, database DSNs, synthetic monitors, and result evidence outside public reports.
23. Run `make cutover-gate-plan` before production traffic switch. Keep DNS, TLS, smoke-test endpoints, tickets, approvals, and rollback evidence in private systems; the public report is a readiness gate, not a traffic switch.
24. Run `make release-runbook-plan RELEASE_RUNBOOK_PROFILE=production-release IMPORT_REDACT=true` before production promotion. Keep private approval indexes, change records, rollback owners, and evidence attachments outside public reports.
25. Run `make cluster-upgrade-plan CLUSTER_UPGRADE_PROFILE=production-upgrade IMPORT_REDACT=true` before changing RKE2 or Kubernetes versions. Keep node health, etcd snapshot, release notes, and owner approvals in private systems.
26. Release only signed/evidenced chart artifacts with `make release-evidence`, SHA-256 checksums, SBOM metadata, and GitHub artifact attestations.

## License

This project is released under the MIT License. See [`LICENSE`](LICENSE).
