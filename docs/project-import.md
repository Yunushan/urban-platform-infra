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
with `MIGRATION_KUBECONFIG` before applying secrets, reading database target
secrets, or applying manifests. Use it after the dry-run report looks correct
and the operator machine has access to the Compose project, Docker, Kubernetes,
and the RKE2 nodes.

When `MIGRATION_ALLOW_SECRET_MATERIAL=true` is set, `import-auto` treats literal
Compose secret values as operator-approved input, imports them into Kubernetes
Secrets, and records the action in the private action plan. Docker socket mounts
are not carried into Kubernetes by default; services that require
`/var/run/docker.sock` are skipped as Docker-socket integrations and should be
replaced with Kubernetes-native monitoring or another least-privilege approach.
Set `MIGRATION_SKIP_DOCKER_SOCKET_SERVICES=false` only for a deliberate
diagnostic run where you want those services included in image handling.

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
passwordless sudo; if it does not, put the sudo password in a local private file
with mode `0600` and set `MIGRATION_BECOME_PASSWORD_FILE` instead of placing the
password on the `make` command line. Use `MIGRATION_RKE2_VERSION` or
`MIGRATION_CLUSTER_DOMAIN` only when installing onto fresh nodes where those
values cannot be discovered yet. For `import-auto`, if the Kubernetes API is
listening but not ready, the same temporary inventory is used to reconcile the
bootstrap and RKE2 playbooks once, then kubeconfig repair is retried. Set
`MIGRATION_AUTO_REPAIR_CLUSTER=false` to disable that repair pass.

Image migration has three modes:

- `MIGRATION_IMAGE_MODE=registry` builds and pushes application images to a
  private registry. This is the production-friendly mode and is the only mode
  that needs registry credentials.
- `MIGRATION_IMAGE_MODE=preload` builds images, saves them as tar archives, and
  can copy them to RKE2 nodes under `/var/lib/rancher/rke2/agent/images` when
  `MIGRATION_RKE2_NODES` is set. This avoids registry login. By default it also
  verifies the tar archives on each node and imports them into the running RKE2
  containerd socket when that socket is available. The operator machine is used
  only as a staging point; generated import tags, local preload archives, and
  dangling container build cache are cleaned up automatically unless
  `MIGRATION_CLEANUP_OPERATOR_IMAGES=false` is set. Set
  `MIGRATION_PRUNE_OPERATOR_CACHE=false` only when you intentionally want to keep
  dangling Podman/Docker build cache on the operator for debugging. Only archives
  generated in the current run are copied to nodes; stale local archives from
  earlier failed runs are not sent again. Node-side preload transfer uses a
  one-archive staging directory under the RKE2 image directory instead of `/tmp`;
  each archive is imported and removed before the next archive is copied.
- `MIGRATION_IMAGE_MODE=skip` leaves application image movement out of the
  migration run. Use this when keeping the existing Compose deployment running
  temporarily behind external routing.

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
For `import-auto`, set `MIGRATION_TLS_CERT_FILE` and `MIGRATION_TLS_KEY_FILE`
to create the ingress TLS secret from your certificate files; otherwise the
import stage creates a self-signed fallback secret for `MIGRATION_INGRESS_HOST`.

No-registry preload example:

```bash
make import-migrate PROJECT_PATH=/path/to/compose-project \
  MIGRATION_STAGE=images \
  MIGRATION_EXECUTE=true \
  MIGRATION_IMAGE_MODE=preload \
  MIGRATION_RKE2_NODES=node-01,node-02,node-03
```

Available stages are `prepare`, `bundle`, `secrets`, `images`, `databases`,
`manifests`, `validate`, and `all`. Stage-by-stage execution is mainly for
troubleshooting a failed section. For example:

```bash
make import-migrate PROJECT_PATH=/path/to/compose-project \
  MIGRATION_STAGE=databases \
  MIGRATION_EXECUTE=true \
  MIGRATION_ALLOW_SECRET_MATERIAL=true
```

Database dump/restore is performed by the automation when execution is enabled.
The restore step uses the generated private DB target map. For CloudNativePG
targets from the selected Helm values, the map points at the generated app
secret for each database instance, so operators do not have to paste target
passwords into the file. The map can still use a direct DSN when needed:

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
  `nginxinc/nginx-unprivileged:1.30.0` and flags rootful or version-drifted
  nginx images.
- `DB=postgresql` expects the PostgreSQL/CloudNativePG migration path. It flags
  PostgreSQL majors older or newer than the platform default `18`, and fails
  very old majors that do not fit the supported path.
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
5. Translate data stores to the selected operator or managed-service profile.
   For PostgreSQL-family services, verify extensions and perform a dump/restore
   rehearsal against the selected major version.
6. Put private paths, node addresses, passwords, tokens, and TLS material in
   private inventory or secret-management tooling, not in the public repository.
7. Re-run the checker with `IMPORT_STRICT=true`, then proceed to Helm values and
   deployment dry runs.

The checker is intentionally conservative. A warning does not always mean the
service cannot be imported; it means there is a platform decision to make before
turning the Compose service into Kubernetes resources.
