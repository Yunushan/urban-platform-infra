# Operations

## Deploy

```bash
make operator-ready
make install-operators
make deploy
```

For the common one-command readiness and operator flows, start with
[`docs/operator-workflows.md`](operator-workflows.md). It keeps the local
readiness, cluster health, lab deployment, project import, and release evidence
paths in one public-safe place.

The deployment target installs Helm and Helmfile when missing, applies the
templated operator Helmfile, waits for CNPG and ECK CRDs, then installs the
platform chart. The low-resource lab profile keeps Elasticsearch, Kibana,
Grafana, Loki, ClickHouse, Logstash, Prometheus, and OpenTelemetry disabled
unless their deploy flags are explicitly enabled.

Before Helmfile, kubectl, or Helm touches the cluster, `make install-operators`
and `make deploy` run `scripts/tools/ensure-kubeconfig.sh`. That script fetches
the RKE2 kubeconfig from the first server, rewrites the API endpoint to the
configured VIP port, and writes it to `${KUBECONFIG}` or `~/.kube/config`. If
`${KUBECONFIG}` or `~/.kube/config` already exists and its Kubernetes API
`/readyz` endpoint responds, the script uses that kubeconfig as-is instead of
requiring an inventory just to install operator CRDs.

The default operator pins are intentionally current for this stack:
CloudNativePG 1.29+ is required for PostgreSQL 18 defaults, and ECK 3.4+ is
required for Kubernetes 1.34 and Elastic Stack 9.x.
The chart does not render CloudNativePG's deprecated
`spec.monitoring.enablePodMonitor` field by default. Create PodMonitor resources
explicitly when database scraping is required.
For lab clusters or small disks, override all CloudNativePG PVCs with
`databases.storageOverride.size` and, when the cluster does not have a default
StorageClass, `databases.storageOverride.className`.

For environments with separate storage backends, configure optional
hot/warm/cold storage tiers in `storageTiers`. The hot tier can act as the
default StorageClass fallback for stateful chart workloads when their explicit
storage class is empty. Warm and cold tiers are public-safe contracts for
compressed history, backups, import dumps, snapshots, and release evidence; see
[`docs/storage-tiers.md`](storage-tiers.md).
`make install-operators` checks for a StorageClass before installing stateful
workloads. When no StorageClass exists, `INSTALL_LOCAL_PATH_STORAGE=auto`
installs Rancher local-path provisioner as a default lab StorageClass. Set
`INSTALL_LOCAL_PATH_STORAGE=false` when production storage is managed separately.
When the `local-path` StorageClass already exists, `deploy-auto` still
reconciles the provisioner and prepares `LOCAL_PATH_STORAGE_PATH`
(`/opt/local-path-provisioner` by default) on the RKE2 nodes over SSH. This
sets writable permissions and a container-compatible SELinux label so helper
pods do not fail with `mkdir: Permission denied`.

For an import/lab deployment, use the automatic recovery path instead of
manually uninstalling stuck releases or deleting Pending PVCs:

```bash
make environment-profile-plan ENV_PROFILE=lab IMPORT_REDACT=true
make capacity-preflight
make lab-deploy-plan
make deploy-auto \
  HELM_EXTRA_ARGS="-f reports/environment-profile-values.yaml -f reports/lab-deploy-values.yaml" \
  OPERATOR_KUBECONFIG="$OPERATOR_KUBECONFIG" \
  KUBECONFIG="$KUBECONFIG" \
  DEPLOY_INGRESS_HOST="$DEPLOY_INGRESS_HOST" \
  DEPLOY_CLUSTER_VIP="$DEPLOY_CLUSTER_VIP"
```

