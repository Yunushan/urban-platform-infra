# Project Import Compatibility

Use the import checker before migrating an existing Docker Compose project into
the RKE2/Helm platform. It is read-only: it scans the external project, reports
compatibility findings, and does not copy files, modify Compose files, or deploy
anything.

```bash
make import-check PROJECT_PATH=/path/to/compose-project INGRESS=traefik WEB=nginx DB=postgresql
```

To keep a Markdown report:

```bash
make import-check PROJECT_PATH=/path/to/compose-project IMPORT_REPORT=reports/import-check.md
```

The `reports/` directory is ignored by Git because full import reports can
contain private service names, project filenames, host paths, and image names.
Use redaction for a report that can be attached to tickets or shared outside the
operator machine:

```bash
make import-check PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true IMPORT_REPORT=reports/import-check-public.md
```

Every report includes a migration plan section. In redacted mode, that plan
keeps exact project paths, Compose filenames, service names, and application
image names hidden while still showing the selected target infrastructure, such
as Traefik ingress, the selected webserver image, and PostgreSQL-family target
images.

To generate an automation bundle instead of only a report:

```bash
make import-migrate PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true
```

This writes guarded scripts under `reports/import-migration/` and automatically
prepares the private operator workspace. The preparation step creates
`/var/lib/urban-platform/private`, writes a full private import report there,
initializes `/var/lib/urban-platform/private/db-targets.yaml`, secures the
files with restrictive permissions, and prints the generated bundle files.
For a diagnostics-only run that does not need cluster access or apply anything,
use:

```bash
make import-plan PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true
```

`import-plan` writes the private report and
`/var/lib/urban-platform/private/operator-action-plan.md`. The action plan
lists exact Compose files and services, separates items handled automatically
from true manual blockers, and avoids requiring operators to run ad-hoc `grep`
commands against the application tree.

Dry-run bundle generation is the default. For the normal operator workflow, use
one command that prepares the private workspace, runs every guarded stage, and
finishes with a post-migration validation report:

```bash
make environment-profile-plan ENV_PROFILE=lab IMPORT_REDACT=true
make import-auto PROJECT_PATH=/path/to/compose-project \
  IMPORT_REDACT=true \
  MIGRATION_EXECUTE=true \
  MIGRATION_ALLOW_SECRET_MATERIAL=true \
  MIGRATION_IMAGE_MODE=preload \
  MIGRATION_RKE2_NODES=node-01,node-02,node-03
```

`import-auto` is a convenience wrapper around `import-migrate` with
`MIGRATION_STAGE=all` and `MIGRATION_EXECUTE=true`. It first runs the
operator-kubeconfig repair target, then verifies Kubernetes API reachability
with `MIGRATION_KUBECONFIG`, runs the import cluster preflight, and only then
applies secrets, reads database target secrets, or applies manifests. Use it
after the dry-run report looks correct and the operator machine has access to
the Compose project, Docker, Kubernetes, and the RKE2 nodes.
`make environment-profile-plan` should be the first public-safe planning command
for a lab, staging, or production migration. It writes
`reports/environment-profile-plan.md` and
`reports/environment-profile-values.yaml`, plus
`reports/environment-profile-evidence-bundle.md`, aligning `MIGRATION_PROFILE`,
`MIGRATION_IMAGE_MODE`, database migration strictness, edge routing, backup,
observability, optional capabilities, cutover gates, and release evidence
requirements before the mutating import command runs.

If the API, VIP, HAProxy, Keepalived, SSH/sudo, or kubeconfig path is unclear,
run `make cluster-doctor` first. It writes `reports/cluster-doctor.md` with
public-safe node aliases and no private endpoints or raw journals.

To run only the cluster gate:

```bash
make import-preflight PROJECT_PATH=/path/to/compose-project \
  IMPORT_REDACT=true \
  MIGRATION_RKE2_NODES=node-01,node-02,node-03
```

