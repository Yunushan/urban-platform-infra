# Runtime Hardening And Admission Policy

## Article 17 Baseline

Runtime hardening is an optional production-readiness layer. It keeps the
committed chart compatible with lab imports while giving operators a clear path
to enforce restricted Pod Security, immutable images, and signed-image
admission.

The default profile is `disabled`. The first real step should usually be
`lab-audit`, which keeps Pod Security Admission at `baseline` enforcement while
auditing and warning on `restricted` gaps.

## Profiles

| Profile | Purpose | Policy engine | Enforcement |
|---|---|---|---|
| `disabled` | Public-safe defaults and documentation | none | audit only |
| `lab-audit` | Lab and import rehearsal | native Pod Security Admission | baseline enforce, restricted warn/audit |
| `production-restricted` | Production runtime baseline | Kyverno | restricted and digest image gates |
| `enterprise-signed` | Regulated production | Kyverno | restricted plus signed digest admission |

## One Command

Generate a public-safe plan and Helm override template:

```bash
make runtime-hardening-plan \
  RUNTIME_HARDENING_PROFILE=production-restricted \
  IMPORT_REDACT=true
```

The command writes:

- `reports/runtime-hardening-plan.md`
- `reports/runtime-hardening-values.yaml`

The planner does not install Kyverno, mutate a cluster, read image layers, or
validate private signatures. It checks committed chart intent and produces a
safe overlay template for private review.

## Production Path

1. Run `lab-audit` and fix warnings from rendered manifests.
2. Promote images by digest through the registry promotion controller.
3. Map writable paths to `emptyDir`, PVCs, or application-owned directories.
4. Enable `production-restricted` in a private override.
5. Add Kyverno or another admission engine after capacity and ownership are clear.
6. Move to `enterprise-signed` only after signature keys, identity, and break-glass procedures are documented.

## Controls

The hardening plan covers:

- Pod Security Admission label target.
- Host namespace denial.
- dedicated service accounts and disabled automount.
- `runAsNonRoot`.
- `RuntimeDefault` seccomp.
- dropped Linux capabilities.
- disabled privilege escalation.
- read-only root filesystem readiness.
- digest-pinned image readiness.
- signed-image admission readiness.

## Public-Safe Rules

- Do not commit signing keys, registry secrets, or private certificate chains.
- Do not enforce signed-image admission until private registry promotion is stable.
- Keep `runtimeHardening.enabled=false` in committed defaults.
- Use private overlays for real admission policy engine configuration.