`deploy-auto` installs local-path storage when needed, recovers a failed or
`uninstalling` `urban-platform-infra` Helm release, removes stale resources from
that release, recreates the lab Kafka/ZooKeeper/Redis StatefulSets when their
storage template must change, and deletes only Pending PVCs by default, even
when the previous Helm release is already `deployed`. It uses one lab replica
and compact local-path storage sizes and classes for PostgreSQL, Kafka,
ZooKeeper, Redis, and any explicitly enabled observability backend. Bound PVCs are preserved unless
`DEPLOY_RECOVER_DELETE_PVCS=true` is set explicitly. It also disables Redis
Sentinel for the one-replica lab profile and skips sanitized placeholder
workloads whose images are still `example-app-*`, avoiding wasted memory and
repeated image pulls until real application images are imported or configured.
`make environment-profile-plan` aligns the lab, staging, or production intent
before deploy/import work starts. It writes
`reports/environment-profile-plan.md` and
`reports/environment-profile-values.yaml`, tying topology, Helm replica/storage
defaults, migration profile, image mode, database strictness, edge routing,
backup, observability, optional capabilities, and release evidence requirements
together in one public-safe report.
`make capacity-preflight` writes `reports/capacity-preflight.md` and fails
before cluster mutation when the selected lab/production assumptions exceed
CPU, memory, pod-count, batch, or evidence guardrails. `make lab-deploy-plan`
writes `reports/lab-deploy-values.yaml` for the first bounded lab wave.
`import-auto` also defaults to `MIGRATION_PROFILE=lab`. That profile writes
`reports/import-migration/lab-profile-values.yaml` and applies small resource
requests/limits to generated imported workloads. Keep this profile for
4 GiB/node labs; switch to `MIGRATION_PROFILE=production` only after capacity,
backup, storage, and database cutover plans are reviewed.
Before running a large image import, run `make image-cache-plan`. It writes
`reports/image-cache-plan.md` with the selected registry or preload strategy,
RKE2 node count, running containerd import behavior, and operator cache cleanup
settings. The report is public-safe and does not list node addresses, image
layers, or registry credentials.
Before production registry mode, run `make registry-promotion-plan`. It writes
`reports/registry-promotion-controller.md` and
`reports/registry-promotion-values.yaml`, confirming registry profile, image
pull secret, digest pins, and promotion evidence before the mutating image stage
or an external promotion pipeline runs.
Before enabling GitOps reconciliation, run `make gitops-delivery-plan`. It
writes `reports/gitops-delivery-plan.md` and
`reports/gitops-delivery-values.yaml`, confirming operator-managed, Argo CD, or
Flux delivery intent, drift posture, protected-branch expectations, and
required preflight checks without printing private repository URLs or values
file names when redaction is enabled.
Before enabling canary or blue-green delivery, run
`make progressive-delivery-plan`. It writes
`reports/progressive-delivery-plan.md` and
`reports/progressive-delivery-values.yaml`, confirming rollout strategy,
controller ownership, traffic provider, SLO analysis, GitOps readiness, and
rollback drill evidence. Keep progressive delivery disabled until the plan is
reviewed and automatic promotion has an explicit owner.
Before enabling HPA, VPA, KEDA, or cluster autoscaler automation, run
`make scaling-policy-plan`. It writes `reports/scaling-policy-plan.md` and
`reports/scaling-policy-values.yaml`, confirming capacity evidence, metrics
source readiness, SLO alert coverage, event-trigger ownership, and load-test
evidence. Keep runtime autoscaling disabled until a private overlay has been
reviewed.
Before tightening egress or enabling Linkerd/Istio, run
`make network-connectivity-plan`. It writes
`reports/network-connectivity-plan.md` and
`reports/network-connectivity-values.yaml`, confirming NetworkPolicy, DNS, TLS,
Kubernetes API egress, external egress contract, and service mesh readiness
without printing private routes or CIDR inventories. Keep mesh and stricter
egress plan-only until health probes and rollback behavior are proven.
Before enabling OIDC/SSO, broad RBAC changes, or tenant namespaces, run
`make access-governance-plan`. It writes
`reports/access-governance-plan.md` and
`reports/access-governance-values.yaml`, confirming service-account token
automount, least-privilege RBAC, identity provider, audit policy, break-glass,
and tenant isolation readiness without printing users, groups, tenants, or
identity provider URLs.
Before assembling compliance evidence or audit packs, run
`make compliance-evidence-plan`. It writes
`reports/compliance-evidence-plan.md` and
`reports/compliance-evidence-values.yaml`, confirming control-map, private
evidence-index, restore drill, access review, incident drill, checksum,
attestation, and retention readiness without exporting private evidence or
claiming certification.
Before enabling production paging or incident-management integrations, run
`make incident-response-plan`. It writes
`reports/incident-response-plan.md` and
`reports/incident-response-values.yaml`, confirming alert route ownership,
escalation rota, pager service, runbook index, service ownership, communication
template, stakeholder map, incident drill, post-incident review, and regulatory
owner readiness without paging anyone or printing private contacts.
Before enforcing production change approvals or maintenance windows, run
`make change-management-plan`. It writes
`reports/change-management-plan.md` and
`reports/change-management-values.yaml`, confirming change-ticket, approval,
risk, impact, freeze-check, stakeholder notice, rollback, smoke-test,
deployment evidence, and post-change review readiness without creating tickets
or printing private approver details.
Before production traffic switch, run `make cutover-gate-plan`. It writes
`reports/cutover-gate-plan.md` and `reports/cutover-gate-values.yaml`,
confirming import preflight, capacity, recovery, release evidence,
registry/preload, backup, database restore, DNS/TLS, smoke-test, rollback,
approval, observation window, and owner handoff readiness without modifying DNS,
approving tickets, switching ingress routes, or running customer-facing tests.
Before claiming disaster recovery or business continuity readiness, run
`make disaster-recovery-plan`. It writes
`reports/disaster-recovery-plan.md` and
`reports/disaster-recovery-values.yaml`, confirming RTO/RPO, dependency map,
criticality map, backup replication, database restore, RKE2 etcd restore,
namespace restore, application smoke test, failover runbook, communications,
manual workaround, supplier ownership, and post-drill review readiness without
printing private recovery sites or drill evidence.
Before running the database stage, run `make database-migration-plan`. It writes
`reports/database-migration-plan.md` with the target-map status, dump directory,
PostgreSQL client fallback image, supported engines, and lab/production
source-skipping behavior without printing DSNs or passwords.
Before applying imported public routes, run `make edge-migration-plan`. It
writes `reports/edge-migration-plan.md` with the selected ingress class, TLS
mode, source allowlist state, HTTP redirect behavior, and backend-Service apply
guard without printing private DNS names, VIPs, or TLS material.
If the API is reachable but `/readyz` reports embedded-etcd readiness failures,
operator kubeconfig repair runs in `auto` mode when migration node addresses are
available. `deploy-auto` and `import-auto` still force that guarded RKE2 repair
pass explicitly.
If the VIP kubeconfig times out after `import-auto`, the kubeconfig helper reuses
the temporary migration inventory and falls back to an SSH tunnel to the RKE2 API.
Before `import-auto` applies secrets, restores databases, or applies manifests,
it runs the import cluster preflight and writes
`reports/import-migration/import-preflight.md`. That gate checks Kubernetes
`/readyz`, node readiness and pressure conditions, StorageClass availability,
ingress DNS/TLS reachability policy, remote RKE2 service health, HAProxy,
Keepalived, and node disk headroom when `MIGRATION_RKE2_NODES` is set. It also
writes `reports/import-migration/import-capacity.md`, which estimates generated
imported workload CPU/memory requests against cluster allocatable capacity and
limits lab imports to a small workload count by default. The same flow writes
`reports/import-migration/import-batches.md` and
`reports/import-migration/import-batches.yaml`; lab mode defaults to
`MIGRATION_IMPORT_BATCH=auto`, so an oversized import runs the first bounded
application batch instead of every generated workload. Resume is enabled by
default. Successful service-secret, image, database, and manifest stages are
recorded in the private `MIGRATION_STATE_FILE` and summarized publicly in
`reports/import-migration/import-resume.md`; reruns skip completed scopes unless
`MIGRATION_FORCE_RERUN=true` is set.
After a failed or interrupted import, run `make import-recovery-plan
IMPORT_REDACT=true` before forcing a rerun. It writes
`reports/import-migration/import-recovery-plan.md` with resume status, operator
cache cleanup guidance, node-side image retention boundaries, database dump
retention guidance, and generated-manifest rollback boundaries.
When the SSH user needs sudo for RKE2 token or kubeconfig discovery,
`deploy-auto` prompts once on the terminal and reuses that password only for the
current run. Set `MIGRATION_BECOME_PASSWORD_PROMPT=false` for non-interactive
runs that must fail instead of prompting.
If one migration node is temporarily SSH-unreachable during automatic RKE2
repair, the generated recovery inventory excludes that node and reconciles the
reachable servers first. A three-node HA repair requires at least two
SSH-reachable servers by default to preserve embedded-etcd quorum. Set
`MIGRATION_SKIP_UNREACHABLE_RKE2_NODES=false` to make an unreachable node fail
the repair immediately, or override
`MIGRATION_REPAIR_MIN_REACHABLE_RKE2_NODES` only for an intentional lab
recovery.
If `/tmp/urban-platform-import-inventory.yml` is not present, pass
`MIGRATION_RKE2_NODES=node-1,node-2,node-3` once so the helper can rebuild that
inventory.
Operator Helmfile sync is retried automatically when the Kubernetes API returns
transient VIP TLS handshake timeouts; each retry refreshes the operator
kubeconfig first. When migration node addresses are available, the operator
kubeconfig prefers direct RKE2 node API endpoints before falling back to the VIP.
Before every Helmfile attempt, the wrapper waits for consecutive successful
`/readyz`, `/version`, and `/openapi/v2` probes so large charts do not start
while the API server is still brownout-prone.
If a previous Helm attempt leaves an operator release in a `pending-*` state, the
wrapper waits for it to finish, rolls it back to the last deployed revision when
needed, and removes a stale pending Helm secret only as a final recovery step.