The preflight writes `reports/import-migration/import-preflight.md` and fails
before migration actions when Kubernetes `/readyz`, node readiness, memory or
disk pressure, StorageClass availability, or RKE2/HA node services are not
healthy. It also writes `reports/import-migration/import-capacity.md`, which
counts generated imported workloads, totals their resource requests, compares
them with cluster allocatable CPU/memory, and stops a lab import when the
workload count is above `MIGRATION_PREFLIGHT_MAX_IMPORTED_WORKLOADS` (`40` by
default). The same run writes `reports/import-migration/import-batches.md` and
`reports/import-migration/import-batches.yaml`; in lab mode
`MIGRATION_IMPORT_BATCH=auto` selects the first batch with pending secret,
image, or manifest work when the generated workload set is larger than
`MIGRATION_BATCH_SIZE`. In lab mode, ingress DNS/TLS endpoint reachability is
reported as a warning by default because the route may not exist yet. In
production mode, `MIGRATION_IMPORT_BATCH=all` and
`MIGRATION_PREFLIGHT_REQUIRE_INGRESS_ENDPOINT=true` are the defaults.
The bundle also writes `reports/import-migration/import-resume.md`, a public-safe
view of which stateful stages are pending or completed for the selected batch.
After a failed or interrupted run, use `make import-recovery-plan
IMPORT_REDACT=true` to write
`reports/import-migration/import-recovery-plan.md`, which summarizes resume
status, safe retry controls, Cleanup Boundaries, and rollback boundaries before
any force-rerun decision.

For lab deploys before import, run `make lab-deploy-plan`. It estimates the
committed platform defaults against a small-node budget and writes
`reports/lab-deploy-values.yaml`, which can be used as a first-wave deploy
overlay before importing application batches.

## Import Profiles

`MIGRATION_PROFILE=lab` is the default. It is designed for constrained clusters
and writes `reports/import-migration/lab-profile-values.yaml` plus
`reports/import-migration/import-profile.md` into the migration bundle. The lab
profile also writes `reports/import-migration/import-preflight.md` and
`reports/import-migration/import-capacity.md` when the preflight stage runs,
plus `reports/import-migration/import-batches.md` and
`reports/import-migration/import-batches.yaml` whenever the bundle or preflight
stage runs. `MIGRATION_RESUME=true` is enabled by default and records completed
stateful stages in `/var/lib/urban-platform/private/migration-state.yaml`.
The lab profile keeps imported workloads to one replica, adds small CPU/memory
requests and limits to generated imported Deployment manifests, keeps
autoscaling, observability, backups, and optional platform capabilities
disabled, and constrains platform database, Kafka, ZooKeeper, and Redis defaults
for small clusters. In lab mode, `MIGRATION_IMAGE_MODE` defaults to `preload`
and unavailable database sources are skipped with a private report entry so a
small lab can continue. For very large Compose projects, import a subset first
or deliberately raise `MIGRATION_PREFLIGHT_MAX_IMPORTED_WORKLOADS`; the default
limit is meant to protect 4 GiB lab nodes from starting too many small-request
pods at once. Batch selection applies to service-specific secrets, image
promotion/preload, generated workload manifests, and matching Traefik route
candidates. Database target maps and PostgreSQL-family dump/restore remain
global because databases are shared dependencies controlled by
`MIGRATION_DB_TARGETS`. In production mode, `MIGRATION_IMAGE_MODE` defaults to
`registry` and unavailable database sources fail the run unless explicitly
overridden.

To run later lab batches after the first automatic batch, rerun the same
`import-auto` command. Resume state skips completed batch stages and
`MIGRATION_IMPORT_BATCH=auto` advances to the next pending batch:

```bash
make import-auto PROJECT_PATH=/path/to/compose-project \
  IMPORT_REDACT=true \
  MIGRATION_ALLOW_SECRET_MATERIAL=true \
  MIGRATION_IMAGE_MODE=preload \
  MIGRATION_RKE2_NODES=node-01,node-02,node-03
```

Set `MIGRATION_IMPORT_BATCH=all` only when the capacity report shows the full
import fits the cluster or when production capacity has already been planned.

## Resume And Retry

`import-auto` is resumable for mutation stages that are expensive or safe to
skip after success: service-specific secrets, image promotion/preload,
PostgreSQL-family database migration, and generated workload manifests. When a
stage completes, the automation records a private completion key in
`MIGRATION_STATE_FILE` (`/var/lib/urban-platform/private/migration-state.yaml`
by default). Re-running the same command skips completed stateful stages for the
same profile, namespace, image mode, registry, image tag, selected batch,
database target map fingerprint, and service scope. Preflight and validation
still run because cluster health and validation results can change.

To force a stage to run again without deleting the private state file:

```bash
make import-auto PROJECT_PATH=/path/to/compose-project \
  IMPORT_REDACT=true \
  MIGRATION_ALLOW_SECRET_MATERIAL=true \
  MIGRATION_FORCE_RERUN=true
```

Use `MIGRATION_RESUME=false` for a one-off run that ignores the state file. Use
`MIGRATION_STATE_FILE=/var/lib/urban-platform/private/<name>.yaml` when you want
separate lab rehearsals to keep separate resume histories.

