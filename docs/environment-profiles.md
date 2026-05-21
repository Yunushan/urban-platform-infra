# Environment Profiles

Environment profiles connect deployment, import, image movement, backup,
observability, edge routing, progressive delivery, scaling policy, network
connectivity, access governance, compliance evidence, incident response, change
management, disaster recovery, and database migration strictness into one
public-safe decision point.

## One Command Plan

Generate the selected environment plan and values overlay:

```bash
make environment-profile-plan ENV_PROFILE=lab IMPORT_REDACT=true
```

The command writes:

- `reports/environment-profile-plan.md`
- `reports/environment-profile-values.yaml`

The report is public-safe. It does not print private inventories, node
addresses, DNS names, TLS material, registry credentials, or customer
identifiers.

## Profiles

`config/environment-profiles.yaml` defines three baseline profiles:

- `lab`: constrained validation and migration rehearsal. Uses preload image
  mode, one replica, disabled backups, disabled heavy observability, disabled
  optional capabilities, direct guarded lab secret import, lab-preload registry
  promotion planning, lab-audit runtime hardening planning, operator-managed
  delivery, disabled lab-canary rollout planning, disabled lab right-sizing
  planning, lab network connectivity planning, lab access governance planning,
  lab compliance evidence summaries, lab incident readiness planning, lab
  change management planning, lab disaster recovery rehearsal planning, batched
  import, and non-strict unavailable database handling.
- `staging`: non-production integration. Uses a private registry strategy,
  External Secrets style runtime secret references, production-registry
  promotion planning, lab-audit runtime hardening planning, lab Argo CD
  delivery intent, disabled lab-canary rollout planning, two replicas, ingress
  endpoint checks, production HPA readiness planning, restricted network
  connectivity planning, production RBAC readiness planning, and backup/restore
  rehearsal expectations with staging control-review evidence planning, staging
  incident drill planning, staging change approval planning, and staging DR
  rehearsal planning.
- `production`: capacity-planned HA. Requires private registry strategy,
  Vault-backed secret provider profile, enterprise-signed registry promotion,
  production-restricted runtime hardening, production GitOps delivery intent,
  disabled production canary rollout intent, production HPA readiness planning,
  restricted network connectivity planning, OIDC access governance planning,
  production audit-pack evidence planning, production incident on-call planning,
  production CAB change management planning, production disaster recovery
  planning, strict database migration, ingress endpoint checks, restore drills,
  observability review, and release evidence.

## Overlay Use

After reviewing the generated overlay, use it with Helm:

```bash
make deploy-auto HELM_EXTRA_ARGS="-f reports/environment-profile-values.yaml"
```

For imports, keep the Make variables aligned with the selected profile:

```bash
make import-auto PROJECT_PATH=/path/to/compose-project \
  MIGRATION_PROFILE=lab \
  MIGRATION_IMAGE_MODE=preload
```

Production should not be reached by simply changing one variable. Review the
environment profile plan, lab capacity plan, image cache or registry plan,
database migration controller plan, edge migration plan, backup plan,
observability plan, GitOps delivery plan, progressive delivery plan, and
scaling policy plan, network connectivity plan, access governance plan,
compliance evidence plan, incident response plan, change management plan, and
disaster recovery plan, and release evidence first.