The operator step uses `helmfile sync`, so the Helm diff plugin is not required
on the operator machine.

## Optional Capabilities

Optional platform capabilities are disabled by default. Enable them only after
capacity, ownership, storage, DNS, TLS, secret references, and rollback plans
are reviewed.

Examples:

```bash
make install-operators DEPLOY_ENABLE_MINIO=true
make install-operators DEPLOY_ENABLE_RABBITMQ=true
make install-operators DEPLOY_ENABLE_KEYCLOAK=true
make install-operators DEPLOY_ENABLE_EMQX=true
make install-operators DEPLOY_ENABLE_NATS=true
make install-operators DEPLOY_ENABLE_VAULT=true
make install-operators DEPLOY_ENABLE_KYVERNO=true
make install-operators DEPLOY_ENABLE_TEMPORAL=true
make install-operators DEPLOY_ENABLE_ARGO_WORKFLOWS=true
```

For small labs, enable only one optional capability at a time. See
[`docs/platform-capabilities.md`](platform-capabilities.md).

## Observe

```bash
make status
make cluster-doctor
make lab-deploy-plan
make observability-plan
make observability-status
```

Use `make cluster-doctor` when RKE2 API, VIP, HAProxy, Keepalived, SSH/sudo,
or kubeconfig health is unclear. It writes a public-safe report to
`reports/cluster-doctor.md`. Use `make cluster-repair` only when you
intentionally want the guarded kubeconfig/RKE2 repair helper to run.

