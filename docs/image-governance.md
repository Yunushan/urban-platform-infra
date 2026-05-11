# Image Governance and Runtime Version Hygiene

This repository is an infrastructure deployment project. It must not carry private application source, private image contents, customer data, or disclosure-sensitive runtime metadata. Images are represented as deploy-time references only.

## Article 7 Baseline

Image governance has four rules:

1. Do not use mutable image tags such as `latest`, `latest-pg16`, or `*-latest`.
2. Use explicit version tags in examples and development defaults.
3. Use digest pins in production override files after images are promoted into an approved private registry.
4. Keep image movement scripts pointed at the sanitized image catalog and never at private credentials or local kubeconfigs.

The default placeholder application images now use the sanitized `0.1.0` tag. Third-party runtime images are pinned in `config/image-policy.yaml`, `config/services.catalog.yaml`, Docker Compose, and Helm values.

## Production Promotion

Production image flow:

```text
upstream image -> vulnerability scan -> private registry mirror -> digest pin -> deployment override
```

Recommended production override style:

```yaml
global:
  imageRegistry: registry.example.com/city-intersection
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
```

This validates:

- Helm image objects have an explicit tag or digest.
- Mutable tags are blocked.
- Placeholder app images stay on sanitized `0.1.0` until replaced by private images.
- Runtime images are approved in `config/image-policy.yaml`.
- Docker Compose and config catalogs do not drift from the policy.

## Current Pinned Runtime Images

| Layer | Image |
|---|---|
| Kafka | `confluentinc/cp-kafka:7.5.0` |
| ZooKeeper | `confluentinc/cp-zookeeper:7.5.0` |
| Kafka UI | `provectuslabs/kafka-ui:v0.7.2` |
| TimescaleDB | `timescale/timescaledb:2.26.4-pg16` |
| Zabbix agent | `zabbix/zabbix-agent2:ubuntu-7.0.25` |

## References

- Kubernetes image names, tags, and digests: https://kubernetes.io/docs/concepts/containers/images/
- Kubernetes admission controllers: https://kubernetes.io/docs/reference/access-authn-authz/admission-controllers/
- Dockerfile best practices: https://docs.docker.com/develop/develop-images/dockerfile_best-practices/
- Sigstore Cosign verification: https://docs.sigstore.dev/cosign/verifying/verify/
