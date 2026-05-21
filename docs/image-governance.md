# Image Governance and Runtime Version Hygiene

This repository is an infrastructure deployment project. It must not carry private application source, private image contents, customer data, or disclosure-sensitive runtime metadata. Images are represented as deploy-time references only.

## Article 7 Baseline

Image governance has four rules:

1. Do not use mutable image tags such as `latest`, `latest-pg16`, `latest-pg17`, `latest-pg18`, or `*-latest`.
2. Use explicit version tags in examples and development defaults.
3. Use digest pins in production override files after images are promoted into an approved private registry.
4. Keep image movement scripts pointed at the sanitized image catalog and never at private credentials or local kubeconfigs.

The default placeholder application images now use the sanitized `0.1.0` tag. Third-party runtime images are pinned in `config/image-policy.yaml`, `config/services.catalog.yaml`, Docker Compose, and Helm values.

The local Article 7 planner is `scripts/images/promotion_plan.py`. It generates
`reports/image-promotion-plan.md`, a public-safe checklist of image references
that still need private-registry promotion, digest pins, vulnerability scan
evidence, SBOM evidence, and signature or attestation evidence before
production use.

## Production Promotion

Production image flow:

```text
upstream image -> vulnerability scan -> private registry mirror -> digest pin -> deployment override
```

Recommended production override style:

```yaml
global:
  imageRegistry: registry.example.invalid/platform
  imagePullSecrets:
    - registry-credentials

workloads:
  app-01:
    image:
      repository: app-01
      tag: 0.1.0
      digest: sha256:REPLACE_WITH_PROMOTED_DIGEST
```

When `digest` is present, the chart renders `repository@sha256:...` and ignores tag mutability at pull time. Keep the tag as human-readable release context, but treat the digest as the production identity.

## Checks

Run:

```bash
make image-policy
make image-promotion-plan IMAGE_PROMOTION_REGISTRY=private-registry.example.invalid/platform
```

This validates:

- Helm image objects have an explicit tag or digest.
- Mutable tags are blocked.
- Placeholder app images stay on sanitized `0.1.0` until replaced by private images.
- Runtime images are approved in `config/image-policy.yaml`.
- Docker Compose and config catalogs do not drift from the policy.

The promotion plan is report-only. It does not log in to a registry, push
images, pull image layers, read kubeconfigs, or inspect private inventories.

## Article 16 Registry Promotion Controller

The optional registry promotion controller extends the Article 7 report with a
profile-driven production readiness contract. Its config is
`config/registry-promotion.yaml`, its planner is
`scripts/images/registry_promotion_controller.py`, and its default profile is
`disabled`.

Run:

```bash
make registry-promotion-plan \
  REGISTRY_PROMOTION_PROFILE=production-registry \
  REGISTRY_PROMOTION_REGISTRY=private-registry.example.invalid/platform \
  IMPORT_REDACT=true
```

This writes `reports/registry-promotion-controller.md` and
`reports/registry-promotion-values.yaml`. The controller still does not log in,
push, pull, or inspect private layers. It prepares the private-registry intent,
image pull secret contract, digest-pin requirement, and evidence checklist so
`make import-auto` or an external CI promotion pipeline can perform the actual
image movement.

Use `REGISTRY_PROMOTION_PROFILE=lab-preload` for small RKE2 labs where registry
login is intentionally avoided.

## Current Pinned Runtime Images

| Layer | Image |
|---|---|
| Kafka | `confluentinc/cp-kafka:7.9.6` |
| ZooKeeper | `confluentinc/cp-zookeeper:7.9.6` |
| Kafka UI | `provectuslabs/kafka-ui:v0.7.2` |
| TimescaleDB | `timescale/timescaledb:2.26.4-pg18` |
| Zabbix agent | `zabbix/zabbix-agent2:ubuntu-7.4.10` |

Kafka remains on the latest ZooKeeper-compatible Confluent Platform 7.9.x line. Moving to Confluent Platform 8.x requires a KRaft migration and removal of the ZooKeeper deployment from the chart and compose profiles.

The TimescaleDB tag does not start with a PostgreSQL major version, so the Helm
chart declares a CloudNativePG `ImageCatalog` entry with `major: 18` and has the
TimescaleDB `Cluster` reference that catalog. The image is based on the Alpine
variant of the official Postgres image, so the TimescaleDB cluster overrides the
global CNPG UID/GID defaults and runs PostgreSQL as UID/GID `70`.

## References

- Kubernetes image names, tags, and digests: https://kubernetes.io/docs/concepts/containers/images/
- Kubernetes admission controllers: https://kubernetes.io/docs/reference/access-authn-authz/admission-controllers/
- Dockerfile best practices: https://docs.docker.com/develop/develop-images/dockerfile_best-practices/
- Sigstore Cosign verification: https://docs.sigstore.dev/cosign/verifying/verify/