For a public-safe recovery view before retrying, run:

```bash
make import-recovery-plan IMPORT_REDACT=true
```

The generated `import-recovery-plan.md` is plan-only. It explains resume status,
operator cache cleanup, node-side image retention, database dump retention,
generated-manifest rollback boundaries, and the exact retry knobs to use without
printing private state keys or operator paths when redaction is enabled.

Use `MIGRATION_PROFILE=production` only after capacity, registry/preload,
storage, backup, and database migration plans are ready. Production mode does
not inject lab resource limits into imported workload manifests.

When `MIGRATION_ALLOW_SECRET_MATERIAL=true` is set, `import-auto` treats literal
Compose secret values as operator-approved input, imports them into Kubernetes
Secrets, and records the action in the private action plan. Docker socket mounts
are not carried into Kubernetes by default; services that require
`/var/run/docker.sock` are skipped as Docker-socket integrations and should be
replaced with Kubernetes-native monitoring or another least-privilege approach.
Set `MIGRATION_SKIP_DOCKER_SOCKET_SERVICES=false` only for a deliberate
diagnostic run where you want those services included in image handling.

Set `MIGRATION_SECRET_PROVIDER=external-secrets` or
`MIGRATION_SECRET_PROVIDER=vault` when imported service secrets should be
represented as `ExternalSecret` resources instead of direct Kubernetes Secret
objects. The import stage uses `MIGRATION_SECRET_STORE_NAME`,
`MIGRATION_SECRET_STORE_KIND`, `MIGRATION_SECRET_REFRESH_INTERVAL`, and
`MIGRATION_SECRET_REMOTE_PREFIX` to build remote references without printing or
committing secret values. `MIGRATION_SECRET_PROVIDER=sops` and
`MIGRATION_SECRET_PROVIDER=sealed-secrets` are protected handoff modes; they do
not apply plain Secret material and require the selected encrypted-Git workflow
to produce the final artifacts.

If the private production inventory is not present on the operator machine,
`operator-kubeconfig` can generate a temporary inventory from
`MIGRATION_RKE2_NODES`. Without `MIGRATION_CLUSTER_VIP`, that temporary
inventory points kubectl at the first RKE2 node on port `6443`; set
`MIGRATION_CLUSTER_VIP` and `MIGRATION_KUBERNETES_API_VIP_PORT` when the
cluster API must be reached through a VIP or load balancer. In temporary
inventory mode, the helper fetches `/etc/rancher/rke2/rke2.yaml` directly over
SSH from the first RKE2 node, discovers the existing RKE2 token, installed RKE2
version, and cluster domain when available, and generates a private token only
for fresh installs where RKE2 is not already installed. It honors
`MIGRATION_SSH_USER` and `MIGRATION_SSH_KEY`. The SSH user should normally have
passwordless sudo; if it does not, the helper prompts once on an interactive
terminal and reuses that password only for the current run. For non-interactive
runs, put the sudo password in a local private file with mode `0600` and set
`MIGRATION_BECOME_PASSWORD_FILE`; use
`MIGRATION_BECOME_PASSWORD_PROMPT=false` to fail instead of prompting. Use
`MIGRATION_RKE2_VERSION` or
`MIGRATION_CLUSTER_DOMAIN` only when installing onto fresh nodes where those
values cannot be discovered yet. When migration node addresses are available and
the Kubernetes API is listening but not ready, the same temporary inventory is
used to reconcile the bootstrap and RKE2 playbooks once, then kubeconfig repair
is retried. Three-node HA repair requires at least two SSH-reachable servers by
default. Set `MIGRATION_AUTO_REPAIR_CLUSTER=false` to disable that repair pass.
For current RKE2 lab imports, pin fresh installs with
`MIGRATION_RKE2_VERSION=v1.36.1+rke2r2`.

Before executing image migration, run `make image-cache-plan` with the same
`MIGRATION_IMAGE_MODE`, `MIGRATION_RKE2_NODES`, and registry settings you plan
to use. It writes `reports/image-cache-plan.md`, a public-safe summary of the
image cache, preload, containerd import, and cleanup contract.

For production registry mode, also run `make registry-promotion-plan` before
the mutating image stage. It writes
`reports/registry-promotion-controller.md` and
`reports/registry-promotion-values.yaml`, confirming the private-registry
profile, image pull secret, digest-pin requirement, and scan/SBOM/signature
evidence contract without logging in, pushing images, or printing private
registry details when `IMPORT_REDACT=true`.

