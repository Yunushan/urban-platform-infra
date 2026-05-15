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
