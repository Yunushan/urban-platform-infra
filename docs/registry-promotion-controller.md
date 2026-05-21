# Registry Promotion Controller

## Article 16 Baseline

The registry promotion controller is an optional, public-safe planning layer for
production image promotion. It does not log in to registries, push images, read
image layers, or expose registry credentials. The default profile is
`disabled`, so committed configuration remains safe for labs and public review.

Use it to answer three questions before production rollout:

- Which profile should move images: disabled, lab preload, production registry, or enterprise signed registry.
- Which evidence is required before production: digest pins, vulnerability scan, SBOM, signature or attestation, and promotion record.
- Which Helm override values should be prepared for `global.imageRegistry` and `global.imagePullSecrets`.

## Profiles

| Profile | Purpose | Mutating behavior |
|---|---|---|
| `disabled` | Default public-safe posture | No registry requirement |
| `lab-preload` | Small RKE2 labs or disconnected tests | Uses preload workflow outside registry login |
| `production-registry` | Normal production promotion | Requires private registry and pull secret |
| `enterprise-signed` | Enterprise signed digest promotion | Adds admission verification intent |

## One Command

Generate the controller report and a public-safe Helm override template:

```bash
make registry-promotion-plan \
  REGISTRY_PROMOTION_PROFILE=production-registry \
  REGISTRY_PROMOTION_REGISTRY=private-registry.example.invalid/platform \
  IMPORT_REDACT=true
```

The report is written to `reports/registry-promotion-controller.md`. The
override template is written to `reports/registry-promotion-values.yaml`.

For constrained labs, keep the import path on preload mode:

```bash
make registry-promotion-plan REGISTRY_PROMOTION_PROFILE=lab-preload IMPORT_REDACT=true
make import-auto PROJECT_PATH=/path/to/compose-project MIGRATION_PROFILE=lab MIGRATION_IMAGE_MODE=preload
```

## Production Use

The production registry profile expects:

- a real private registry outside Git,
- `registry-credentials` or another configured image pull secret,
- External Secrets, Vault, CI secrets, or existing login state for credentials,
- digest-pinned image overrides after promotion,
- scan, SBOM, signature or attestation, and promotion record evidence.

The controller only prepares intent and checks. Actual image movement still
happens through `make import-auto`/`make import-migrate` with
`MIGRATION_IMAGE_MODE=registry`, or through an approved external promotion
pipeline.

## Public-Safe Rules

- Do not commit real registry hostnames when they identify private infrastructure.
- Do not commit registry credentials or generated Docker config JSON.
- Keep `imagePromotionController.enabled=false` in committed defaults.
- Commit only sanitized reports and templates; keep real production overrides in private overlays.
