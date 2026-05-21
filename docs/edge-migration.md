# Ingress And Edge Migration

This is the public-safe control plane for moving Compose edge behavior into the
platform ingress model. It avoids exposing private DNS names, VIPs, node
addresses, TLS keys, certificate contents, or customer route names.

## One Command Plan

Generate the edge migration plan before applying imported routes:

```bash
make edge-migration-plan IMPORT_REDACT=true MIGRATION_INGRESS_HOST=app.example.invalid
```

The plan writes `reports/edge-migration-plan.md`. It summarizes the selected
ingress class, webserver provider, TLS mode, source allowlist state, HTTP
redirect behavior, backend-Service apply guard, and route conversion rules.

## Traefik Default

RKE2-bundled Traefik is the default public ingress. Compose services that bind
host ports `80` or `443` should not keep host-port semantics in Kubernetes.
They should become ClusterIP Services plus Ingress routes.

Compose nginx edge gateways should move external routing to Traefik Ingress.
Keep nginx only as an internal backend when it still serves static files or
reverse-proxy rules that have not yet been absorbed by application services.

Compose Traefik services should not be imported as a second public edge
controller when RKE2 bundled Traefik is selected.

## TLS Modes

The chart supports these TLS paths:

- existing Kubernetes TLS secret
- certificate and key files passed to import automation
- cert-manager issuer
- External Secrets mapping for TLS material
- self-signed lab fallback

Production should use an existing secret, cert-manager production issuer, or
External Secrets. Self-signed TLS is acceptable only for lab and migration
rehearsals.

## Apply Guard

The import stage writes generated Ingress candidates to
`reports/import-migration/manifests/traefik-ingress-candidates.yaml`. When
execution is enabled, it applies only candidates whose backend Kubernetes
Service already exists in the target namespace. This avoids broken routes during
partial or batched imports.

## Source Allowlist

Use `DEPLOY_ALLOWED_CIDRS` or `ingress.sourceAllowList` for public routes that
should be restricted. With Traefik, the chart renders middleware references for
websecure and redirect routes. Keep private CIDR values out of Git.

## Useful Commands

```bash
make edge-migration-plan IMPORT_REDACT=true
make import-migrate PROJECT_PATH=/path/to/compose-project MIGRATION_STAGE=manifests MIGRATION_EXECUTE=true
make deploy-auto DEPLOY_INGRESS_HOST=app.example.invalid DEPLOY_ALLOWED_CIDRS="203.0.113.0/24"
```