Image migration has three modes:

- `MIGRATION_IMAGE_MODE=registry` builds and pushes application images to a
  private registry. This is the production-friendly mode and is the only mode
  that needs registry credentials.
- `MIGRATION_IMAGE_MODE=preload` builds images, saves each image as a tar
  archive, and can copy it to RKE2 nodes under
  `/var/lib/rancher/rke2/agent/images` when `MIGRATION_RKE2_NODES` is set. This
  avoids registry login. By default it also verifies the tar archive on each
  node and imports it into the running RKE2 containerd socket when that socket is
  available. The operator machine is used only as a short-lived staging point;
  generated import tags, local preload archives, and dangling container build
  cache are cleaned up automatically unless
  `MIGRATION_CLEANUP_OPERATOR_IMAGES=false` is set. Set
  `MIGRATION_PRUNE_OPERATOR_CACHE=false` only when you intentionally want to keep
  dangling Podman/Docker build cache on the operator for debugging or repeated
  retry speed. Only the current archive is copied to nodes; stale local archives
  from earlier failed runs are removed before the run and are not sent again.
  Node-side preload transfer streams one archive at a time through sudo into the
  RKE2 image directory; each archive is imported and removed before the next
  archive is copied. On retries, candidates already present on every RKE2 node
  skip build, archive save, and upload; nodes that already have a partially
  migrated image skip that archive upload. If the operator container cache has a
  corrupted build layer and archive save fails, build-only candidates are rebuilt
  once with `--no-cache` before failing the import.
- `MIGRATION_IMAGE_MODE=skip` leaves application image movement out of the
  migration run. Use this when keeping the existing Compose deployment running
  temporarily behind external routing.
- The database stage uses local `pg_dump` and `pg_restore` for PostgreSQL-family services when they are
  installed. If they are missing, it falls back to the selected container tool
  with `MIGRATION_POSTGRES_CLIENT_IMAGE` (`docker.io/library/postgres:18.3` by
  default) and `--network host`, so the operator does not need PostgreSQL client
  packages installed manually. Source databases that are not reachable on their
  Compose-published localhost ports are skipped by default and listed in the
  output; set `MIGRATION_SKIP_UNAVAILABLE_DATABASES=false` when a production
  migration must fail instead of continuing without that data.
- MySQL, MariaDB, Microsoft SQL Server, MongoDB, and SQLite are detected and
  written into `/var/lib/urban-platform/private/db-targets.yaml` with engine,
  port, target-mode, and migration-tool placeholders. Their dump/restore runners
  stay scaffolded until the exact operator, managed service, or external target
  profile is declared.

Before executing the database stage, run `make database-migration-plan`. It
writes `reports/database-migration-plan.md`, a public-safe controller summary of
the target map status, PostgreSQL client fallback, dump/restore flags, engine
support, and lab versus production source availability rules.

Image migration uses `MIGRATION_CONTAINER_TOOL=auto` by default. The automation
prefers `docker` when it is installed, otherwise it uses `podman`. Set
`MIGRATION_CONTAINER_TOOL=docker` or `MIGRATION_CONTAINER_TOOL=podman` to force
one tool explicitly.

Imported Traefik route candidates use HTTPS by default. `MIGRATION_INGRESS_HOST`
controls the route host and defaults to `MIGRATION_CLUSTER_DOMAIN`; the Helm
chart uses `ingress.host` or `global.cluster.domain` the same way. By default,
the chart renders cert-manager `Issuer` and `Certificate` resources so
cert-manager creates `ingress.tls.secretName` with a self-signed certificate
without the chart rendering a plain Kubernetes Secret. Set
`ingress.tls.createSecret=false` to use an existing TLS secret, use
`ingress.tls.certManager.issuerName` for a production issuer, or enable
`secretManagement.externalSecrets.ingressTls`.
Run `make edge-migration-plan` before applying route candidates. It writes
`reports/edge-migration-plan.md`, a public-safe view of the selected ingress
class, TLS mode, HTTP redirect, source allowlist, backend-Service apply guard,
and nginx/Traefik edge conversion rules.
For `import-auto`, set `MIGRATION_TLS_CERT_FILE` and `MIGRATION_TLS_KEY_FILE`
to create the ingress TLS secret from your certificate files; otherwise the
import stage creates a self-signed fallback secret for `MIGRATION_INGRESS_HOST`.
When execution is enabled, generated Ingress candidates are applied only if
their backend Kubernetes Service already exists in the target namespace. If the
Compose edge service has not been converted to a chart workload yet, the
candidate is still written to `reports/import-migration/manifests/` but is not
applied as a broken route.

