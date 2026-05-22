# Quality Gates

This repository uses layered checks so infrastructure changes fail early, before a cluster is touched.

## Local developer gates

Run these before opening a pull request:

```bash
make operator-ready
make bootstrap-check ENV=prod ENGINE=rke2
make install-cluster-check ENV=prod ENGINE=rke2
make deploy-dry-run
make capacity-preflight
make environment-profile-plan ENV_PROFILE=lab IMPORT_REDACT=true
make policy
make runtime-hardening-plan RUNTIME_HARDENING_PROFILE=lab-audit IMPORT_REDACT=true
make gitops-delivery-plan GITOPS_DELIVERY_PROFILE=lab-argocd IMPORT_REDACT=true
make progressive-delivery-plan PROGRESSIVE_DELIVERY_PROFILE=lab-canary IMPORT_REDACT=true
make scaling-policy-plan SCALING_POLICY_PROFILE=lab-rightsize IMPORT_REDACT=true
make network-connectivity-plan NETWORK_CONNECTIVITY_PROFILE=lab-baseline IMPORT_REDACT=true
make access-governance-plan ACCESS_GOVERNANCE_PROFILE=lab-audit IMPORT_REDACT=true
make compliance-evidence-plan COMPLIANCE_EVIDENCE_PROFILE=lab-evidence IMPORT_REDACT=true
make incident-response-plan INCIDENT_RESPONSE_PROFILE=lab-readiness IMPORT_REDACT=true
make change-management-plan CHANGE_MANAGEMENT_PROFILE=lab-change IMPORT_REDACT=true
make smoke-test-plan SMOKE_TEST_PROFILE=lab-smoke IMPORT_REDACT=true
make cutover-gate-plan CUTOVER_GATES_PROFILE=lab-smoke IMPORT_REDACT=true
make release-runbook-plan RELEASE_RUNBOOK_PROFILE=lab-release IMPORT_REDACT=true
make cluster-upgrade-plan CLUSTER_UPGRADE_PROFILE=lab-upgrade IMPORT_REDACT=true
make disaster-recovery-plan DISASTER_RECOVERY_PROFILE=lab-dr IMPORT_REDACT=true
```

`make operator-ready` is the one-command local readiness gate. It expands to
local setup, local doctor, CI contract validation, private-data audit,
capacity preflight, repository validation, and lint.

For the modern control-node lane, use Python 3.12, 3.13, or 3.14 and install the modern pins:

```bash
pip install -r requirements-ci-modern.txt
make ansible-collections ANSIBLE_COLLECTION_REQUIREMENTS=ansible/requirements-modern.yml
```

The local gates cover:

- YAML style and parse checks for repository configuration.
- CI workflow contract checks for lane pins, action refs, dependency cache keys, and required gate commands.
- Public-safe private-data audits for secret tokens, private IPs, kubeconfigs, decrypted artifacts, and disclosure-prone identifiers.
- Ansible preflight and check-mode dry runs for bootstrap changes.
- Shell script linting for portable helper scripts.
- Repository structure validation and sanitized example-data checks.
- Secret hygiene checks for ignored sensitive directories, plain Kubernetes Secret manifests, and decrypted secret artifacts.
- Release integrity checks for checksum/SBOM generation, GitHub artifact attestations, and non-floating action refs.
- Image governance checks for explicit tags or digests, blocked mutable tags, and approved runtime-image references.
- Observability checks for SLO contract files, runbooks, and PrometheusRule alert coverage.
- Helm linting and manifest rendering.
- Rendered-manifest policy checks.
- Runtime hardening and admission readiness planning.
- Cluster capacity preflight, lab sizing, and first-wave deploy guardrails.
- GitOps delivery and drift-control readiness planning.
- Progressive delivery, rollback drill, and traffic-shift readiness planning.
- Scaling policy, metrics, load-test, and capacity automation readiness planning.
- Network connectivity, egress, DNS/TLS, and service mesh readiness planning.
- Access governance, RBAC, OIDC/SSO, audit, break-glass, and tenant isolation readiness planning.
- Compliance evidence, control mapping, audit-pack, retention, and redacted evidence readiness planning.
- Incident response, escalation, runbook, communication, drill, and post-incident readiness planning.
- Change management, approval, freeze-check, maintenance-window, rollback, smoke-test, and post-change review readiness planning.
- Post-migration smoke-test, Kubernetes rollout, HTTP/TLS, TCP, database, messaging, and private synthetic readiness planning.
- Production cutover, DNS/TLS, smoke-test, rollback, and post-cutover watch readiness planning.
- Release runbook, artifact evidence, change approval, rollback, smoke-test, cutover, and owner-review readiness planning.
- Cluster upgrade, RKE2/Kubernetes version skew, etcd snapshot, add-on compatibility, rollback, and post-upgrade smoke-test readiness planning.
- Environment evidence bundle planning for public report coverage and private evidence categories.
- Disaster recovery, RTO/RPO, dependency mapping, backup replication, restore drill, failover, and business continuity readiness planning.