Use `make lab-deploy-plan` before deploying into a constrained lab. It writes a
capacity report and an optional first-wave overlay at
`reports/lab-deploy-values.yaml`. Apply that overlay with
`HELM_EXTRA_ARGS="-f reports/lab-deploy-values.yaml"` only after reviewing the
report.

`make install-operators` installs the required operators and only installs optional observability charts when their flags are enabled. For the 4-core/4 GiB lab profile, those observability services are off by default. Re-enable only what you need, for example with `DEPLOY_ENABLE_PROMETHEUS=true DEPLOY_ENABLE_GRAFANA=true` for metrics dashboards or `DEPLOY_ENABLE_ELASTICSEARCH=true DEPLOY_ENABLE_KIBANA=true DEPLOY_ENABLE_LOGSTASH=true` for Elastic, then enable `monitoring.enabled=true` in a production override file when the Prometheus Operator CRDs are present.

Service objectives live in `config/slo.yaml`. Alert runbooks live in `docs/runbooks.md`. `make observability-plan` produces a public-safe readiness report before any monitoring or logging stack is enabled.

## Upgrade Image Tags

Edit `helm/urban-platform-infra/values.yaml` or use dependency automation to propose changes. Production overrides should use private-registry digest pins after image promotion.

## Backup

Backup support is optional and disabled by default. Generate the public-safe
plan before enabling anything:

```bash
make backup-plan
```

Production backup enablement should include:

- CloudNativePG Barman backups to an object-store cold tier.
- Velero namespace and persistent-volume metadata backups when the operator is
  explicitly installed.
- RKE2 etcd snapshots copied off the nodes.
- Kafka topic backup or MirrorMaker/replication strategy.
- Redis RDB/AOF persistence and backup.
- GitOps repository backup.

See [`docs/backup-restore.md`](backup-restore.md). Keep real bucket names,
secret references, and restore evidence in private operator records.

## Logs

Default lab pipeline: application logs go to stdout/stderr and heavy observability backends are disabled. Production pipelines such as OpenTelemetry Collector -> Logstash -> Elasticsearch -> Kibana, or Prometheus/Grafana for metrics and dashboards, are configured in `config/observability.yaml` and enabled through deploy flags or values overrides.

## Monthly Review

- Review SLO error budget burn from `config/slo.yaml`.
- Review alert volume and remove noisy alerts.
- Review capacity pressure, restart trends, and storage growth.
- Confirm every alert has a current runbook.
- Confirm release evidence exists for deployed chart artifacts.

## Rollback

```bash
helm history urban-platform-infra -n urban-platform
helm rollback urban-platform-infra <REVISION> -n urban-platform
```
