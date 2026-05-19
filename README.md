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
  <a href="#what-this-repository-deploys">Workloads</a> •
  <a href="#changeable-defaults">Change Defaults</a> •
  <a href="docs/high-availability.md">HA Guide</a> •
  <a href="docs/bootstrap-safety.md">Bootstrap Safety</a> •
  <a href="docs/helm-hardening.md">Helm Hardening</a> •
  <a href="docs/kubernetes-security-posture.md">Kubernetes Security</a> •
  <a href="docs/deployment-topologies.md">Topologies</a> •
  <a href="docs/project-import.md">Project Import</a> •
  <a href="docs/three-node-rke2-tarball-deploy.md">3-Node Deploy</a> •
  <a href="docs/secrets-management.md">Secrets</a> •
  <a href="docs/supply-chain.md">Supply Chain</a> •
  <a href="docs/image-governance.md">Images</a> •
  <a href="docs/observability-slo.md">SLOs</a> •
  <a href="docs/platform-support.md">Platform Support</a> •
  <a href="docs/repository-setup.md">GitHub/GitLab</a> •
  <a href="docs/release-guide.md">Release Guide</a> •
  <a href="LICENSE">License</a>
</p>

---

A desktop/operator-first and production-ready deployment workspace for the **urban-platform-infra** stack. It is centered on a default **3-node RKE2 Kubernetes cluster** running on **Ubuntu 24.04**, with full Ubuntu 22.04/24.04/26.04, Debian 11/12/13, RHEL/Rocky Linux/AlmaLinux 7-10, Oracle Linux 10, and CentOS Stream 9-10 node profile support, HAProxy/Keepalived for the control-plane virtual IP, Chrony for time sync, Helm-based application deployment, Docker Swarm/Compose fallback, raw-install scaffolding, and GitHub/GitLab private-repository readiness.

The project is designed so defaults can be changed from configuration instead of editing templates: cluster engine, web server, database family, observability backend, registry, replica counts, hostnames, storage class, TLS, image tags, and platform profile all live under `config/` and `helm/urban-platform-infra/values.yaml`.

Control-node automation is tested in two lanes: a legacy enterprise lane with Python 3.11 and ansible-core 2.14.18, and a modern lane with Python 3.12/3.13/3.14 and ansible-core 2.20.5.

## Quick Start

```bash
git init urban-platform-infra
cd urban-platform-infra
# copy this repository content into the directory, or unzip the delivered artifact here

cp inventories/example/hosts.yml inventories/prod/hosts.yml
cp .env.example .env
$EDITOR inventories/prod/hosts.yml .env

make validate
make lint
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

Existing Compose project compatibility check:

```bash
make import-check PROJECT_PATH=/path/to/compose-project INGRESS=traefik WEB=nginx DB=postgresql
make import-check PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true IMPORT_REPORT=reports/import-check-public.md
make import-migrate PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true
make import-migrate PROJECT_PATH=/path/to/compose-project MIGRATION_STAGE=databases MIGRATION_EXECUTE=true MIGRATION_ALLOW_SECRET_MATERIAL=true
make import-migrate PROJECT_PATH=/path/to/compose-project MIGRATION_STAGE=images MIGRATION_EXECUTE=true MIGRATION_IMAGE_MODE=preload MIGRATION_RKE2_NODES=node-01,node-02,node-03
```

The read-only checker discovers Compose files, compares service images, ports,
database versions, web gateway choices, and secret-looking environment values
against the selected platform profile, then adds a redaction-aware migration
plan for secrets, database upgrades, Traefik routing, image promotion, and
volume/config conversion. `make import-migrate` generates guarded automation
scripts, automatically prepares the private operator workspace, supports staged
execution with `MIGRATION_STAGE`, and can move images through either registry or
RKE2 preload mode. Execution still requires explicit operator opt-in. See
[`docs/project-import.md`](docs/project-import.md).

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
| Web gateway | `nginxinc/nginx-unprivileged:1.31.0` | Low-resource default replica, HTTPS redirect, swappable with Apache HTTPD, Tomcat, or Traefik |
| Application services | Sanitized `example-app-*` images | Skipped by default until real images are configured or imported |
| Kafka | `confluentinc/cp-kafka:7.9.6` + `confluentinc/cp-zookeeper:7.9.6` | One compact broker and ZooKeeper pod for the lab profile |
| Redis | `redis:8.6.2` | One compact Redis pod; Sentinel disabled by default |
| PostgreSQL/PostGIS/TimescaleDB | `postgres:18.3`, `postgis/postgis:18-3.6`, `timescale/timescaledb:2.26.4-pg18` | CloudNativePG custom resources with one lab instance and 1 Gi storage override |
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

Supported ingress controllers are `traefik` and `nginx`; Traefik is the default RKE2 edge controller. By default `rke2_traefik_source: bundled` lets the pinned `rke2_version` choose the tested Traefik chart/image. If a deployment needs Traefik `v3.7.1`, set `rke2_traefik_source: upstream`, `rke2_traefik_chart_version: "40.2.0"`, and `rke2_traefik_image_tag: "v3.7.1"` in the private inventory. Supported web server profiles are defined in [`config/webservers.yaml`](config/webservers.yaml): `nginx`, `apache-httpd`, `apache-tomcat`, and `traefik`.

Supported database profiles are defined in [`config/databases.catalog.yaml`](config/databases.catalog.yaml), aligned with the database family list from endoflife.date. PostgreSQL is the default because your current stack already includes PostgreSQL, PostGIS, and TimescaleDB images.

## Repository layout

```text
.
├── ansible/                         # Node bootstrap, HAProxy/Keepalived/Chrony, RKE2/K3s/MicroK8s/Docker/raw roles
├── config/                          # Cluster, services, database, webserver, observability, OS profiles
├── deploy/                          # Helmfile, Argo CD application, kustomize entrypoints
├── docs/                            # Architecture, HA, platform, operations, release, security, troubleshooting
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
4. Pin `rke2_version` in production inventory; keep `rke2_traefik_source: bundled` unless you intentionally need a specific upstream Traefik chart pin.
5. Push local/private images to a registry or preload them onto all RKE2 nodes with `scripts/images/preload-rke2.sh`.
6. Keep HTTPS redirect enabled; provide `ingress.tls.secretName` through cert-manager, External Secrets, SOPS, Sealed Secrets, or Vault before live production.
7. Review `config/secrets.contract.yaml` and put secret values in SOPS, External Secrets, Sealed Secrets, or Vault.
8. Choose storage classes for CloudNativePG, Kafka, Redis, Elasticsearch, and ClickHouse/OpenSearch if enabled; keep the low-resource lab storage overrides for 4-core/4 GiB nodes.
9. Run `make lint`, `make validate`, `make policy`, `make deploy-dry-run`, and Ansible check targets before production deploy.
10. Run `make image-policy` and use private-registry digest pins for production image overrides.
11. Review `config/slo.yaml`; heavy observability is disabled by default for labs. Enable kube-prometheus-stack/Grafana, OpenTelemetry, Elasticsearch/Kibana, Loki, or ClickHouse only after the nodes have enough capacity, and set chart `monitoring.enabled=true` only after Prometheus Operator CRDs exist.
12. Release only signed/evidenced chart artifacts with `make release-evidence`, SHA-256 checksums, SBOM metadata, and GitHub artifact attestations.

## License

This project is released under the MIT License. See [`LICENSE`](LICENSE).