## CI gates

The GitHub Actions workflow separates concerns into these jobs:

- `static`: yamllint, Ansible syntax checks, and shellcheck.
- `static (ansible-2.20-py312/py313/py314)`: modern Ansible syntax checks through Python 3.14.
- `validate`: CI contract validation, private-data audit, repository structure, YAML parsing, sanitized examples, and workflow-generation checks on Python 3.11 through 3.14.
- `render`: Helm lint, manifest rendering, policy checks, and rendered manifest upload.
- `security`: Trivy filesystem scan.

## Enforcement model

The current baseline is intentionally strict for syntax, rendering, repository hygiene, high-confidence secret/disclosure checks, release evidence, image mutability, and SLO/runbook coverage. Runtime-hardening policies such as mandatory read-only root filesystems and signed image admission start as `runtime-hardening-plan` readiness gates, then become blocking admission controls only after production overrides, digest promotion, writable-path mapping, and policy-engine ownership are ready. GitOps drift enforcement starts as a `gitops-delivery-plan` readiness gate and should become automated only after protected branches, private overlays, signed releases, rollback ownership, and controller access boundaries are reviewed. Progressive delivery starts as a `progressive-delivery-plan` readiness gate and should stay disabled until rollout controller ownership, private SLO analysis, traffic-splitting support, smoke tests, and rollback drills are proven. Scaling policy starts as a `scaling-policy-plan` readiness gate and should stay disabled until capacity reports, workload requests, metrics adapters, SLO alerts, load-test evidence, and autoscaler ownership are proven. Network connectivity starts as a `network-connectivity-plan` readiness gate and should stay plan-only until DNS, TLS, ingress-controller, Kubernetes API egress, external egress, service mesh capacity, and rollback ownership are proven. Access governance starts as an `access-governance-plan` readiness gate and should stay plan-only until RBAC inventory, identity provider ownership, group mappings, audit retention, break-glass review, and tenant isolation contracts are proven. Compliance evidence starts as a `compliance-evidence-plan` readiness gate and should stay plan-only until private evidence indexes, control maps, restore/access/incident evidence, retention rules, and export approvals are proven. Incident response starts as an `incident-response-plan` readiness gate and should stay plan-only until alert routes, escalation rotas, pager ownership, runbook indexes, communication templates, drills, and post-incident reviews are proven. Change management starts as a `change-management-plan` readiness gate and should stay plan-only until tickets, approvals, risk and impact assessments, maintenance windows, freeze checks, rollback plans, smoke tests, deployment evidence, and post-change reviews are proven. Smoke testing starts as a `smoke-test-plan` readiness gate and should stay plan-only until private runner ownership, Kubernetes rollout checks, HTTP/TLS routes, TCP services, database connections, messaging connections, synthetic checks, and owner-reviewed results are proven. Cutover gates start as a `cutover-gate-plan` readiness gate and should stay plan-only until import preflight, capacity, recovery, release evidence, registry/preload evidence, backup, database restore, DNS/TLS, smoke-test, rollback, approvals, and observation ownership are proven. Release runbook gating starts as a `release-runbook-plan` readiness gate and should stay plan-only until release artifacts, attestations, private approval indexes, rollback plans, smoke-test plans, cutover gates, and owner reviews are proven. Cluster upgrade gating starts as a `cluster-upgrade-plan` readiness gate and should stay plan-only until target RKE2 pins, Kubernetes version skew, etcd snapshots, add-on compatibility, maintenance windows, rollback, node health, and post-upgrade smoke tests are proven. Disaster recovery starts as a `disaster-recovery-plan` readiness gate and should stay plan-only until RTO/RPO objectives, dependency maps, backup replication, restore drills, failover runbooks, continuity communications, supplier ownership, and post-drill reviews are proven.