No-registry preload example:

```bash
make import-migrate PROJECT_PATH=/path/to/compose-project \
  MIGRATION_STAGE=images \
  MIGRATION_EXECUTE=true \
  MIGRATION_IMAGE_MODE=preload \
  MIGRATION_RKE2_NODES=node-01,node-02,node-03
```

Available stages are `prepare`, `bundle`, `preflight`, `secrets`, `images`,
`databases`, `manifests`, `validate`, and `all`. Stage-by-stage execution is mainly for
troubleshooting a failed section. For example:

```bash
make import-migrate PROJECT_PATH=/path/to/compose-project \
  MIGRATION_STAGE=databases \
  MIGRATION_EXECUTE=true \
  MIGRATION_ALLOW_SECRET_MATERIAL=true
```

PostgreSQL-family database dump/restore is performed by the automation when
execution is enabled. The restore step uses the generated private DB target map.
For CloudNativePG targets from the selected Helm values, the map points at the
generated app secret for each database instance, so operators do not have to
paste target passwords into the file. Optional engines use the same private map
for target scaffolding until their engine-specific runner is enabled. The map can
still use a direct DSN when needed:

```yaml
databaseTargets:
  service-name-or-alias:
    host: target-service-rw.namespace.svc
    port: 5432
    database: target_db
    secretRef:
      name: target-service-app
      namespace: namespace
      usernameKey: username
      passwordKey: password
```

To avoid manual `docker login`, export registry credentials before running the
image stage. If they are absent, the automation uses Docker's existing
credential store:

```bash
export MIGRATION_REGISTRY_USERNAME=<registry-user>
export MIGRATION_REGISTRY_PASSWORD=<registry-password>
```

Use strict mode when warnings should fail the gate:

```bash
make import-check PROJECT_PATH=/path/to/compose-project IMPORT_STRICT=true
```

## What It Checks

The checker recursively discovers Compose files such as `compose.yaml`,
`docker-compose.yml`, and `docker-compose.prod.yml`. It inventories service
images, build-only services, published ports, environment variables, env files,
and bind mounts.

It compares the project against the selected platform profile:

- `INGRESS=traefik` warns when a Compose service publishes host ports `80` or
  `443`, or when the project includes a second Traefik edge controller.
- `WEB=nginx` expects the platform gateway image
  `nginxinc/nginx-unprivileged:1.31.1` and flags rootful or version-drifted
  nginx images.
- `DB=postgresql` expects the PostgreSQL/CloudNativePG migration path. It flags
  PostgreSQL majors older or newer than the platform default `18`, and fails
  very old majors that do not fit the supported path.
- `DB=mysql`, `DB=mariadb`, `DB=microsoft-sql-server`, `DB=mongodb`, and
  `DB=sqlite` are optional profiles. The checker recognizes their Compose
  services and the migration generator prepares private target-map scaffolds
  without exposing service names, node addresses, or credentials in public
  reports.
- Approved runtime images are compared with `config/image-policy.yaml`.
- Literal secret-looking environment values, Docker socket mounts, mutable image
  tags, and host bind mounts are reported before they can leak into Git or Helm.
- The migration plan groups remediation into secrets, database upgrades, edge
  routing, image promotion, volume/config conversion, and the validation loop.

## Migration Flow

1. Run `make import-check PROJECT_PATH=/path/to/compose-project`.
2. Resolve `ERROR` findings first, especially literal secrets, Docker socket
   mounts, and unsupported database versions.
3. Decide whether each Compose web or proxy service becomes a backend Service,
   a platform webserver replacement, or a Traefik Ingress route.
4. Build and push any build-only application images to the private registry, or
   preload them onto RKE2 nodes during offline installs.
5. Translate data stores to the selected operator, managed-service, or external
   endpoint profile. For PostgreSQL-family services, the automation performs
   dump/restore against the selected major version when execution is enabled.
   Optional database engines are imported after their target profile and runner
   settings are present in the private target map.
6. Put private paths, node addresses, passwords, tokens, and TLS material in
   private inventory or secret-management tooling, not in the public repository.
7. Re-run the checker with `IMPORT_STRICT=true`, then proceed to Helm values and
   deployment dry runs.

The checker is intentionally conservative. A warning does not always mean the
service cannot be imported; it means there is a platform decision to make before
turning the Compose service into Kubernetes resources.
