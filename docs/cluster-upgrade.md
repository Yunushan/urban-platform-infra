# Cluster Upgrade And Version-Skew Guardrails

Article 12 adds a public-safe cluster upgrade planning gate. It helps operators
review Kubernetes and RKE2 version skew, target version pins, etcd snapshot
readiness, add-on compatibility, rollback, maintenance-window, and post-upgrade
smoke-test evidence before any cluster version changes.

## Plan Command

Generate the production upgrade plan:

```bash
make cluster-upgrade-plan CLUSTER_UPGRADE_PROFILE=production-upgrade IMPORT_REDACT=true
```

The command writes:

- `reports/cluster-upgrade-plan.md`
- `reports/cluster-upgrade-values.yaml`

Use `CLUSTER_UPGRADE_PROFILE=lab-upgrade` for lab rehearsals and
`CLUSTER_UPGRADE_PROFILE=staging-upgrade` before non-production upgrades.

## Version Inputs

The planner accepts explicit version inputs when the private inventory or
cluster doctor report has already discovered them:

```bash
make cluster-upgrade-plan \
  CLUSTER_UPGRADE_PROFILE=production-upgrade \
  CLUSTER_UPGRADE_CURRENT_KUBERNETES=vX.Y.Z \
  CLUSTER_UPGRADE_TARGET_KUBERNETES=vX.Y.Z \
  CLUSTER_UPGRADE_CURRENT_RKE2=vX.Y.Z+rke2rN \
  CLUSTER_UPGRADE_TARGET_RKE2=vX.Y.Z+rke2rN \
  IMPORT_REDACT=true
```

Do not commit real node names, private API endpoints, kubeconfigs, maintenance
tickets, approver names, or production inventory snippets.

## Guardrail Scope

The cluster upgrade gate expects private evidence for:

- cluster doctor or equivalent health report
- target RKE2 version pin
- supported Kubernetes version skew
- RKE2 etcd snapshot and restore readiness
- backup and restore evidence
- maintenance window or freeze exception
- capacity headroom and node health evidence
- add-on compatibility for cert-manager, CloudNativePG, ECK, ingress, CNI, CSI, and policy controllers
- rollback plan and post-upgrade smoke-test plan

## Disabled By Default

The generated Helm overlay keeps `clusterUpgrade.enabled` and
`clusterUpgrade.orchestration.enabled` set to `false`. The command does not
drain nodes, restart RKE2, patch inventories, upgrade Kubernetes, mutate
HAProxy/Keepalived, or switch traffic.

Production upgrades should stay private and operator-approved until upgrade
owners review release notes, version skew, backups, add-on compatibility,
rollback, and smoke-test evidence.
