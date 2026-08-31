# Environment Profiles

Environment profiles connect deployment, import, image movement, backup,
observability, edge routing, progressive delivery, scaling policy, network
connectivity, access governance, compliance evidence, incident response, change
management, smoke tests, release runbook gating, cluster upgrade guardrails, disaster recovery, and database migration strictness into one
public-safe decision point.

## One Command Plan

Generate the selected environment plan and values overlay:

```bash
make environment-profile-plan ENV_PROFILE=lab IMPORT_REDACT=true
```

The command writes:

- `reports/environment-profile-plan.md`
- `reports/environment-profile-values.yaml`
- `reports/environment-profile-evidence-bundle.md`

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
  change management planning, lab cutover gates, lab smoke tests, lab disaster recovery
  rehearsal planning, lab release runbook review, lab cluster upgrade guardrails, batched import, and non-strict unavailable database
  handling.
- `staging`: non-production integration. Uses a private registry strategy,
  External Secrets style runtime secret references, production-registry
  promotion planning, lab-audit runtime hardening planning, lab Argo CD
  delivery intent, disabled lab-canary rollout planning, two replicas, ingress
  endpoint checks, production HPA readiness planning, restricted network
  connectivity planning, production RBAC readiness planning, and backup/restore
  rehearsal expectations with staging control-review evidence planning, staging
  incident drill planning, staging change approval planning, staging cutover
  gates, staging smoke tests, staging release runbook review, staging cluster upgrade guardrails, and staging DR rehearsal planning.
- `production`: capacity-planned HA. Requires private registry strategy,
  Vault-backed secret provider profile, enterprise-signed registry promotion,
  production-restricted runtime hardening, production GitOps delivery intent,
  disabled production canary rollout intent, production HPA readiness planning,
  restricted network connectivity planning, OIDC access governance planning,
  production audit-pack evidence planning, production incident on-call planning,
  production CAB change management planning, production cutover gates,
  production smoke-test evidence planning, production release runbook evidence gates,
  production cluster upgrade guardrails,
  production disaster recovery planning, strict database migration, ingress
  endpoint checks, restore drills, observability review, and release evidence.

## Evidence Bundle

Every profile declares an evidence bundle. The generated
`reports/environment-profile-evidence-bundle.md` lists the public reports that
should exist for that profile and the private evidence categories that must
stay in approved operator systems.

For production, the bundle expects release verification, registry or preload
evidence, database migration evidence, edge migration evidence, backup and
restore evidence, change management evidence, disaster recovery evidence,
import preflight/capacity/recovery reports, smoke-test plans, and cutover gate
evidence. Private items such as DNS/TLS ownership, tickets, approver names,
restore evidence, smoke-test endpoint lists, rollback owners, post-cutover
observation owners, release approval indexes, and release owner reviews are represented only as categories.

## Overlay Use

After reviewing the generated overlay, use it with Helm for a lab deployment:

```bash
make deploy-auto HELM_EXTRA_ARGS="-f reports/environment-profile-values.yaml"
```

For production, use the production deployment target and confirm the change
explicitly; `deploy-auto` is intentionally lab-only:

```bash
make deploy DEPLOY_PROFILE=production \
  VALUES=helm/urban-platform-infra/values-production.yaml \
  DEPLOY_PRIVATE_VALUES=/var/lib/urban-platform/private/values-production-private.yaml \
  HELM_EXTRA_ARGS="-f reports/environment-profile-values.yaml" \
  CONFIRM_PROD=true
```

`DEPLOY_PRIVATE_VALUES` is mandatory for production, must exist outside the
repository checkout, and is applied after every public values file. It must
contain the signed release identity and promoted digest-pinned private image
references described in the production evidence runbook. A production
`import-auto` run passes the same variable to its platform deployment.

For imports, keep the Make variables aligned with the selected profile:

```bash
make import-auto PROJECT_PATH=/path/to/compose-project \
  ENV=lab \
  MIGRATION_PROFILE=lab \
  MIGRATION_IMAGE_MODE=preload
```

Production should not be reached by simply changing one variable. Review the
environment profile plan, lab capacity plan, image cache or registry plan,
database migration controller plan, edge migration plan, backup plan,
observability plan, GitOps delivery plan, progressive delivery plan, and
scaling policy plan, network connectivity plan, access governance plan,
compliance evidence plan, incident response plan, change management plan,
smoke-test plan, release runbook plan, cluster upgrade plan, disaster recovery plan, cutover gate plan, environment evidence bundle, and
release evidence first.

The migration target selects its values file from `MIGRATION_PROFILE`, which
follows the inventory environment by default. Use `ENV=lab` for lab imports.
For an intentional lab operation against a production-named inventory, add
`ALLOW_LAB_ON_PROD=true`; otherwise the Makefile fails closed. Override the
values selection with `MIGRATION_VALUES=/path/to/private-or-reviewed-values.yaml`
only when a reviewed custom overlay is required.
