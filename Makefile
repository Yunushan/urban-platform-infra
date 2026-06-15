SHELL := /usr/bin/env bash
PROJECT ?= urban-platform-infra
ENV ?= prod
ENGINE ?= rke2
INGRESS ?= traefik
WEB ?= nginx
DB ?= postgresql
OBS ?= disabled
NAMESPACE ?= urban-platform
VALUES ?= helm/urban-platform-infra/values.yaml
TOPOLOGY ?= three-node-ha
TOPOLOGY_VALUES ?= helm/urban-platform-infra/topologies/$(TOPOLOGY).yaml
INVENTORY ?= inventories/$(ENV)/hosts.yml
ANSIBLE_CONFIG ?= ansible/ansible.cfg
ANSIBLE_ARGS ?=
ANSIBLE_DIFF ?= --diff
VENV ?= .venv
VENV_POSIX_BIN := $(VENV)/bin
VENV_WINDOWS_BIN := $(VENV)/Scripts
VENV_POSIX_PYTHON := $(firstword $(wildcard $(VENV_POSIX_BIN)/python3) $(wildcard $(VENV_POSIX_BIN)/python))
VENV_WINDOWS_PYTHON := $(wildcard $(VENV_WINDOWS_BIN)/python.exe)
VENV_PYTHON := $(firstword $(VENV_POSIX_PYTHON) $(VENV_WINDOWS_PYTHON))
VENV_BIN := $(if $(VENV_POSIX_PYTHON),$(VENV_POSIX_BIN),$(if $(VENV_WINDOWS_PYTHON),$(VENV_WINDOWS_BIN),$(VENV_POSIX_BIN)))
SYSTEM_PYTHON := $(shell command -v python3 2>/dev/null || command -v python 2>/dev/null || printf python3)
PYTHON ?= $(if $(VENV_PYTHON),$(VENV_PYTHON),$(SYSTEM_PYTHON))
PIP ?= $(PYTHON) -m pip
VENV_ANSIBLE_PLAYBOOK := $(firstword $(wildcard $(VENV_BIN)/ansible-playbook) $(wildcard $(VENV_BIN)/ansible-playbook.exe))
VENV_ANSIBLE_GALAXY := $(firstword $(wildcard $(VENV_BIN)/ansible-galaxy) $(wildcard $(VENV_BIN)/ansible-galaxy.exe))
VENV_YAMLLINT := $(firstword $(wildcard $(VENV_BIN)/yamllint) $(wildcard $(VENV_BIN)/yamllint.exe))
ANSIBLE_PLAYBOOK ?= $(if $(VENV_ANSIBLE_PLAYBOOK),$(VENV_ANSIBLE_PLAYBOOK),ansible-playbook)
ANSIBLE_GALAXY ?= $(if $(VENV_ANSIBLE_GALAXY),$(VENV_ANSIBLE_GALAXY),ansible-galaxy)
YAMLLINT ?= $(if $(VENV_YAMLLINT),$(VENV_YAMLLINT),yamllint)
SHELLCHECK ?= shellcheck
ANSIBLE_COLLECTION_REQUIREMENTS ?= ansible/requirements.yml
ANSIBLE_COLLECTIONS_STAMP ?= .ansible/collections/.$(subst /,_,$(ANSIBLE_COLLECTION_REQUIREMENTS)).stamp
PYTHON_DEPS_STAMP ?= .ansible/.python-deps.stamp
LOCAL_SETUP_SCRIPT ?= scripts/tools/setup_local.py
LOCAL_DOCTOR_SCRIPT ?= scripts/tools/doctor_local.py
LOCAL_DOCTOR_REPORT ?= reports/local-doctor.md
CI_CONTRACT_SCRIPT ?= scripts/tools/validate_ci_contract.py
CI_CONTRACT_REPORT ?= reports/ci-contract.md
PRIVATE_DATA_AUDIT_SCRIPT ?= scripts/tools/private_data_audit.py
PRIVATE_DATA_AUDIT_REPORT ?= reports/private-data-audit.md
CONFIRM_PROD ?= false
HELM ?= helm
HELM_INSTALL_SCRIPT ?= scripts/tools/install-helm.sh
HELM_RECOVERY_SCRIPT ?= scripts/tools/recover-helm-release.sh
HELM_TIMEOUT ?= 10m
HELM_DEPLOY_RETRIES ?= 3
HELM_DEPLOY_RETRY_DELAY ?= 20
HELM_EXTRA_ARGS ?=
HELMFILE ?= helmfile
HELMFILE_CONFIG ?= deploy/helmfile.yaml.gotmpl
HELMFILE_INSTALL_SCRIPT ?= scripts/tools/install-helmfile.sh
HELMFILE_SYNC_SCRIPT ?= scripts/tools/helmfile-sync-retry.sh
STRIMZI_INSTALL_SCRIPT ?= scripts/tools/install-strimzi.sh
RKE2_IMAGE_PRELOAD_SCRIPT ?= scripts/tools/preload-rke2-images.sh
HELMFILE_SYNC_RETRIES ?= 4
HELMFILE_SYNC_RETRY_DELAY ?= 20
HELMFILE_SYNC_ATTEMPT_TIMEOUT ?= 240
SKIP_HELMFILE_SYNC ?= auto
LOCAL_PATH_INSTALL_SCRIPT ?= scripts/tools/install-local-path-storage.sh
INSTALL_LOCAL_PATH_STORAGE ?= auto
LOCAL_PATH_PROVISIONER_VERSION ?= v0.0.35
LOCAL_PATH_STORAGE_CLASS ?= local-path
LOCAL_PATH_STORAGE_DEFAULT ?= true
LOCAL_PATH_STORAGE_PATH ?= /opt/local-path-provisioner
LOCAL_PATH_PREPARE_HOST_PATHS ?= auto
OPERATOR_CRD_TIMEOUT ?= 180s
OPERATOR_KUBECONFIG ?= $(if $(KUBECONFIG),$(KUBECONFIG),$(HOME)/.kube/config)
KUBECONFIG_SCRIPT ?= scripts/tools/ensure-kubeconfig.sh
DEPLOY_RECOVER_FAILED_RELEASE ?= false
DEPLOY_RECOVER_STALE_RESOURCES ?= true
DEPLOY_RECOVER_PENDING_PVCS ?= true
DEPLOY_RECOVER_DELETE_PVCS ?= false
DEPLOY_RECOVER_STATEFULSETS ?= false
DEPLOY_RECOVER_CNPG_INITDB ?= false
DEPLOY_LAB_STORAGE ?= true
DEPLOY_LAB_REPLICA_OVERRIDE ?= 1
DEPLOY_LAB_AUTOSCALING ?= false
DEPLOY_LAB_TOPOLOGY_SPREAD ?= false
DEPLOY_SKIP_PLACEHOLDER_WORKLOADS ?= true
DEPLOY_ROOT_WORKLOAD ?= app-27
DEPLOY_ROOT_IMAGE_REPOSITORY ?=
DEPLOY_ROOT_IMAGE_TAG ?=
DEPLOY_ROOT_CONTAINER_PORT ?=
DEPLOY_ROOT_SERVICE_PORT ?=
DEPLOY_ROOT_PROBE_PORT ?=
DEPLOY_ROOT_INGRESS_ENABLED ?= true
DEPLOY_ROOT_INGRESS_PATH ?= /
DEPLOY_ALLOWED_CIDRS ?=
DEPLOY_CONFIGURE_EDGE_PORTS ?= true
DEPLOY_ENABLE_ECK ?= true
DEPLOY_ENABLE_PROMETHEUS ?= false
DEPLOY_ENABLE_GRAFANA ?= false
DEPLOY_ENABLE_OPENTELEMETRY ?= false
DEPLOY_ENABLE_ELASTICSEARCH ?= false
DEPLOY_ENABLE_KIBANA ?= false
DEPLOY_ENABLE_LOGSTASH ?= false
DEPLOY_ENABLE_LOKI ?= false
DEPLOY_ENABLE_CLICKHOUSE ?= false
DEPLOY_ENABLE_VELERO ?= false
DEPLOY_ENABLE_MINIO ?= false
DEPLOY_ENABLE_RABBITMQ ?= false
DEPLOY_ENABLE_KEYCLOAK ?= false
DEPLOY_ENABLE_EMQX ?= false
DEPLOY_ENABLE_NATS ?= false
DEPLOY_ENABLE_STRIMZI ?= false
STRIMZI_OPERATOR_CHART_VERSION ?= 1.0.0
STRIMZI_OPERATOR_TIMEOUT ?= 10m
STRIMZI_WATCH_NAMESPACES ?= $(NAMESPACE)
STRIMZI_WATCH_ANY_NAMESPACE ?= false
STRIMZI_PRELOAD_IMAGES ?= auto
STRIMZI_KAFKA_VERSION ?= 4.2.0
DEPLOY_ENABLE_VAULT ?= false
DEPLOY_ENABLE_KYVERNO ?= false
DEPLOY_ENABLE_TEMPORAL ?= false
DEPLOY_ENABLE_ARGO_WORKFLOWS ?= false
DEPLOY_ENABLE_LINKERD ?= false
DEPLOY_ENABLE_ISTIO ?= false
VELERO_PROVIDER ?= aws
VELERO_BUCKET ?=
VELERO_PREFIX ?= urban-platform
VELERO_REGION ?= minio
VELERO_S3_URL ?=
VELERO_S3_FORCE_PATH_STYLE ?= true
VELERO_USE_SECRET ?= false
VELERO_EXISTING_SECRET ?=
VELERO_SNAPSHOTS_ENABLED ?= false
VELERO_NODE_AGENT_ENABLED ?= false
DEPLOY_EDGE_OBSERVABILITY_PORTS ?= false
DEPLOY_OBSERVABILITY_SERVICE_TYPE ?= NodePort
DEPLOY_KIBANA_NODE_PORT ?= 30561
DEPLOY_ELASTICSEARCH_NODE_PORT ?= 30920
DEPLOY_GRAFANA_NODE_PORT ?= 30300
DEPLOY_LOKI_NODE_PORT ?= 30310
DEPLOY_CLICKHOUSE_HTTP_NODE_PORT ?= 30812
DEPLOY_CLICKHOUSE_TCP_NODE_PORT ?= 30900
DEPLOY_DATABASE_STORAGE_SIZE ?= 1Gi
DEPLOY_DATABASE_STORAGE_CLASS ?= $(LOCAL_PATH_STORAGE_CLASS)
DEPLOY_ELASTICSEARCH_STORAGE ?= 2Gi
DEPLOY_KAFKA_STORAGE ?= 2Gi
DEPLOY_ZOOKEEPER_STORAGE ?= 1Gi
DEPLOY_REDIS_STORAGE ?= 1Gi
DEPLOY_REDIS_SENTINEL ?= false
DEPLOY_INGRESS_HOST ?= $(MIGRATION_INGRESS_HOST)
DEPLOY_CLUSTER_DOMAIN ?= $(if $(MIGRATION_CLUSTER_DOMAIN),$(MIGRATION_CLUSTER_DOMAIN),$(DEPLOY_INGRESS_HOST))
DEPLOY_CLUSTER_VIP ?= $(MIGRATION_CLUSTER_VIP)
DEPLOY_TLS_SECRET_NAME ?=
DEPLOY_TLS_CREATE_SECRET ?=
DEPLOY_NAMESPACE_RESOURCE_QUOTA ?= true
PROJECT_PATH ?=
IMPORT_REPORT ?=
IMPORT_STRICT ?= false
IMPORT_REDACT ?= false
MIGRATION_OUTPUT ?= reports/import-migration
MIGRATION_EXECUTE ?= false
MIGRATION_ALLOW_SECRET_MATERIAL ?= false
MIGRATION_STAGE ?= $(if $(filter true,$(MIGRATION_EXECUTE)),all,bundle)
MIGRATION_AUTO_PREPARE ?= true
MIGRATION_PRIVATE_DIR ?= /var/lib/urban-platform/private
MIGRATION_FALLBACK_INVENTORY ?= /tmp/urban-platform-import-inventory.yml
MIGRATION_KUBECONFIG ?= $(OPERATOR_KUBECONFIG)
MIGRATION_CLUSTER_VIP ?=
MIGRATION_KUBERNETES_API_VIP_PORT ?=
MIGRATION_CLUSTER_DOMAIN ?=
MIGRATION_INGRESS_HOST ?= $(MIGRATION_CLUSTER_DOMAIN)
MIGRATION_TLS_MODE ?= auto
MIGRATION_TLS_CERT_FILE ?=
MIGRATION_TLS_KEY_FILE ?=
MIGRATION_TLS_EXTRA_HOSTS ?=
MIGRATION_TLS_PFX_FILE ?=
MIGRATION_TLS_PFX_PASSWORD_FILE ?=
MIGRATION_TLS_DURATION_DAYS ?= 0
MIGRATION_TLS_LE_EMAIL ?=
MIGRATION_TLS_LE_SERVER ?= https://acme-v02.api.letsencrypt.org/directory
MIGRATION_TLS_LE_ISSUER_NAME ?= urban-platform-letsencrypt
MIGRATION_TLS_LE_ISSUER_KIND ?= ClusterIssuer
MIGRATION_TLS_LE_PRIVATE_KEY_SECRET ?= urban-platform-letsencrypt-account
MIGRATION_TLS_LE_CREATE_ISSUER ?= true
MIGRATION_PROFILE ?= lab
MIGRATION_IMPORT_SECURITY_CONTEXT ?= $(if $(filter production,$(MIGRATION_PROFILE)),restricted,compat)
MIGRATION_IMPORT_PROBE_MODE ?= auto
MIGRATION_LAB_WORKLOAD_CPU_REQUEST ?= 25m
MIGRATION_LAB_WORKLOAD_MEMORY_REQUEST ?= 64Mi
MIGRATION_LAB_WORKLOAD_CPU_LIMIT ?= 250m
MIGRATION_LAB_WORKLOAD_MEMORY_LIMIT ?= 256Mi
MIGRATION_PREFLIGHT_MIN_NODE_MEMORY ?= 3500Mi
MIGRATION_PREFLIGHT_MIN_NODE_DISK_FREE ?= 2048Mi
MIGRATION_PREFLIGHT_MAX_IMPORTED_WORKLOADS ?= $(if $(filter production,$(MIGRATION_PROFILE)),0,40)
MIGRATION_PREFLIGHT_CAPACITY_UTILIZATION_LIMIT ?= $(if $(filter production,$(MIGRATION_PROFILE)),0.85,0.70)
MIGRATION_PREFLIGHT_REQUIRE_INGRESS_ENDPOINT ?= $(if $(filter production,$(MIGRATION_PROFILE)),true,false)
MIGRATION_BATCH_SIZE ?= $(if $(filter production,$(MIGRATION_PROFILE)),0,$(MIGRATION_PREFLIGHT_MAX_IMPORTED_WORKLOADS))
MIGRATION_IMPORT_BATCH ?= $(if $(filter production,$(MIGRATION_PROFILE)),all,auto)
MIGRATION_SERVICE_FILTER ?=
MIGRATION_RUNTIME_VALIDATION_TIMEOUT ?= $(if $(filter production,$(MIGRATION_PROFILE)),900,600)
MIGRATION_RUNTIME_VALIDATION_INTERVAL ?= 10
MIGRATION_KAFKA_BOOTSTRAP_SERVERS ?= kafka:9092
MIGRATION_STATE_FILE ?= $(MIGRATION_PRIVATE_DIR)/migration-state.yaml
MIGRATION_RESUME ?= true
MIGRATION_FORCE_RERUN ?= false
MIGRATION_RKE2_VERSION ?=
MIGRATION_AUTO_REPAIR_CLUSTER ?= auto
MIGRATION_KEEPALIVED_AUTH_PASS ?=
MIGRATION_KEEPALIVED_INTERFACE ?=
MIGRATION_IMAGE_MODE ?= $(if $(filter lab,$(MIGRATION_PROFILE)),preload,registry)
MIGRATION_IMAGE_OUTPUT_DIR ?= $(MIGRATION_PRIVATE_DIR)/images
MIGRATION_RKE2_NODES ?=
MIGRATION_RKE2_IMAGE_DIR ?= /var/lib/rancher/rke2/agent/images
MIGRATION_RKE2_IMPORT_IMAGES ?= true
MIGRATION_CLEANUP_OPERATOR_IMAGES ?= true
MIGRATION_PRUNE_OPERATOR_CACHE ?= true
MIGRATION_CLEANUP_NODE_IMPORT_IMAGES ?= true
MIGRATION_CLEANUP_NODE_CRI_IMAGES ?= true
MIGRATION_CLEANUP_NODE_CONTENT_PRUNE ?= true
MIGRATION_CLEANUP_NODE_IMAGE_SCOPE ?= desired
MIGRATION_NODE_ARCHIVE_RETENTION_HOURS ?= 1
MIGRATION_SKIP_DOCKER_SOCKET_SERVICES ?= true
MIGRATION_SKIP_UNAVAILABLE_DATABASES ?= $(if $(filter production,$(MIGRATION_PROFILE)),false,true)
MIGRATION_DEPLOY_PLATFORM ?= true
MIGRATION_RELAX_RESOURCE_QUOTA ?= $(if $(filter lab,$(MIGRATION_PROFILE)),true,false)
MIGRATION_SECRET_PROVIDER ?= kubernetes
MIGRATION_SECRET_REMOTE_PREFIX ?= example/urban-platform/import
MIGRATION_SECRET_STORE_NAME ?= vault
MIGRATION_SECRET_STORE_KIND ?= ClusterSecretStore
MIGRATION_SECRET_REFRESH_INTERVAL ?= 1h
MIGRATION_SSH_USER ?= root
MIGRATION_SSH_KEY ?=
MIGRATION_BECOME_PASSWORD_FILE ?=
MIGRATION_BECOME_PASSWORD_PROMPT ?= auto
MIGRATION_CONTAINER_TOOL ?= auto
MIGRATION_POSTGRES_CLIENT_IMAGE ?= docker.io/library/postgres:18.3
STANDALONE_ENV_FILE ?= .env.standalone
MIGRATION_REGISTRY ?=
MIGRATION_IMAGE_TAG ?= imported-0.1.0
MIGRATION_NAMESPACE ?= $(NAMESPACE)
MIGRATION_DUMP_DIR ?= $(MIGRATION_PRIVATE_DIR)/db-dumps
MIGRATION_DB_TARGETS ?= $(MIGRATION_PRIVATE_DIR)/db-targets.yaml
IMPORT_RECOVERY_OUTPUT ?= $(MIGRATION_OUTPUT)/import-recovery-plan.md
BACKUP_POLICY ?= config/backup-policy.yaml
BACKUP_OUTPUT ?= reports/backup-plan.md
OBSERVABILITY_CONFIG ?= config/observability.yaml
SLO_CONFIG ?= config/slo.yaml
OBSERVABILITY_PLAN_PROFILE ?= $(MIGRATION_PROFILE)
OBSERVABILITY_PLAN_OUTPUT ?= reports/observability-plan.md
CLUSTER_DOCTOR_OUTPUT ?= reports/cluster-doctor.md
CLUSTER_DOCTOR_NODES ?= $(MIGRATION_RKE2_NODES)
CLUSTER_DOCTOR_CLUSTER_VIP ?= $(if $(MIGRATION_CLUSTER_VIP),$(MIGRATION_CLUSTER_VIP),$(DEPLOY_CLUSTER_VIP))
CLUSTER_DOCTOR_API_PORT ?= $(if $(MIGRATION_KUBERNETES_API_VIP_PORT),$(MIGRATION_KUBERNETES_API_VIP_PORT),7443)
CLUSTER_DOCTOR_SSH_USER ?= $(MIGRATION_SSH_USER)
CLUSTER_DOCTOR_SSH_KEY ?= $(MIGRATION_SSH_KEY)
CLUSTER_DOCTOR_REPAIR ?= false
CLUSTER_DOCTOR_REDACT ?= true
LAB_CAPACITY_CONFIG ?= config/lab-capacity.yaml
LAB_DEPLOY_PROFILE ?=
LAB_DEPLOY_NODE_COUNT ?= 0
LAB_DEPLOY_NODE_CPU ?=
LAB_DEPLOY_NODE_MEMORY ?=
LAB_DEPLOY_UTILIZATION_LIMIT ?= 0
LAB_DEPLOY_MAX_PODS ?= 0
LAB_DEPLOY_MAX_DATABASES ?= -1
LAB_DEPLOY_BATCH_SIZE ?= 0
LAB_DEPLOY_OUTPUT ?= reports/lab-deploy-plan.md
LAB_DEPLOY_VALUES ?= reports/lab-deploy-values.yaml
CAPACITY_PREFLIGHT_OUTPUT ?= reports/capacity-preflight.md
CAPACITY_PREFLIGHT_ENV_PROFILE ?= $(ENV_PROFILE)
CAPACITY_PREFLIGHT_IMPORT_BATCH ?= $(MIGRATION_IMPORT_BATCH)
CAPACITY_PREFLIGHT_MAX_IMPORTED_WORKLOADS ?= $(MIGRATION_PREFLIGHT_MAX_IMPORTED_WORKLOADS)
CAPACITY_PREFLIGHT_EVIDENCE ?=
IMAGE_CACHE_CONFIG ?= config/image-cache.yaml
IMAGE_CACHE_PROFILE ?=
IMAGE_CACHE_OUTPUT ?= reports/image-cache-plan.md
DB_MIGRATION_CONFIG ?= config/database-migration.yaml
DB_MIGRATION_PROFILE ?= $(MIGRATION_PROFILE)
DB_MIGRATION_OUTPUT ?= reports/database-migration-plan.md
EDGE_MIGRATION_CONFIG ?= config/edge-migration.yaml
EDGE_MIGRATION_PROFILE ?=
EDGE_MIGRATION_OUTPUT ?= reports/edge-migration-plan.md
ENV_PROFILE_CONFIG ?= config/environment-profiles.yaml
ENV_PROFILE ?= $(MIGRATION_PROFILE)
ENV_PROFILE_OUTPUT ?= reports/environment-profile-plan.md
ENV_PROFILE_VALUES ?= reports/environment-profile-values.yaml
ENV_PROFILE_EVIDENCE ?= reports/environment-profile-evidence-bundle.md
SMOKE_TEST_CONFIG ?= config/smoke-tests.yaml
SMOKE_TEST_PROFILE ?=
SMOKE_TEST_NAMESPACE ?= $(MIGRATION_NAMESPACE)
SMOKE_TEST_INGRESS_HOST ?= $(DEPLOY_INGRESS_HOST)
SMOKE_TEST_OUTPUT ?= reports/smoke-test-plan.md
SMOKE_TEST_VALUES ?= reports/smoke-test-values.yaml
SMOKE_TEST_EVIDENCE ?=
SMOKE_TEST_EXECUTE ?= false
RELEASE_RUNBOOK_CONFIG ?= config/release-runbook.yaml
RELEASE_RUNBOOK_PROFILE ?=
RELEASE_RUNBOOK_TAG ?= $(RELEASE_TAG)
RELEASE_RUNBOOK_RELEASE_EVIDENCE ?= $(RELEASE_VERIFY_REPORT)
RELEASE_RUNBOOK_CHANGE_TICKET ?= $(CHANGE_MANAGEMENT_TICKET)
RELEASE_RUNBOOK_APPROVAL_EVIDENCE ?= $(CHANGE_MANAGEMENT_APPROVAL_EVIDENCE)
RELEASE_RUNBOOK_ROLLBACK_PLAN ?= $(CHANGE_MANAGEMENT_ROLLBACK_PLAN)
RELEASE_RUNBOOK_SMOKE_TEST_PLAN ?= $(SMOKE_TEST_OUTPUT)
RELEASE_RUNBOOK_CUTOVER_GATE_PLAN ?= $(CUTOVER_GATES_OUTPUT)
RELEASE_RUNBOOK_ENVIRONMENT_EVIDENCE ?= $(ENV_PROFILE_EVIDENCE)
RELEASE_RUNBOOK_OUTPUT ?= reports/release-runbook-plan.md
RELEASE_RUNBOOK_VALUES ?= reports/release-runbook-values.yaml
RELEASE_RUNBOOK_EXECUTE ?= false
CLUSTER_UPGRADE_CONFIG ?= config/cluster-upgrade.yaml
CLUSTER_UPGRADE_PROFILE ?=
CLUSTER_UPGRADE_CURRENT_KUBERNETES ?=
CLUSTER_UPGRADE_TARGET_KUBERNETES ?=
CLUSTER_UPGRADE_CURRENT_RKE2 ?=
CLUSTER_UPGRADE_TARGET_RKE2 ?= $(MIGRATION_RKE2_VERSION)
CLUSTER_UPGRADE_CLUSTER_DOCTOR ?= $(CLUSTER_DOCTOR_OUTPUT)
CLUSTER_UPGRADE_ETCD_SNAPSHOT ?=
CLUSTER_UPGRADE_BACKUP_RESTORE_EVIDENCE ?= $(BACKUP_OUTPUT)
CLUSTER_UPGRADE_MAINTENANCE_WINDOW ?= $(CHANGE_MANAGEMENT_WINDOW)
CLUSTER_UPGRADE_CAPACITY_EVIDENCE ?= $(CAPACITY_PREFLIGHT_OUTPUT)
CLUSTER_UPGRADE_NODE_HEALTH_EVIDENCE ?= $(CLUSTER_DOCTOR_OUTPUT)
CLUSTER_UPGRADE_ROLLBACK_PLAN ?= $(CHANGE_MANAGEMENT_ROLLBACK_PLAN)
CLUSTER_UPGRADE_ADDON_COMPATIBILITY ?=
CLUSTER_UPGRADE_SMOKE_TEST_PLAN ?= $(SMOKE_TEST_OUTPUT)
CLUSTER_UPGRADE_INVENTORY_REVIEW ?=
CLUSTER_UPGRADE_RELEASE_NOTES_REVIEW ?=
CLUSTER_UPGRADE_OWNER_APPROVAL ?=
CLUSTER_UPGRADE_OUTPUT ?= reports/cluster-upgrade-plan.md
CLUSTER_UPGRADE_VALUES ?= reports/cluster-upgrade-values.yaml
CLUSTER_UPGRADE_EXECUTE ?= false
RELEASE_TAG ?= $(shell git describe --tags --exact-match 2>/dev/null)
RELEASE_VERIFY_REPORT ?= reports/release-evidence-verification.md
IMAGE_PROMOTION_REGISTRY ?= private-registry.example.invalid/platform
IMAGE_PROMOTION_PROFILE ?= production
IMAGE_PROMOTION_REPORT ?= reports/image-promotion-plan.md
REGISTRY_PROMOTION_CONFIG ?= config/registry-promotion.yaml
REGISTRY_PROMOTION_PROFILE ?=
REGISTRY_PROMOTION_REGISTRY ?= $(IMAGE_PROMOTION_REGISTRY)
REGISTRY_PROMOTION_CREDENTIAL_SOURCE ?=
REGISTRY_PROMOTION_IMAGE_PULL_SECRET ?= registry-credentials
REGISTRY_PROMOTION_OUTPUT ?= reports/registry-promotion-controller.md
REGISTRY_PROMOTION_VALUES ?= reports/registry-promotion-values.yaml
RUNTIME_HARDENING_CONFIG ?= config/runtime-hardening.yaml
RUNTIME_HARDENING_PROFILE ?=
RUNTIME_HARDENING_OUTPUT ?= reports/runtime-hardening-plan.md
RUNTIME_HARDENING_VALUES ?= reports/runtime-hardening-values.yaml
GITOPS_DELIVERY_CONFIG ?= config/gitops-delivery.yaml
GITOPS_DELIVERY_PROFILE ?=
GITOPS_DELIVERY_REPO_URL ?=
GITOPS_DELIVERY_TARGET_REVISION ?= main
GITOPS_DELIVERY_VALUES_PATH ?=
GITOPS_DELIVERY_OUTPUT ?= reports/gitops-delivery-plan.md
GITOPS_DELIVERY_VALUES ?= reports/gitops-delivery-values.yaml
PROGRESSIVE_DELIVERY_CONFIG ?= config/progressive-delivery.yaml
PROGRESSIVE_DELIVERY_PROFILE ?=
PROGRESSIVE_DELIVERY_GITOPS_PROFILE ?= $(GITOPS_DELIVERY_PROFILE)
PROGRESSIVE_DELIVERY_RUNTIME_PROFILE ?= $(RUNTIME_HARDENING_PROFILE)
PROGRESSIVE_DELIVERY_SLO_SOURCE ?=
PROGRESSIVE_DELIVERY_ROLLBACK_DRILL ?= false
PROGRESSIVE_DELIVERY_OUTPUT ?= reports/progressive-delivery-plan.md
PROGRESSIVE_DELIVERY_VALUES ?= reports/progressive-delivery-values.yaml
SCALING_POLICY_CONFIG ?= config/scaling-policy.yaml
SCALING_POLICY_PROFILE ?=
SCALING_POLICY_METRICS_SOURCE ?=
SCALING_POLICY_EVENT_SOURCE ?=
SCALING_POLICY_CAPACITY_REPORT ?=
SCALING_POLICY_LOAD_TEST_EVIDENCE ?= false
SCALING_POLICY_OUTPUT ?= reports/scaling-policy-plan.md
SCALING_POLICY_VALUES ?= reports/scaling-policy-values.yaml
NETWORK_CONNECTIVITY_CONFIG ?= config/network-connectivity.yaml
NETWORK_CONNECTIVITY_PROFILE ?=
NETWORK_CONNECTIVITY_TRAFFIC_INVENTORY ?=
NETWORK_CONNECTIVITY_EGRESS_CONTRACT ?=
NETWORK_CONNECTIVITY_DNS_TLS_EVIDENCE ?= false
NETWORK_CONNECTIVITY_MESH_READINESS ?= false
NETWORK_CONNECTIVITY_OUTPUT ?= reports/network-connectivity-plan.md
NETWORK_CONNECTIVITY_VALUES ?= reports/network-connectivity-values.yaml
ACCESS_GOVERNANCE_CONFIG ?= config/access-governance.yaml
ACCESS_GOVERNANCE_PROFILE ?=
ACCESS_GOVERNANCE_IDENTITY_PROVIDER ?=
ACCESS_GOVERNANCE_GROUP_MAPPING ?=
ACCESS_GOVERNANCE_TENANT_MODEL ?=
ACCESS_GOVERNANCE_RBAC_INVENTORY ?=
ACCESS_GOVERNANCE_AUDIT_EVIDENCE ?= false
ACCESS_GOVERNANCE_BREAK_GLASS_REVIEW ?= false
ACCESS_GOVERNANCE_OUTPUT ?= reports/access-governance-plan.md
ACCESS_GOVERNANCE_VALUES ?= reports/access-governance-values.yaml
COMPLIANCE_EVIDENCE_CONFIG ?= config/compliance-evidence.yaml
COMPLIANCE_EVIDENCE_PROFILE ?=
COMPLIANCE_EVIDENCE_RELEASE_TAG ?= $(RELEASE_TAG)
COMPLIANCE_EVIDENCE_ROOT ?=
COMPLIANCE_EVIDENCE_CONTROL_MAP ?=
COMPLIANCE_EVIDENCE_PRIVATE_INDEX ?=
COMPLIANCE_EVIDENCE_ATTESTATION_SOURCE ?=
COMPLIANCE_EVIDENCE_RESTORE_DRILL ?= false
COMPLIANCE_EVIDENCE_ACCESS_REVIEW ?= false
COMPLIANCE_EVIDENCE_INCIDENT_DRILL ?= false
COMPLIANCE_EVIDENCE_OUTPUT ?= reports/compliance-evidence-plan.md
COMPLIANCE_EVIDENCE_VALUES ?= reports/compliance-evidence-values.yaml
INCIDENT_RESPONSE_CONFIG ?= config/incident-response.yaml
INCIDENT_RESPONSE_PROFILE ?=
INCIDENT_RESPONSE_ALERT_ROUTE_SOURCE ?=
INCIDENT_RESPONSE_ESCALATION_ROTA ?=
INCIDENT_RESPONSE_PAGER_SERVICE ?=
INCIDENT_RESPONSE_RUNBOOK_SOURCE ?=
INCIDENT_RESPONSE_SERVICE_OWNER_MAP ?=
INCIDENT_RESPONSE_COMMS_TEMPLATE ?=
INCIDENT_RESPONSE_STAKEHOLDER_MAP ?=
INCIDENT_RESPONSE_REGULATORY_OWNER ?=
INCIDENT_RESPONSE_INCIDENT_DRILL ?= false
INCIDENT_RESPONSE_POST_INCIDENT_REVIEW ?= false
INCIDENT_RESPONSE_OUTPUT ?= reports/incident-response-plan.md
INCIDENT_RESPONSE_VALUES ?= reports/incident-response-values.yaml
CHANGE_MANAGEMENT_CONFIG ?= config/change-management.yaml
CHANGE_MANAGEMENT_PROFILE ?=
CHANGE_MANAGEMENT_TICKET ?=
CHANGE_MANAGEMENT_APPROVAL_EVIDENCE ?=
CHANGE_MANAGEMENT_RISK_ASSESSMENT ?=
CHANGE_MANAGEMENT_IMPACT_ASSESSMENT ?=
CHANGE_MANAGEMENT_WINDOW ?=
CHANGE_MANAGEMENT_ROLLBACK_PLAN ?=
CHANGE_MANAGEMENT_SMOKE_TEST_PLAN ?=
CHANGE_MANAGEMENT_FREEZE_CHECK ?= false
CHANGE_MANAGEMENT_STAKEHOLDER_NOTICE ?= false
CHANGE_MANAGEMENT_POST_CHANGE_REVIEW ?= false
CHANGE_MANAGEMENT_REGULATORY_EVIDENCE ?= false
CHANGE_MANAGEMENT_OUTPUT ?= reports/change-management-plan.md
CHANGE_MANAGEMENT_VALUES ?= reports/change-management-values.yaml
CUTOVER_GATES_CONFIG ?= config/cutover-gates.yaml
CUTOVER_GATES_PROFILE ?=
CUTOVER_GATES_NAMESPACE ?= $(MIGRATION_NAMESPACE)
CUTOVER_GATES_INGRESS_HOST ?= $(DEPLOY_INGRESS_HOST)
CUTOVER_GATES_IMPORT_OUTPUT ?= $(MIGRATION_OUTPUT)
CUTOVER_CHANGE_TICKET ?= $(CHANGE_MANAGEMENT_TICKET)
CUTOVER_APPROVAL_EVIDENCE ?= $(CHANGE_MANAGEMENT_APPROVAL_EVIDENCE)
CUTOVER_ROLLBACK_PLAN ?= $(CHANGE_MANAGEMENT_ROLLBACK_PLAN)
CUTOVER_SMOKE_TEST_PLAN ?= $(SMOKE_TEST_OUTPUT)
CUTOVER_RELEASE_EVIDENCE ?= $(RELEASE_VERIFY_REPORT)
CUTOVER_REGISTRY_EVIDENCE ?= $(REGISTRY_PROMOTION_OUTPUT)
CUTOVER_BACKUP_RESTORE_EVIDENCE ?= $(BACKUP_OUTPUT)
CUTOVER_DATABASE_RESTORE_EVIDENCE ?= $(DB_MIGRATION_OUTPUT)
CUTOVER_RESTORE_POINT_EVIDENCE ?=
CUTOVER_DNS_TLS_EVIDENCE ?= false
CUTOVER_OWNER_HANDOFF ?= false
CUTOVER_POST_CUTOVER_WINDOW ?=
CUTOVER_GATES_OUTPUT ?= reports/cutover-gate-plan.md
CUTOVER_GATES_VALUES ?= reports/cutover-gate-values.yaml
DISASTER_RECOVERY_CONFIG ?= config/disaster-recovery.yaml
DISASTER_RECOVERY_PROFILE ?=
DISASTER_RECOVERY_RTO_RPO ?=
DISASTER_RECOVERY_DEPENDENCY_MAP ?=
DISASTER_RECOVERY_CRITICALITY_MAP ?=
DISASTER_RECOVERY_BACKUP_REPLICATION ?=
DISASTER_RECOVERY_DATA_REPLICATION ?=
DISASTER_RECOVERY_CROSS_ZONE_EVIDENCE ?=
DISASTER_RECOVERY_DATABASE_RESTORE_EVIDENCE ?=
DISASTER_RECOVERY_ETCD_RESTORE_EVIDENCE ?=
DISASTER_RECOVERY_NAMESPACE_RESTORE_EVIDENCE ?=
DISASTER_RECOVERY_APPLICATION_SMOKE_TEST ?=
DISASTER_RECOVERY_RUNBOOK_SOURCE ?=
DISASTER_RECOVERY_COMMS_PLAN ?=
DISASTER_RECOVERY_MANUAL_WORKAROUND ?=
DISASTER_RECOVERY_SUPPLIER_CONTACTS ?=
DISASTER_RECOVERY_DRILL_EVIDENCE ?=
DISASTER_RECOVERY_RTO_EVIDENCE ?=
DISASTER_RECOVERY_POST_DRILL_REVIEW ?= false
DISASTER_RECOVERY_OUTPUT ?= reports/disaster-recovery-plan.md
DISASTER_RECOVERY_VALUES ?= reports/disaster-recovery-values.yaml

.PHONY: help setup-local doctor-local ci-contract private-data-audit operator-ready validate image-policy image-promotion-plan registry-promotion-plan runtime-hardening-plan gitops-delivery-plan progressive-delivery-plan scaling-policy-plan network-connectivity-plan access-governance-plan compliance-evidence-plan incident-response-plan change-management-plan cutover-gate-plan smoke-test-plan release-runbook-plan cluster-upgrade-plan disaster-recovery-plan lint configure backup-plan observability-plan cluster-doctor cluster-repair lab-deploy-plan capacity-preflight image-cache-plan database-migration-plan edge-migration-plan environment-profile-plan import-check import-plan import-preflight import-recovery-plan import-migrate import-auto python-deps ansible-collections preflight bootstrap-check bootstrap install-cluster-check install-cluster operator-kubeconfig configure-edge-ports install-helm install-helmfile install-local-path-storage ensure-storageclass install-operators wait-operator-crds ensure-namespace recover-helm-release deploy deploy-auto deploy-strimzi-kafka deploy-dry-run package-chart release-evidence verify-release-evidence status observability-status docker-up docker-down docker-status docker-standalone-config docker-standalone-up docker-standalone-down docker-standalone-status policy clean

HELM_DEPLOY_SET_ARGS = \
	--set namespace.create=false \
	$(if $(DEPLOY_INGRESS_HOST),--set ingress.host=$(DEPLOY_INGRESS_HOST),) \
	$(if $(DEPLOY_CLUSTER_DOMAIN),--set global.cluster.domain=$(DEPLOY_CLUSTER_DOMAIN),) \
	$(if $(DEPLOY_CLUSTER_VIP),--set global.cluster.vip=$(DEPLOY_CLUSTER_VIP),) \
	$(if $(DEPLOY_TLS_SECRET_NAME),--set ingress.tls.secretName=$(DEPLOY_TLS_SECRET_NAME),) \
	$(if $(DEPLOY_TLS_CREATE_SECRET),--set ingress.tls.createSecret=$(DEPLOY_TLS_CREATE_SECRET),) \
	--set namespace.resourceQuota.enabled=$(DEPLOY_NAMESPACE_RESOURCE_QUOTA) \
	$(if $(filter true,$(DEPLOY_SKIP_PLACEHOLDER_WORKLOADS)),--set global.skipPlaceholderWorkloads=true,) \
	$(if $(DEPLOY_ROOT_IMAGE_REPOSITORY),--set workloads.$(DEPLOY_ROOT_WORKLOAD).image.repository=$(DEPLOY_ROOT_IMAGE_REPOSITORY),) \
	$(if $(DEPLOY_ROOT_IMAGE_TAG),--set-string workloads.$(DEPLOY_ROOT_WORKLOAD).image.tag=$(DEPLOY_ROOT_IMAGE_TAG),) \
	$(if $(DEPLOY_ROOT_CONTAINER_PORT),--set 'workloads.$(DEPLOY_ROOT_WORKLOAD).ports[0].containerPort=$(DEPLOY_ROOT_CONTAINER_PORT)',) \
	$(if $(DEPLOY_ROOT_SERVICE_PORT),--set 'workloads.$(DEPLOY_ROOT_WORKLOAD).ports[0].servicePort=$(DEPLOY_ROOT_SERVICE_PORT)',) \
	$(if $(DEPLOY_ROOT_PROBE_PORT),--set workloads.$(DEPLOY_ROOT_WORKLOAD).probe.port=$(DEPLOY_ROOT_PROBE_PORT),) \
	$(if $(DEPLOY_ROOT_INGRESS_ENABLED),--set workloads.$(DEPLOY_ROOT_WORKLOAD).ingress.enabled=$(DEPLOY_ROOT_INGRESS_ENABLED),) \
	$(if $(DEPLOY_ROOT_INGRESS_PATH),--set workloads.$(DEPLOY_ROOT_WORKLOAD).ingress.path=$(DEPLOY_ROOT_INGRESS_PATH),) \
	$(if $(DEPLOY_ALLOWED_CIDRS),--set ingress.sourceAllowList.enabled=true --set-string ingress.sourceAllowList.cidrsText="$(DEPLOY_ALLOWED_CIDRS)",) \
	--set observability.grafana.enabled=$(DEPLOY_ENABLE_GRAFANA) \
	--set observability.prometheus.enabled=$(DEPLOY_ENABLE_PROMETHEUS) \
	--set observability.opentelemetry.enabled=$(DEPLOY_ENABLE_OPENTELEMETRY) \
	--set observability.elasticsearch.enabled=$(DEPLOY_ENABLE_ELASTICSEARCH) \
	--set observability.kibana.enabled=$(DEPLOY_ENABLE_KIBANA) \
	--set observability.logstash.enabled=$(DEPLOY_ENABLE_LOGSTASH) \
	--set observability.loki.enabled=$(DEPLOY_ENABLE_LOKI) \
	--set observability.clickhouse.enabled=$(DEPLOY_ENABLE_CLICKHOUSE) \
	--set observability.elasticsearch.service.type=$(DEPLOY_OBSERVABILITY_SERVICE_TYPE) \
	--set observability.elasticsearch.service.nodePort=$(DEPLOY_ELASTICSEARCH_NODE_PORT) \
	--set observability.kibana.service.type=$(DEPLOY_OBSERVABILITY_SERVICE_TYPE) \
	--set observability.kibana.service.nodePort=$(DEPLOY_KIBANA_NODE_PORT) \
	$(if $(filter true,$(DEPLOY_LAB_STORAGE)),--set global.replicaOverride=$(DEPLOY_LAB_REPLICA_OVERRIDE) --set global.defaultReplicas=$(DEPLOY_LAB_REPLICA_OVERRIDE) --set autoscaling.enabled=$(DEPLOY_LAB_AUTOSCALING) --set global.scheduling.topologySpread=$(DEPLOY_LAB_TOPOLOGY_SPREAD) --set databases.storageOverride.size=$(DEPLOY_DATABASE_STORAGE_SIZE) --set databases.storageOverride.className=$(DEPLOY_DATABASE_STORAGE_CLASS) --set 'observability.elasticsearch.nodeSets[0].storage=$(DEPLOY_ELASTICSEARCH_STORAGE)' --set messaging.kafka.storage.size=$(DEPLOY_KAFKA_STORAGE) --set messaging.kafka.storage.className=$(DEPLOY_DATABASE_STORAGE_CLASS) --set messaging.kafka.zookeeper.storage.size=$(DEPLOY_ZOOKEEPER_STORAGE) --set messaging.kafka.zookeeper.storage.className=$(DEPLOY_DATABASE_STORAGE_CLASS) --set messaging.redis.storage.size=$(DEPLOY_REDIS_STORAGE) --set messaging.redis.storage.className=$(DEPLOY_DATABASE_STORAGE_CLASS) --set messaging.redis.sentinel.enabled=$(DEPLOY_REDIS_SENTINEL),)

define require_prod_confirmation
	@if [ "$(ENV)" = "prod" ] && [ "$(CONFIRM_PROD)" != "true" ]; then \
		echo "Refusing to mutate prod without CONFIRM_PROD=true. Run preflight/check targets first."; \
		exit 2; \
	fi
endef

define install_python_deps
req="$$( $(PYTHON) -c 'import sys; print("requirements-ci-modern.txt" if sys.version_info >= (3, 12) else "requirements-ci.txt")' )"; \
	echo "Installing Python operator dependencies from $$req"; \
	$(PIP) install -r "$$req"; \
	touch "$(PYTHON_DEPS_STAMP)"
endef

help:
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make <target> [ENV=prod ENGINE=rke2 INGRESS=traefik WEB=nginx DB=postgresql OBS=disabled TOPOLOGY=three-node-ha]\n\nTargets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  %-22s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

setup-local: ## Create or update the local Python virtualenv for validation and operator tooling.
	$(PYTHON) $(LOCAL_SETUP_SCRIPT) --venv "$(VENV)"

doctor-local: ## Diagnose local workstation/operator prerequisites and write a public-safe report.
	mkdir -p reports
	$(PYTHON) $(LOCAL_DOCTOR_SCRIPT) --report "$(LOCAL_DOCTOR_REPORT)"

ci-contract: ## Validate GitHub/GitLab CI lane pins, actions, and gate commands.
	mkdir -p reports
	$(PYTHON) $(CI_CONTRACT_SCRIPT) --report "$(CI_CONTRACT_REPORT)"

private-data-audit: ## Scan tracked repository content for secret/private-data leakage and write a public-safe report.
	mkdir -p reports
	$(PYTHON) $(PRIVATE_DATA_AUDIT_SCRIPT) --report "$(PRIVATE_DATA_AUDIT_REPORT)"

operator-ready: ## One-command local readiness check before cluster deploy, import, or release work.
	$(MAKE) setup-local
	$(MAKE) doctor-local
	$(MAKE) ci-contract
	$(MAKE) private-data-audit
	$(MAKE) capacity-preflight
	$(MAKE) validate
	$(MAKE) lint

$(PYTHON_DEPS_STAMP): requirements-ci.txt requirements-ci-modern.txt
	mkdir -p .ansible
	@$(install_python_deps)

python-deps: $(PYTHON_DEPS_STAMP) ## Install Python/Ansible dependencies compatible with the current Python.
	@if ! $(PYTHON) -c 'import ansible, yaml' >/dev/null 2>&1 || ! $(ANSIBLE_PLAYBOOK) --version >/dev/null 2>&1 || ! $(ANSIBLE_GALAXY) --version >/dev/null 2>&1; then \
		echo "Python/Ansible dependencies are missing from $(PYTHON); reinstalling."; \
		$(install_python_deps); \
	fi

validate: python-deps ## Validate YAML, Helm chart structure, scripts, and config catalogs.
	$(PYTHON) $(CI_CONTRACT_SCRIPT)
	$(PYTHON) $(PRIVATE_DATA_AUDIT_SCRIPT)
	$(PYTHON) scripts/validate.py
	$(PYTHON) scripts/images/validate-images.py

image-policy: ## Validate image tag, digest, and approved runtime-image policy.
	$(PYTHON) scripts/images/validate-images.py

image-promotion-plan: ## Generate a public-safe production image promotion evidence plan.
	mkdir -p reports
	$(PYTHON) scripts/images/promotion_plan.py --values "$(VALUES)" --policy config/image-policy.yaml --registry "$(IMAGE_PROMOTION_REGISTRY)" --profile "$(IMAGE_PROMOTION_PROFILE)" --output "$(IMAGE_PROMOTION_REPORT)"

registry-promotion-plan: ## Generate a public-safe registry promotion controller plan and Helm override template.
	mkdir -p reports
	$(PYTHON) scripts/images/registry_promotion_controller.py --config "$(REGISTRY_PROMOTION_CONFIG)" --values "$(VALUES)" --policy config/image-policy.yaml --profile "$(REGISTRY_PROMOTION_PROFILE)" --registry "$(REGISTRY_PROMOTION_REGISTRY)" --credential-source "$(REGISTRY_PROMOTION_CREDENTIAL_SOURCE)" --image-pull-secret "$(REGISTRY_PROMOTION_IMAGE_PULL_SECRET)" --output "$(REGISTRY_PROMOTION_OUTPUT)" --overrides "$(REGISTRY_PROMOTION_VALUES)" $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

runtime-hardening-plan: ## Generate a public-safe runtime hardening and admission policy plan.
	mkdir -p reports
	$(PYTHON) scripts/runtime_hardening_plan.py --config "$(RUNTIME_HARDENING_CONFIG)" --values "$(VALUES)" --profile "$(RUNTIME_HARDENING_PROFILE)" --output "$(RUNTIME_HARDENING_OUTPUT)" --overrides "$(RUNTIME_HARDENING_VALUES)" $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

gitops-delivery-plan: ## Generate a public-safe GitOps delivery and drift-control plan.
	mkdir -p reports
	$(PYTHON) scripts/gitops_delivery_plan.py --config "$(GITOPS_DELIVERY_CONFIG)" --profile "$(GITOPS_DELIVERY_PROFILE)" --repo-url "$(GITOPS_DELIVERY_REPO_URL)" --target-revision "$(GITOPS_DELIVERY_TARGET_REVISION)" --values-path "$(GITOPS_DELIVERY_VALUES_PATH)" --output "$(GITOPS_DELIVERY_OUTPUT)" --overrides "$(GITOPS_DELIVERY_VALUES)" $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

progressive-delivery-plan: ## Generate a public-safe progressive delivery and rollback plan.
	mkdir -p reports
	$(PYTHON) scripts/progressive_delivery_plan.py --config "$(PROGRESSIVE_DELIVERY_CONFIG)" --profile "$(PROGRESSIVE_DELIVERY_PROFILE)" --gitops-profile "$(PROGRESSIVE_DELIVERY_GITOPS_PROFILE)" --runtime-profile "$(PROGRESSIVE_DELIVERY_RUNTIME_PROFILE)" --slo-source "$(PROGRESSIVE_DELIVERY_SLO_SOURCE)" --output "$(PROGRESSIVE_DELIVERY_OUTPUT)" --overrides "$(PROGRESSIVE_DELIVERY_VALUES)" $(if $(filter true,$(PROGRESSIVE_DELIVERY_ROLLBACK_DRILL)),--rollback-drill,) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

scaling-policy-plan: ## Generate a public-safe scaling policy and capacity automation plan.
	mkdir -p reports
	$(PYTHON) scripts/scaling_policy_plan.py --config "$(SCALING_POLICY_CONFIG)" --profile "$(SCALING_POLICY_PROFILE)" --metrics-source "$(SCALING_POLICY_METRICS_SOURCE)" --event-source "$(SCALING_POLICY_EVENT_SOURCE)" --capacity-report "$(SCALING_POLICY_CAPACITY_REPORT)" --output "$(SCALING_POLICY_OUTPUT)" --overrides "$(SCALING_POLICY_VALUES)" $(if $(filter true,$(SCALING_POLICY_LOAD_TEST_EVIDENCE)),--load-test-evidence,) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

network-connectivity-plan: ## Generate a public-safe network connectivity, egress, and service mesh plan.
	mkdir -p reports
	$(PYTHON) scripts/network_connectivity_plan.py --config "$(NETWORK_CONNECTIVITY_CONFIG)" --profile "$(NETWORK_CONNECTIVITY_PROFILE)" --traffic-inventory "$(NETWORK_CONNECTIVITY_TRAFFIC_INVENTORY)" --egress-contract "$(NETWORK_CONNECTIVITY_EGRESS_CONTRACT)" --output "$(NETWORK_CONNECTIVITY_OUTPUT)" --overrides "$(NETWORK_CONNECTIVITY_VALUES)" $(if $(filter true,$(NETWORK_CONNECTIVITY_DNS_TLS_EVIDENCE)),--dns-tls-evidence,) $(if $(filter true,$(NETWORK_CONNECTIVITY_MESH_READINESS)),--mesh-readiness,) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

access-governance-plan: ## Generate a public-safe access governance, RBAC, and tenant isolation plan.
	mkdir -p reports
	$(PYTHON) scripts/access_governance_plan.py --config "$(ACCESS_GOVERNANCE_CONFIG)" --profile "$(ACCESS_GOVERNANCE_PROFILE)" --identity-provider "$(ACCESS_GOVERNANCE_IDENTITY_PROVIDER)" --group-mapping "$(ACCESS_GOVERNANCE_GROUP_MAPPING)" --tenant-model "$(ACCESS_GOVERNANCE_TENANT_MODEL)" --rbac-inventory "$(ACCESS_GOVERNANCE_RBAC_INVENTORY)" --output "$(ACCESS_GOVERNANCE_OUTPUT)" --overrides "$(ACCESS_GOVERNANCE_VALUES)" $(if $(filter true,$(ACCESS_GOVERNANCE_AUDIT_EVIDENCE)),--audit-evidence,) $(if $(filter true,$(ACCESS_GOVERNANCE_BREAK_GLASS_REVIEW)),--break-glass-review,) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

compliance-evidence-plan: ## Generate a public-safe compliance evidence and audit-pack readiness plan.
	mkdir -p reports
	$(PYTHON) scripts/compliance_evidence_plan.py --config "$(COMPLIANCE_EVIDENCE_CONFIG)" --profile "$(COMPLIANCE_EVIDENCE_PROFILE)" --release-tag "$(COMPLIANCE_EVIDENCE_RELEASE_TAG)" --evidence-root "$(COMPLIANCE_EVIDENCE_ROOT)" --control-map "$(COMPLIANCE_EVIDENCE_CONTROL_MAP)" --private-evidence-index "$(COMPLIANCE_EVIDENCE_PRIVATE_INDEX)" --attestation-source "$(COMPLIANCE_EVIDENCE_ATTESTATION_SOURCE)" --output "$(COMPLIANCE_EVIDENCE_OUTPUT)" --overrides "$(COMPLIANCE_EVIDENCE_VALUES)" $(if $(filter true,$(COMPLIANCE_EVIDENCE_RESTORE_DRILL)),--restore-drill-evidence,) $(if $(filter true,$(COMPLIANCE_EVIDENCE_ACCESS_REVIEW)),--access-review-evidence,) $(if $(filter true,$(COMPLIANCE_EVIDENCE_INCIDENT_DRILL)),--incident-drill-evidence,) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

incident-response-plan: ## Generate a public-safe incident response and operational readiness plan.
	mkdir -p reports
	$(PYTHON) scripts/incident_response_plan.py --config "$(INCIDENT_RESPONSE_CONFIG)" --profile "$(INCIDENT_RESPONSE_PROFILE)" --alert-route-source "$(INCIDENT_RESPONSE_ALERT_ROUTE_SOURCE)" --escalation-rota "$(INCIDENT_RESPONSE_ESCALATION_ROTA)" --pager-service "$(INCIDENT_RESPONSE_PAGER_SERVICE)" --runbook-source "$(INCIDENT_RESPONSE_RUNBOOK_SOURCE)" --service-owner-map "$(INCIDENT_RESPONSE_SERVICE_OWNER_MAP)" --comms-template "$(INCIDENT_RESPONSE_COMMS_TEMPLATE)" --stakeholder-map "$(INCIDENT_RESPONSE_STAKEHOLDER_MAP)" --regulatory-owner "$(INCIDENT_RESPONSE_REGULATORY_OWNER)" --output "$(INCIDENT_RESPONSE_OUTPUT)" --overrides "$(INCIDENT_RESPONSE_VALUES)" $(if $(filter true,$(INCIDENT_RESPONSE_INCIDENT_DRILL)),--incident-drill,) $(if $(filter true,$(INCIDENT_RESPONSE_POST_INCIDENT_REVIEW)),--post-incident-review,) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

change-management-plan: ## Generate a public-safe change management and maintenance-window plan.
	mkdir -p reports
	$(PYTHON) scripts/change_management_plan.py --config "$(CHANGE_MANAGEMENT_CONFIG)" --profile "$(CHANGE_MANAGEMENT_PROFILE)" --change-ticket "$(CHANGE_MANAGEMENT_TICKET)" --approval-evidence "$(CHANGE_MANAGEMENT_APPROVAL_EVIDENCE)" --risk-assessment "$(CHANGE_MANAGEMENT_RISK_ASSESSMENT)" --impact-assessment "$(CHANGE_MANAGEMENT_IMPACT_ASSESSMENT)" --maintenance-window "$(CHANGE_MANAGEMENT_WINDOW)" --rollback-plan "$(CHANGE_MANAGEMENT_ROLLBACK_PLAN)" --smoke-test-plan "$(CHANGE_MANAGEMENT_SMOKE_TEST_PLAN)" --output "$(CHANGE_MANAGEMENT_OUTPUT)" --overrides "$(CHANGE_MANAGEMENT_VALUES)" $(if $(filter true,$(CHANGE_MANAGEMENT_FREEZE_CHECK)),--freeze-check,) $(if $(filter true,$(CHANGE_MANAGEMENT_STAKEHOLDER_NOTICE)),--stakeholder-notice,) $(if $(filter true,$(CHANGE_MANAGEMENT_POST_CHANGE_REVIEW)),--post-change-review,) $(if $(filter true,$(CHANGE_MANAGEMENT_REGULATORY_EVIDENCE)),--regulatory-evidence,) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

cutover-gate-plan: ## Generate a public-safe production cutover and smoke-test gate plan.
	mkdir -p reports
	$(PYTHON) scripts/cutover_gate_plan.py --config "$(CUTOVER_GATES_CONFIG)" --profile "$(CUTOVER_GATES_PROFILE)" --namespace "$(CUTOVER_GATES_NAMESPACE)" --ingress-host "$(CUTOVER_GATES_INGRESS_HOST)" --import-output "$(CUTOVER_GATES_IMPORT_OUTPUT)" --change-ticket "$(CUTOVER_CHANGE_TICKET)" --approval-evidence "$(CUTOVER_APPROVAL_EVIDENCE)" --rollback-plan "$(CUTOVER_ROLLBACK_PLAN)" --smoke-test-plan "$(CUTOVER_SMOKE_TEST_PLAN)" --release-evidence "$(CUTOVER_RELEASE_EVIDENCE)" --registry-evidence "$(CUTOVER_REGISTRY_EVIDENCE)" --backup-restore-evidence "$(CUTOVER_BACKUP_RESTORE_EVIDENCE)" --database-restore-evidence "$(CUTOVER_DATABASE_RESTORE_EVIDENCE)" --restore-point-evidence "$(CUTOVER_RESTORE_POINT_EVIDENCE)" --post-cutover-window "$(CUTOVER_POST_CUTOVER_WINDOW)" --output "$(CUTOVER_GATES_OUTPUT)" --overrides "$(CUTOVER_GATES_VALUES)" $(if $(filter true,$(CUTOVER_DNS_TLS_EVIDENCE)),--dns-tls-evidence,) $(if $(filter true,$(CUTOVER_OWNER_HANDOFF)),--owner-handoff,) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

smoke-test-plan: ## Generate a public-safe post-migration smoke-test and health-probe plan.
	mkdir -p reports
	$(PYTHON) scripts/smoke_test_plan.py --config "$(SMOKE_TEST_CONFIG)" --profile "$(SMOKE_TEST_PROFILE)" --namespace "$(SMOKE_TEST_NAMESPACE)" --ingress-host "$(SMOKE_TEST_INGRESS_HOST)" --evidence "$(SMOKE_TEST_EVIDENCE)" --output "$(SMOKE_TEST_OUTPUT)" --overrides "$(SMOKE_TEST_VALUES)" $(if $(filter true,$(SMOKE_TEST_EXECUTE)),--execute,) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

release-runbook-plan: ## Generate a public-safe release runbook and evidence gate plan.
	mkdir -p reports
	$(PYTHON) scripts/release_runbook_plan.py --config "$(RELEASE_RUNBOOK_CONFIG)" --profile "$(RELEASE_RUNBOOK_PROFILE)" --release-tag "$(RELEASE_RUNBOOK_TAG)" --release-evidence "$(RELEASE_RUNBOOK_RELEASE_EVIDENCE)" --change-ticket "$(RELEASE_RUNBOOK_CHANGE_TICKET)" --approval-evidence "$(RELEASE_RUNBOOK_APPROVAL_EVIDENCE)" --rollback-plan "$(RELEASE_RUNBOOK_ROLLBACK_PLAN)" --smoke-test-plan "$(RELEASE_RUNBOOK_SMOKE_TEST_PLAN)" --cutover-gate-plan "$(RELEASE_RUNBOOK_CUTOVER_GATE_PLAN)" --environment-evidence "$(RELEASE_RUNBOOK_ENVIRONMENT_EVIDENCE)" --output "$(RELEASE_RUNBOOK_OUTPUT)" --overrides "$(RELEASE_RUNBOOK_VALUES)" $(if $(filter true,$(RELEASE_RUNBOOK_EXECUTE)),--execute,) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

cluster-upgrade-plan: ## Generate a public-safe cluster upgrade and version-skew guardrail plan.
	mkdir -p reports
	$(PYTHON) scripts/cluster_upgrade_plan.py --config "$(CLUSTER_UPGRADE_CONFIG)" --profile "$(CLUSTER_UPGRADE_PROFILE)" --current-kubernetes "$(CLUSTER_UPGRADE_CURRENT_KUBERNETES)" --target-kubernetes "$(CLUSTER_UPGRADE_TARGET_KUBERNETES)" --current-rke2 "$(CLUSTER_UPGRADE_CURRENT_RKE2)" --target-rke2 "$(CLUSTER_UPGRADE_TARGET_RKE2)" --cluster-doctor "$(CLUSTER_UPGRADE_CLUSTER_DOCTOR)" --etcd-snapshot "$(CLUSTER_UPGRADE_ETCD_SNAPSHOT)" --backup-restore-evidence "$(CLUSTER_UPGRADE_BACKUP_RESTORE_EVIDENCE)" --maintenance-window "$(CLUSTER_UPGRADE_MAINTENANCE_WINDOW)" --capacity-evidence "$(CLUSTER_UPGRADE_CAPACITY_EVIDENCE)" --node-health-evidence "$(CLUSTER_UPGRADE_NODE_HEALTH_EVIDENCE)" --rollback-plan "$(CLUSTER_UPGRADE_ROLLBACK_PLAN)" --addon-compatibility "$(CLUSTER_UPGRADE_ADDON_COMPATIBILITY)" --smoke-test-plan "$(CLUSTER_UPGRADE_SMOKE_TEST_PLAN)" --inventory-review "$(CLUSTER_UPGRADE_INVENTORY_REVIEW)" --release-notes-review "$(CLUSTER_UPGRADE_RELEASE_NOTES_REVIEW)" --owner-approval "$(CLUSTER_UPGRADE_OWNER_APPROVAL)" --output "$(CLUSTER_UPGRADE_OUTPUT)" --overrides "$(CLUSTER_UPGRADE_VALUES)" $(if $(filter true,$(CLUSTER_UPGRADE_EXECUTE)),--execute,) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

disaster-recovery-plan: ## Generate a public-safe disaster recovery and business continuity plan.
	mkdir -p reports
	$(PYTHON) scripts/disaster_recovery_plan.py --config "$(DISASTER_RECOVERY_CONFIG)" --profile "$(DISASTER_RECOVERY_PROFILE)" --rto-rpo "$(DISASTER_RECOVERY_RTO_RPO)" --dependency-map "$(DISASTER_RECOVERY_DEPENDENCY_MAP)" --criticality-map "$(DISASTER_RECOVERY_CRITICALITY_MAP)" --backup-replication "$(DISASTER_RECOVERY_BACKUP_REPLICATION)" --data-replication "$(DISASTER_RECOVERY_DATA_REPLICATION)" --cross-zone-evidence "$(DISASTER_RECOVERY_CROSS_ZONE_EVIDENCE)" --database-restore-evidence "$(DISASTER_RECOVERY_DATABASE_RESTORE_EVIDENCE)" --etcd-restore-evidence "$(DISASTER_RECOVERY_ETCD_RESTORE_EVIDENCE)" --namespace-restore-evidence "$(DISASTER_RECOVERY_NAMESPACE_RESTORE_EVIDENCE)" --application-smoke-test "$(DISASTER_RECOVERY_APPLICATION_SMOKE_TEST)" --runbook-source "$(DISASTER_RECOVERY_RUNBOOK_SOURCE)" --comms-plan "$(DISASTER_RECOVERY_COMMS_PLAN)" --manual-workaround "$(DISASTER_RECOVERY_MANUAL_WORKAROUND)" --supplier-contacts "$(DISASTER_RECOVERY_SUPPLIER_CONTACTS)" --drill-evidence "$(DISASTER_RECOVERY_DRILL_EVIDENCE)" --rto-evidence "$(DISASTER_RECOVERY_RTO_EVIDENCE)" --output "$(DISASTER_RECOVERY_OUTPUT)" --overrides "$(DISASTER_RECOVERY_VALUES)" $(if $(filter true,$(DISASTER_RECOVERY_POST_DRILL_REVIEW)),--post-drill-review,) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

lint: python-deps ## Run local static checks that mirror the CI static gate.
	$(YAMLLINT) .
	$(SHELLCHECK) $$(git ls-files '*.sh')

configure: ## Update selected runtime defaults in Helm values.
	$(PYTHON) scripts/configure.py --engine $(ENGINE) --ingress-controller $(INGRESS) --webserver $(WEB) --database $(DB) --observability $(OBS) --values $(VALUES)

backup-plan: python-deps ## Generate a public-safe backup/restore plan without enabling or applying backups.
	mkdir -p reports
	$(PYTHON) scripts/backup_plan.py --values "$(VALUES)" --policy "$(BACKUP_POLICY)" --output "$(BACKUP_OUTPUT)"

observability-plan: ## Generate a public-safe observability and SLO readiness plan.
	mkdir -p reports
	$(PYTHON) scripts/observability_plan.py --values "$(VALUES)" --observability-config "$(OBSERVABILITY_CONFIG)" --slo-config "$(SLO_CONFIG)" --profile "$(OBSERVABILITY_PLAN_PROFILE)" --output "$(OBSERVABILITY_PLAN_OUTPUT)"

cluster-doctor: ## Diagnose RKE2 API/VIP/kubeconfig health and write a public-safe report.
	mkdir -p reports
	$(PYTHON) scripts/cluster_doctor.py --nodes "$(CLUSTER_DOCTOR_NODES)" --cluster-vip "$(CLUSTER_DOCTOR_CLUSTER_VIP)" --api-port "$(CLUSTER_DOCTOR_API_PORT)" --ssh-user "$(CLUSTER_DOCTOR_SSH_USER)" --ssh-key "$(CLUSTER_DOCTOR_SSH_KEY)" --kubeconfig "$(OPERATOR_KUBECONFIG)" --inventory "$(INVENTORY)" --environment "$(ENV)" --engine "$(ENGINE)" --output "$(CLUSTER_DOCTOR_OUTPUT)" $(if $(filter true,$(CLUSTER_DOCTOR_REPAIR)),--repair,) $(if $(filter true,$(CLUSTER_DOCTOR_REDACT)),--redact-sensitive,)

cluster-repair: CLUSTER_DOCTOR_REPAIR = true
cluster-repair: cluster-doctor ## Run cluster doctor and explicitly invoke guarded kubeconfig/RKE2 repair.

lab-deploy-plan: ## Generate a public-safe lab capacity plan and first-wave values overlay.
	mkdir -p reports
	$(PYTHON) scripts/lab_deploy_plan.py --values "$(VALUES)" --capacity "$(LAB_CAPACITY_CONFIG)" --profile "$(LAB_DEPLOY_PROFILE)" --node-count "$(LAB_DEPLOY_NODE_COUNT)" --node-cpu "$(LAB_DEPLOY_NODE_CPU)" --node-memory "$(LAB_DEPLOY_NODE_MEMORY)" --utilization-limit "$(LAB_DEPLOY_UTILIZATION_LIMIT)" --max-pods "$(LAB_DEPLOY_MAX_PODS)" --max-databases "$(LAB_DEPLOY_MAX_DATABASES)" --batch-size "$(LAB_DEPLOY_BATCH_SIZE)" --output "$(LAB_DEPLOY_OUTPUT)" --overrides "$(LAB_DEPLOY_VALUES)"

capacity-preflight: ## Fail fast on unsafe lab/production capacity assumptions before deploy or import.
	mkdir -p reports
	$(PYTHON) scripts/capacity_preflight.py --values "$(VALUES)" --capacity "$(LAB_CAPACITY_CONFIG)" --environment-profiles "$(ENV_PROFILE_CONFIG)" --capacity-profile "$(LAB_DEPLOY_PROFILE)" --environment-profile "$(CAPACITY_PREFLIGHT_ENV_PROFILE)" --node-count "$(LAB_DEPLOY_NODE_COUNT)" --node-cpu "$(LAB_DEPLOY_NODE_CPU)" --node-memory "$(LAB_DEPLOY_NODE_MEMORY)" --utilization-limit "$(LAB_DEPLOY_UTILIZATION_LIMIT)" --max-pods "$(LAB_DEPLOY_MAX_PODS)" --max-databases "$(LAB_DEPLOY_MAX_DATABASES)" --max-imported-workloads "$(CAPACITY_PREFLIGHT_MAX_IMPORTED_WORKLOADS)" --import-batch "$(CAPACITY_PREFLIGHT_IMPORT_BATCH)" --capacity-evidence "$(CAPACITY_PREFLIGHT_EVIDENCE)" --output "$(CAPACITY_PREFLIGHT_OUTPUT)" --strict

image-cache-plan: ## Generate a public-safe image cache, preload, and cleanup plan.
	mkdir -p reports
	$(PYTHON) scripts/image_cache_plan.py --config "$(IMAGE_CACHE_CONFIG)" --profile "$(IMAGE_CACHE_PROFILE)" --output "$(IMAGE_CACHE_OUTPUT)" --image-mode "$(MIGRATION_IMAGE_MODE)" --private-dir "$(MIGRATION_PRIVATE_DIR)" --image-output-dir "$(MIGRATION_IMAGE_OUTPUT_DIR)" --rke2-image-dir "$(MIGRATION_RKE2_IMAGE_DIR)" --rke2-nodes "$(MIGRATION_RKE2_NODES)" --registry "$(MIGRATION_REGISTRY)" --container-tool "$(MIGRATION_CONTAINER_TOOL)" --image-tag "$(MIGRATION_IMAGE_TAG)" --cleanup-operator-images "$(MIGRATION_CLEANUP_OPERATOR_IMAGES)" --prune-operator-cache "$(MIGRATION_PRUNE_OPERATOR_CACHE)" --rke2-import-images "$(MIGRATION_RKE2_IMPORT_IMAGES)" --cleanup-node-import-images "$(MIGRATION_CLEANUP_NODE_IMPORT_IMAGES)" --cleanup-node-cri-images "$(MIGRATION_CLEANUP_NODE_CRI_IMAGES)" --cleanup-node-content-prune "$(MIGRATION_CLEANUP_NODE_CONTENT_PRUNE)" --cleanup-node-image-scope "$(MIGRATION_CLEANUP_NODE_IMAGE_SCOPE)" --node-archive-retention-hours "$(MIGRATION_NODE_ARCHIVE_RETENTION_HOURS)" $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

database-migration-plan: ## Generate a public-safe database dump/restore controller plan.
	mkdir -p reports
	$(PYTHON) scripts/database_migration_controller.py --config "$(DB_MIGRATION_CONFIG)" --values "$(VALUES)" --profile "$(DB_MIGRATION_PROFILE)" --output "$(DB_MIGRATION_OUTPUT)" --namespace "$(MIGRATION_NAMESPACE)" --dump-dir "$(MIGRATION_DUMP_DIR)" --db-targets "$(MIGRATION_DB_TARGETS)" --postgres-client-image "$(MIGRATION_POSTGRES_CLIENT_IMAGE)" --skip-unavailable-databases "$(MIGRATION_SKIP_UNAVAILABLE_DATABASES)" --allow-secret-material "$(MIGRATION_ALLOW_SECRET_MATERIAL)" $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

edge-migration-plan: ## Generate a public-safe ingress and edge migration plan.
	mkdir -p reports
	$(PYTHON) scripts/edge_migration_plan.py --config "$(EDGE_MIGRATION_CONFIG)" --values "$(VALUES)" --profile "$(EDGE_MIGRATION_PROFILE)" --output "$(EDGE_MIGRATION_OUTPUT)" --namespace "$(MIGRATION_NAMESPACE)" --ingress-class "$(INGRESS)" --webserver "$(WEB)" --ingress-host "$(MIGRATION_INGRESS_HOST)" --tls-mode "$(MIGRATION_TLS_MODE)" --tls-cert-file "$(MIGRATION_TLS_CERT_FILE)" --tls-key-file "$(MIGRATION_TLS_KEY_FILE)" --tls-extra-hosts "$(MIGRATION_TLS_EXTRA_HOSTS)" --tls-pfx-file "$(MIGRATION_TLS_PFX_FILE)" --tls-le-email "$(MIGRATION_TLS_LE_EMAIL)" --allowed-cidrs "$(DEPLOY_ALLOWED_CIDRS)" $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

environment-profile-plan: ## Generate a public-safe environment profile plan and Helm values overlay.
	mkdir -p reports
	$(PYTHON) scripts/environment_profile_plan.py --config "$(ENV_PROFILE_CONFIG)" --topologies config/deployment-topologies.yaml --profile "$(ENV_PROFILE)" --output "$(ENV_PROFILE_OUTPUT)" --overrides "$(ENV_PROFILE_VALUES)" --evidence-output "$(ENV_PROFILE_EVIDENCE)" $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

import-check: python-deps ## Check an external Compose project before importing or migrating it.
	@if [ -z "$(PROJECT_PATH)" ]; then \
		echo "Set PROJECT_PATH=/path/to/compose-project, for example: make import-check PROJECT_PATH=/path/to/compose-project"; \
		exit 2; \
	fi
	$(PYTHON) scripts/import_project.py --project-path "$(PROJECT_PATH)" --values "$(VALUES)" --ingress-controller "$(INGRESS)" --webserver "$(WEB)" --database "$(DB)" $(if $(IMPORT_REPORT),--report "$(IMPORT_REPORT)",) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,) $(if $(filter true,$(IMPORT_STRICT)),--strict,)

import-plan: MIGRATION_STAGE = prepare
import-plan: ## Generate private import diagnostics and action plan without applying changes.
	$(MAKE) import-migrate MIGRATION_STAGE=prepare MIGRATION_EXECUTE=false

import-preflight: MIGRATION_STAGE = preflight
import-preflight: MIGRATION_EXECUTE = true
import-preflight: ## Run cluster health preflight before import actions.
	@if [ -z "$(PROJECT_PATH)" ]; then \
		echo "Set PROJECT_PATH=/path/to/compose-project, for example: make import-preflight PROJECT_PATH=/path/to/compose-project"; \
		exit 2; \
	fi
	$(MAKE) operator-kubeconfig
	$(MAKE) import-migrate MIGRATION_STAGE=preflight MIGRATION_EXECUTE=true

import-recovery-plan: ## Generate a public-safe import resume, cleanup, and rollback plan.
	mkdir -p "$(MIGRATION_OUTPUT)"
	$(PYTHON) scripts/import_recovery_plan.py --output "$(IMPORT_RECOVERY_OUTPUT)" --migration-output "$(MIGRATION_OUTPUT)" --private-dir "$(MIGRATION_PRIVATE_DIR)" --state-file "$(MIGRATION_STATE_FILE)" --namespace "$(MIGRATION_NAMESPACE)" --profile "$(MIGRATION_PROFILE)" --image-mode "$(MIGRATION_IMAGE_MODE)" --import-batch "$(MIGRATION_IMPORT_BATCH)" --resume "$(MIGRATION_RESUME)" --force-rerun "$(MIGRATION_FORCE_RERUN)" --cleanup-operator-images "$(MIGRATION_CLEANUP_OPERATOR_IMAGES)" --prune-operator-cache "$(MIGRATION_PRUNE_OPERATOR_CACHE)" --rke2-import-images "$(MIGRATION_RKE2_IMPORT_IMAGES)" $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,)

import-migrate: python-deps ## Generate or execute guarded migration automation for an external Compose project.
	@if [ -z "$(PROJECT_PATH)" ]; then \
		echo "Set PROJECT_PATH=/path/to/compose-project, for example: make import-migrate PROJECT_PATH=/path/to/compose-project"; \
		exit 2; \
	fi
	$(PYTHON) scripts/migrate_project.py --project-path "$(PROJECT_PATH)" --values "$(VALUES)" --output "$(MIGRATION_OUTPUT)" --private-dir "$(MIGRATION_PRIVATE_DIR)" --namespace "$(MIGRATION_NAMESPACE)" --kubeconfig "$(MIGRATION_KUBECONFIG)" --ingress-host "$(MIGRATION_INGRESS_HOST)" --cluster-vip "$(MIGRATION_CLUSTER_VIP)" --tls-mode "$(MIGRATION_TLS_MODE)" --tls-cert-file "$(MIGRATION_TLS_CERT_FILE)" --tls-key-file "$(MIGRATION_TLS_KEY_FILE)" --tls-extra-hosts "$(MIGRATION_TLS_EXTRA_HOSTS)" --tls-pfx-file "$(MIGRATION_TLS_PFX_FILE)" --tls-pfx-password-file "$(MIGRATION_TLS_PFX_PASSWORD_FILE)" --tls-duration-days "$(MIGRATION_TLS_DURATION_DAYS)" --tls-le-email "$(MIGRATION_TLS_LE_EMAIL)" --tls-le-server "$(MIGRATION_TLS_LE_SERVER)" --tls-le-issuer-name "$(MIGRATION_TLS_LE_ISSUER_NAME)" --tls-le-issuer-kind "$(MIGRATION_TLS_LE_ISSUER_KIND)" --tls-le-private-key-secret "$(MIGRATION_TLS_LE_PRIVATE_KEY_SECRET)" $(if $(filter false,$(MIGRATION_TLS_LE_CREATE_ISSUER)),--tls-le-existing-issuer,--tls-le-create-issuer) --ingress-controller "$(INGRESS)" --webserver "$(WEB)" --database "$(DB)" --profile "$(MIGRATION_PROFILE)" --runtime-validation-timeout "$(MIGRATION_RUNTIME_VALIDATION_TIMEOUT)" --runtime-validation-interval "$(MIGRATION_RUNTIME_VALIDATION_INTERVAL)" --kafka-bootstrap-servers "$(MIGRATION_KAFKA_BOOTSTRAP_SERVERS)" --import-security-context "$(MIGRATION_IMPORT_SECURITY_CONTEXT)" --import-probe-mode "$(MIGRATION_IMPORT_PROBE_MODE)" --lab-workload-cpu-request "$(MIGRATION_LAB_WORKLOAD_CPU_REQUEST)" --lab-workload-memory-request "$(MIGRATION_LAB_WORKLOAD_MEMORY_REQUEST)" --lab-workload-cpu-limit "$(MIGRATION_LAB_WORKLOAD_CPU_LIMIT)" --lab-workload-memory-limit "$(MIGRATION_LAB_WORKLOAD_MEMORY_LIMIT)" --preflight-min-node-memory "$(MIGRATION_PREFLIGHT_MIN_NODE_MEMORY)" --preflight-min-node-disk-free "$(MIGRATION_PREFLIGHT_MIN_NODE_DISK_FREE)" --preflight-max-imported-workloads "$(MIGRATION_PREFLIGHT_MAX_IMPORTED_WORKLOADS)" --preflight-capacity-utilization-limit "$(MIGRATION_PREFLIGHT_CAPACITY_UTILIZATION_LIMIT)" --batch-size "$(MIGRATION_BATCH_SIZE)" --import-batch "$(MIGRATION_IMPORT_BATCH)" --service-filter "$(MIGRATION_SERVICE_FILTER)" --state-file "$(MIGRATION_STATE_FILE)" --image-mode "$(MIGRATION_IMAGE_MODE)" --image-output-dir "$(MIGRATION_IMAGE_OUTPUT_DIR)" --rke2-nodes "$(MIGRATION_RKE2_NODES)" --rke2-image-dir "$(MIGRATION_RKE2_IMAGE_DIR)" --ssh-user "$(MIGRATION_SSH_USER)" --ssh-key "$(MIGRATION_SSH_KEY)" --become-password-file "$(MIGRATION_BECOME_PASSWORD_FILE)" --container-tool "$(MIGRATION_CONTAINER_TOOL)" --postgres-client-image "$(MIGRATION_POSTGRES_CLIENT_IMAGE)" --registry "$(MIGRATION_REGISTRY)" --image-tag "$(MIGRATION_IMAGE_TAG)" --dump-dir "$(MIGRATION_DUMP_DIR)" --db-targets "$(MIGRATION_DB_TARGETS)" --secret-provider "$(MIGRATION_SECRET_PROVIDER)" --secret-remote-prefix "$(MIGRATION_SECRET_REMOTE_PREFIX)" --secret-store-name "$(MIGRATION_SECRET_STORE_NAME)" --secret-store-kind "$(MIGRATION_SECRET_STORE_KIND)" --secret-refresh-interval "$(MIGRATION_SECRET_REFRESH_INTERVAL)" --stage "$(MIGRATION_STAGE)" --cleanup-node-image-scope "$(MIGRATION_CLEANUP_NODE_IMAGE_SCOPE)" --node-archive-retention-hours "$(MIGRATION_NODE_ARCHIVE_RETENTION_HOURS)" $(if $(filter true,$(MIGRATION_PREFLIGHT_REQUIRE_INGRESS_ENDPOINT)),--preflight-require-ingress-endpoint,--no-preflight-require-ingress-endpoint) $(if $(filter false,$(MIGRATION_RESUME)),--no-resume,--resume) $(if $(filter true,$(MIGRATION_FORCE_RERUN)),--force-rerun,) $(if $(filter true,$(MIGRATION_AUTO_PREPARE)),--auto-prepare,) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,) $(if $(filter true,$(MIGRATION_EXECUTE)),--execute,) $(if $(filter true,$(MIGRATION_ALLOW_SECRET_MATERIAL)),--allow-secret-material,) $(if $(filter false,$(MIGRATION_RKE2_IMPORT_IMAGES)),--no-rke2-import-images,--rke2-import-images) $(if $(filter false,$(MIGRATION_CLEANUP_OPERATOR_IMAGES)),--no-cleanup-operator-images,--cleanup-operator-images) $(if $(filter false,$(MIGRATION_PRUNE_OPERATOR_CACHE)),--no-prune-operator-cache,--prune-operator-cache) $(if $(filter false,$(MIGRATION_CLEANUP_NODE_IMPORT_IMAGES)),--no-cleanup-node-import-images,--cleanup-node-import-images) $(if $(filter false,$(MIGRATION_CLEANUP_NODE_CRI_IMAGES)),--no-cleanup-node-cri-images,--cleanup-node-cri-images) $(if $(filter false,$(MIGRATION_CLEANUP_NODE_CONTENT_PRUNE)),--no-cleanup-node-content-prune,--cleanup-node-content-prune) $(if $(filter false,$(MIGRATION_SKIP_DOCKER_SOCKET_SERVICES)),--include-docker-socket-services,--skip-docker-socket-services) $(if $(filter false,$(MIGRATION_SKIP_UNAVAILABLE_DATABASES)),--strict-database-migration,--skip-unavailable-databases)

import-auto: MIGRATION_AUTO_REPAIR_CLUSTER = true
import-auto: operator-kubeconfig ## Run the full import migration workflow with preparation, execution, and validation.
	@if [ "$(MIGRATION_DEPLOY_PLATFORM)" = "true" ]; then \
		echo "Deploying/upgrading the platform chart before import so PostgreSQL 18 and platform services are reconciled."; \
		$(MAKE) deploy-auto VALUES="$(VALUES)" NAMESPACE="$(MIGRATION_NAMESPACE)" DEPLOY_NAMESPACE_RESOURCE_QUOTA="$(if $(filter true,$(MIGRATION_RELAX_RESOURCE_QUOTA)),false,$(DEPLOY_NAMESPACE_RESOURCE_QUOTA))"; \
	else \
		echo "Skipping platform Helm deploy because MIGRATION_DEPLOY_PLATFORM=$(MIGRATION_DEPLOY_PLATFORM)."; \
	fi
	$(MAKE) import-migrate PROJECT_PATH="$(PROJECT_PATH)" VALUES="$(VALUES)" INGRESS="$(INGRESS)" WEB="$(WEB)" DB="$(DB)" IMPORT_REDACT="$(IMPORT_REDACT)" IMPORT_STRICT="$(IMPORT_STRICT)" MIGRATION_STAGE=all MIGRATION_EXECUTE=true

$(ANSIBLE_COLLECTIONS_STAMP): $(ANSIBLE_COLLECTION_REQUIREMENTS) $(PYTHON_DEPS_STAMP)
	mkdir -p .ansible/collections
	ANSIBLE_CONFIG=$(ANSIBLE_CONFIG) $(ANSIBLE_GALAXY) collection install -r $(ANSIBLE_COLLECTION_REQUIREMENTS) --force
	touch $(ANSIBLE_COLLECTIONS_STAMP)

ansible-collections: python-deps $(ANSIBLE_COLLECTIONS_STAMP) ## Install repo-pinned Ansible collections.

preflight: ansible-collections ## Validate inventory and target readiness before bootstrap/install.
	ANSIBLE_CONFIG=$(ANSIBLE_CONFIG) $(ANSIBLE_PLAYBOOK) -i $(INVENTORY) ansible/playbooks/preflight.yml -e cluster_engine=$(ENGINE) -e deployment_environment=$(ENV) $(ANSIBLE_ARGS)

bootstrap-check: ansible-collections ## Dry-run bootstrap with Ansible check mode and diff.
	ANSIBLE_CONFIG=$(ANSIBLE_CONFIG) $(ANSIBLE_PLAYBOOK) -i $(INVENTORY) ansible/playbooks/bootstrap.yml -e cluster_engine=$(ENGINE) -e deployment_environment=$(ENV) --check $(ANSIBLE_DIFF) $(ANSIBLE_ARGS)

bootstrap: ansible-collections ## Bootstrap nodes with common packages, Chrony, HAProxy, Keepalived.
	$(call require_prod_confirmation)
	ANSIBLE_CONFIG=$(ANSIBLE_CONFIG) $(ANSIBLE_PLAYBOOK) -i $(INVENTORY) ansible/playbooks/bootstrap.yml -e cluster_engine=$(ENGINE) -e deployment_environment=$(ENV) $(ANSIBLE_ARGS)

install-cluster-check: ansible-collections ## Dry-run cluster install with Ansible check mode and diff.
	ANSIBLE_CONFIG=$(ANSIBLE_CONFIG) $(ANSIBLE_PLAYBOOK) -i $(INVENTORY) ansible/playbooks/install-cluster.yml -e cluster_engine=$(ENGINE) -e deployment_environment=$(ENV) --check $(ANSIBLE_DIFF) $(ANSIBLE_ARGS)

install-cluster: ansible-collections ## Install selected cluster engine: rke2, k3s, microk8s, docker, or raw.
	$(call require_prod_confirmation)
	ANSIBLE_CONFIG=$(ANSIBLE_CONFIG) $(ANSIBLE_PLAYBOOK) -i $(INVENTORY) ansible/playbooks/install-cluster.yml -e cluster_engine=$(ENGINE) -e deployment_environment=$(ENV) $(ANSIBLE_ARGS)

operator-kubeconfig: ansible-collections ## Repair/write the operator kubeconfig to the cluster VIP when needed.
	@ENV=$(ENV) ENGINE=$(ENGINE) INVENTORY=$(INVENTORY) ANSIBLE_CONFIG=$(ANSIBLE_CONFIG) ANSIBLE_PLAYBOOK=$(ANSIBLE_PLAYBOOK) OPERATOR_KUBECONFIG=$(OPERATOR_KUBECONFIG) OPERATOR_KUBECONFIG_FORCE_REPAIR="$(OPERATOR_KUBECONFIG_FORCE_REPAIR)" ANSIBLE_ARGS="$(ANSIBLE_ARGS)" MIGRATION_RKE2_NODES="$(MIGRATION_RKE2_NODES)" MIGRATION_SSH_USER="$(MIGRATION_SSH_USER)" MIGRATION_SSH_KEY="$(MIGRATION_SSH_KEY)" MIGRATION_BECOME_PASSWORD_FILE="$(MIGRATION_BECOME_PASSWORD_FILE)" MIGRATION_BECOME_PASSWORD_PROMPT="$(MIGRATION_BECOME_PASSWORD_PROMPT)" MIGRATION_CLUSTER_VIP="$(if $(MIGRATION_CLUSTER_VIP),$(MIGRATION_CLUSTER_VIP),$(DEPLOY_CLUSTER_VIP))" MIGRATION_KUBERNETES_API_VIP_PORT="$(MIGRATION_KUBERNETES_API_VIP_PORT)" MIGRATION_CLUSTER_DOMAIN="$(MIGRATION_CLUSTER_DOMAIN)" MIGRATION_RKE2_VERSION="$(MIGRATION_RKE2_VERSION)" MIGRATION_AUTO_REPAIR_CLUSTER="$(MIGRATION_AUTO_REPAIR_CLUSTER)" MIGRATION_KEEPALIVED_AUTH_PASS="$(MIGRATION_KEEPALIVED_AUTH_PASS)" MIGRATION_KEEPALIVED_INTERFACE="$(MIGRATION_KEEPALIVED_INTERFACE)" bash $(KUBECONFIG_SCRIPT)

configure-edge-ports: ansible-collections ## Configure HAProxy VIP forwarding for non-80/443 observability ports.
	@edge_inventory="$(INVENTORY)"; \
	if [ ! -s "$$edge_inventory" ] && [ -s "$(MIGRATION_FALLBACK_INVENTORY)" ]; then \
		edge_inventory="$(MIGRATION_FALLBACK_INVENTORY)"; \
		echo "Using recovered private inventory for edge ports: $$edge_inventory"; \
	fi; \
	if [ ! -s "$$edge_inventory" ]; then \
		echo "No usable inventory found for edge ports. Set INVENTORY or MIGRATION_FALLBACK_INVENTORY."; \
		exit 2; \
	fi; \
	ANSIBLE_CONFIG=$(ANSIBLE_CONFIG) $(ANSIBLE_PLAYBOOK) -i "$$edge_inventory" ansible/playbooks/edge-ports.yml -e cluster_engine=$(ENGINE) -e deployment_environment=$(ENV) -e edge_allowed_cidrs_text="$(DEPLOY_ALLOWED_CIDRS)" -e edge_observability_ports_enabled="$(DEPLOY_EDGE_OBSERVABILITY_PORTS)" $(ANSIBLE_ARGS)

install-helm: ## Install or align Helm on the operator machine.
	bash $(HELM_INSTALL_SCRIPT)

install-helmfile: install-helm ## Install or align Helmfile on the operator machine.
	bash $(HELMFILE_INSTALL_SCRIPT)

install-local-path-storage: operator-kubeconfig ## Install Rancher local-path dynamic storage for lab/small clusters.
	KUBECONFIG=$(OPERATOR_KUBECONFIG) LOCAL_PATH_PROVISIONER_VERSION=$(LOCAL_PATH_PROVISIONER_VERSION) LOCAL_PATH_STORAGE_CLASS=$(LOCAL_PATH_STORAGE_CLASS) LOCAL_PATH_STORAGE_DEFAULT=$(LOCAL_PATH_STORAGE_DEFAULT) LOCAL_PATH_STORAGE_PATH=$(LOCAL_PATH_STORAGE_PATH) LOCAL_PATH_PREPARE_HOST_PATHS=$(LOCAL_PATH_PREPARE_HOST_PATHS) MIGRATION_RKE2_NODES="$(MIGRATION_RKE2_NODES)" MIGRATION_SSH_USER="$(MIGRATION_SSH_USER)" MIGRATION_SSH_KEY="$(MIGRATION_SSH_KEY)" MIGRATION_BECOME_PASSWORD_FILE="$(MIGRATION_BECOME_PASSWORD_FILE)" MIGRATION_BECOME_PASSWORD_PROMPT="$(MIGRATION_BECOME_PASSWORD_PROMPT)" bash $(LOCAL_PATH_INSTALL_SCRIPT)

ensure-storageclass: operator-kubeconfig ## Ensure the cluster has a StorageClass before installing stateful workloads.
	@if KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl get storageclass $(LOCAL_PATH_STORAGE_CLASS) >/dev/null 2>&1 && { [ "$(INSTALL_LOCAL_PATH_STORAGE)" = "auto" ] || [ "$(INSTALL_LOCAL_PATH_STORAGE)" = "true" ]; }; then \
		echo "Local-path StorageClass already present; reconciling provisioner and host paths."; \
		KUBECONFIG=$(OPERATOR_KUBECONFIG) LOCAL_PATH_PROVISIONER_VERSION=$(LOCAL_PATH_PROVISIONER_VERSION) LOCAL_PATH_STORAGE_CLASS=$(LOCAL_PATH_STORAGE_CLASS) LOCAL_PATH_STORAGE_DEFAULT=$(LOCAL_PATH_STORAGE_DEFAULT) LOCAL_PATH_STORAGE_PATH=$(LOCAL_PATH_STORAGE_PATH) LOCAL_PATH_PREPARE_HOST_PATHS=$(LOCAL_PATH_PREPARE_HOST_PATHS) MIGRATION_RKE2_NODES="$(MIGRATION_RKE2_NODES)" MIGRATION_SSH_USER="$(MIGRATION_SSH_USER)" MIGRATION_SSH_KEY="$(MIGRATION_SSH_KEY)" MIGRATION_BECOME_PASSWORD_FILE="$(MIGRATION_BECOME_PASSWORD_FILE)" MIGRATION_BECOME_PASSWORD_PROMPT="$(MIGRATION_BECOME_PASSWORD_PROMPT)" bash $(LOCAL_PATH_INSTALL_SCRIPT); \
	elif KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl get storageclass -o name 2>/dev/null | grep -q .; then \
		echo "StorageClass already present."; \
	elif [ "$(INSTALL_LOCAL_PATH_STORAGE)" = "auto" ] || [ "$(INSTALL_LOCAL_PATH_STORAGE)" = "true" ]; then \
		KUBECONFIG=$(OPERATOR_KUBECONFIG) LOCAL_PATH_PROVISIONER_VERSION=$(LOCAL_PATH_PROVISIONER_VERSION) LOCAL_PATH_STORAGE_CLASS=$(LOCAL_PATH_STORAGE_CLASS) LOCAL_PATH_STORAGE_DEFAULT=$(LOCAL_PATH_STORAGE_DEFAULT) LOCAL_PATH_STORAGE_PATH=$(LOCAL_PATH_STORAGE_PATH) LOCAL_PATH_PREPARE_HOST_PATHS=$(LOCAL_PATH_PREPARE_HOST_PATHS) MIGRATION_RKE2_NODES="$(MIGRATION_RKE2_NODES)" MIGRATION_SSH_USER="$(MIGRATION_SSH_USER)" MIGRATION_SSH_KEY="$(MIGRATION_SSH_KEY)" MIGRATION_BECOME_PASSWORD_FILE="$(MIGRATION_BECOME_PASSWORD_FILE)" MIGRATION_BECOME_PASSWORD_PROMPT="$(MIGRATION_BECOME_PASSWORD_PROMPT)" bash $(LOCAL_PATH_INSTALL_SCRIPT); \
	else \
		echo "No StorageClass exists. Install a CSI provisioner or rerun with INSTALL_LOCAL_PATH_STORAGE=true."; \
		exit 2; \
	fi

wait-operator-crds: ## Wait until CRDs required by the default platform chart exist.
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl wait --for=condition=Established crd/clusters.postgresql.cnpg.io --timeout=$(OPERATOR_CRD_TIMEOUT)
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl wait --for=condition=Established crd/imagecatalogs.postgresql.cnpg.io --timeout=$(OPERATOR_CRD_TIMEOUT)
	@if [ "$(DEPLOY_ENABLE_ECK)" = "true" ]; then \
		KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl wait --for=condition=Established crd/elasticsearches.elasticsearch.k8s.elastic.co --timeout=$(OPERATOR_CRD_TIMEOUT); \
		KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl wait --for=condition=Established crd/kibanas.kibana.k8s.elastic.co --timeout=$(OPERATOR_CRD_TIMEOUT); \
	else \
		echo "Skipping ECK CRD wait because DEPLOY_ENABLE_ECK=false."; \
	fi
	@if [ "$(DEPLOY_ENABLE_STRIMZI)" = "true" ]; then \
		KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl wait --for=condition=Established crd/kafkas.kafka.strimzi.io --timeout=$(OPERATOR_CRD_TIMEOUT); \
		KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl wait --for=condition=Established crd/kafkanodepools.kafka.strimzi.io --timeout=$(OPERATOR_CRD_TIMEOUT); \
		KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl -n strimzi-system rollout status deployment/strimzi-cluster-operator --timeout=$(OPERATOR_CRD_TIMEOUT); \
	else \
		echo "Skipping Strimzi CRD wait because DEPLOY_ENABLE_STRIMZI=false."; \
	fi
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl -n cnpg-system rollout status deployment/cloudnative-pg --timeout=$(OPERATOR_CRD_TIMEOUT)

install-operators: install-helmfile operator-kubeconfig ensure-storageclass ## Install optional operators/charts needed for HA data and observability profiles.
	KUBECONFIG=$(OPERATOR_KUBECONFIG) OPERATOR_KUBECONFIG=$(OPERATOR_KUBECONFIG) NAMESPACE="$(NAMESPACE)" DEPLOY_ENABLE_STRIMZI="$(DEPLOY_ENABLE_STRIMZI)" STRIMZI_OPERATOR_CHART_VERSION="$(STRIMZI_OPERATOR_CHART_VERSION)" STRIMZI_OPERATOR_TIMEOUT="$(STRIMZI_OPERATOR_TIMEOUT)" STRIMZI_WATCH_NAMESPACES="$(STRIMZI_WATCH_NAMESPACES)" STRIMZI_WATCH_ANY_NAMESPACE="$(STRIMZI_WATCH_ANY_NAMESPACE)" STRIMZI_PRELOAD_IMAGES="$(STRIMZI_PRELOAD_IMAGES)" STRIMZI_KAFKA_VERSION="$(STRIMZI_KAFKA_VERSION)" RKE2_IMAGE_PRELOAD_SCRIPT="$(RKE2_IMAGE_PRELOAD_SCRIPT)" MIGRATION_IMAGE_MODE="$(MIGRATION_IMAGE_MODE)" MIGRATION_IMAGE_OUTPUT_DIR="$(MIGRATION_IMAGE_OUTPUT_DIR)" MIGRATION_RKE2_IMAGE_DIR="$(MIGRATION_RKE2_IMAGE_DIR)" MIGRATION_RKE2_NODES="$(MIGRATION_RKE2_NODES)" MIGRATION_SSH_USER="$(MIGRATION_SSH_USER)" MIGRATION_SSH_KEY="$(MIGRATION_SSH_KEY)" MIGRATION_CONTAINER_TOOL="$(MIGRATION_CONTAINER_TOOL)" MIGRATION_FALLBACK_INVENTORY="$(MIGRATION_FALLBACK_INVENTORY)" bash $(STRIMZI_INSTALL_SCRIPT)
	KUBECONFIG=$(OPERATOR_KUBECONFIG) OPERATOR_KUBECONFIG=$(OPERATOR_KUBECONFIG) HELMFILE=$(HELMFILE) HELMFILE_CONFIG=$(HELMFILE_CONFIG) HELMFILE_SYNC_RETRIES=$(HELMFILE_SYNC_RETRIES) HELMFILE_SYNC_RETRY_DELAY=$(HELMFILE_SYNC_RETRY_DELAY) HELMFILE_SYNC_ATTEMPT_TIMEOUT=$(HELMFILE_SYNC_ATTEMPT_TIMEOUT) SKIP_HELMFILE_SYNC="$(SKIP_HELMFILE_SYNC)" KUBECONFIG_SCRIPT=$(KUBECONFIG_SCRIPT) ENV=$(ENV) ENGINE=$(ENGINE) INVENTORY=$(INVENTORY) ANSIBLE_CONFIG=$(ANSIBLE_CONFIG) ANSIBLE_PLAYBOOK=$(ANSIBLE_PLAYBOOK) ANSIBLE_ARGS="$(ANSIBLE_ARGS)" MIGRATION_RKE2_NODES="$(MIGRATION_RKE2_NODES)" MIGRATION_SSH_USER="$(MIGRATION_SSH_USER)" MIGRATION_SSH_KEY="$(MIGRATION_SSH_KEY)" MIGRATION_BECOME_PASSWORD_FILE="$(MIGRATION_BECOME_PASSWORD_FILE)" MIGRATION_BECOME_PASSWORD_PROMPT="$(MIGRATION_BECOME_PASSWORD_PROMPT)" MIGRATION_CLUSTER_VIP="$(if $(MIGRATION_CLUSTER_VIP),$(MIGRATION_CLUSTER_VIP),$(DEPLOY_CLUSTER_VIP))" MIGRATION_KUBERNETES_API_VIP_PORT="$(MIGRATION_KUBERNETES_API_VIP_PORT)" MIGRATION_CLUSTER_DOMAIN="$(MIGRATION_CLUSTER_DOMAIN)" MIGRATION_RKE2_VERSION="$(MIGRATION_RKE2_VERSION)" MIGRATION_KEEPALIVED_AUTH_PASS="$(MIGRATION_KEEPALIVED_AUTH_PASS)" MIGRATION_KEEPALIVED_INTERFACE="$(MIGRATION_KEEPALIVED_INTERFACE)" INSTALL_ECK="$(DEPLOY_ENABLE_ECK)" INSTALL_PROMETHEUS="$(DEPLOY_ENABLE_PROMETHEUS)" GRAFANA_ENABLED="$(DEPLOY_ENABLE_GRAFANA)" INSTALL_OPENTELEMETRY="$(DEPLOY_ENABLE_OPENTELEMETRY)" INSTALL_LOKI="$(DEPLOY_ENABLE_LOKI)" INSTALL_CLICKHOUSE="$(DEPLOY_ENABLE_CLICKHOUSE)" INSTALL_VELERO="$(DEPLOY_ENABLE_VELERO)" INSTALL_MINIO="$(DEPLOY_ENABLE_MINIO)" INSTALL_RABBITMQ="$(DEPLOY_ENABLE_RABBITMQ)" INSTALL_KEYCLOAK="$(DEPLOY_ENABLE_KEYCLOAK)" INSTALL_EMQX="$(DEPLOY_ENABLE_EMQX)" INSTALL_NATS="$(DEPLOY_ENABLE_NATS)" INSTALL_STRIMZI="false" INSTALL_VAULT="$(DEPLOY_ENABLE_VAULT)" INSTALL_KYVERNO="$(DEPLOY_ENABLE_KYVERNO)" INSTALL_TEMPORAL="$(DEPLOY_ENABLE_TEMPORAL)" INSTALL_ARGO_WORKFLOWS="$(DEPLOY_ENABLE_ARGO_WORKFLOWS)" INSTALL_LINKERD="$(DEPLOY_ENABLE_LINKERD)" INSTALL_ISTIO="$(DEPLOY_ENABLE_ISTIO)" VELERO_PROVIDER="$(VELERO_PROVIDER)" VELERO_BUCKET="$(VELERO_BUCKET)" VELERO_PREFIX="$(VELERO_PREFIX)" VELERO_REGION="$(VELERO_REGION)" VELERO_S3_URL="$(VELERO_S3_URL)" VELERO_S3_FORCE_PATH_STYLE="$(VELERO_S3_FORCE_PATH_STYLE)" VELERO_USE_SECRET="$(VELERO_USE_SECRET)" VELERO_EXISTING_SECRET="$(VELERO_EXISTING_SECRET)" VELERO_SNAPSHOTS_ENABLED="$(VELERO_SNAPSHOTS_ENABLED)" VELERO_NODE_AGENT_ENABLED="$(VELERO_NODE_AGENT_ENABLED)" GRAFANA_SERVICE_TYPE="$(DEPLOY_OBSERVABILITY_SERVICE_TYPE)" GRAFANA_NODE_PORT="$(DEPLOY_GRAFANA_NODE_PORT)" LOKI_SERVICE_TYPE="$(DEPLOY_OBSERVABILITY_SERVICE_TYPE)" LOKI_NODE_PORT="$(DEPLOY_LOKI_NODE_PORT)" CLICKHOUSE_SERVICE_TYPE="$(DEPLOY_OBSERVABILITY_SERVICE_TYPE)" CLICKHOUSE_HTTP_NODE_PORT="$(DEPLOY_CLICKHOUSE_HTTP_NODE_PORT)" CLICKHOUSE_TCP_NODE_PORT="$(DEPLOY_CLICKHOUSE_TCP_NODE_PORT)" bash $(HELMFILE_SYNC_SCRIPT)
	$(MAKE) wait-operator-crds OPERATOR_CRD_TIMEOUT=$(OPERATOR_CRD_TIMEOUT) OPERATOR_KUBECONFIG=$(OPERATOR_KUBECONFIG) DEPLOY_ENABLE_ECK=$(DEPLOY_ENABLE_ECK) DEPLOY_ENABLE_STRIMZI=$(DEPLOY_ENABLE_STRIMZI)

ensure-namespace: ## Create and label the target namespace before deploying the platform chart.
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl get namespace $(NAMESPACE) >/dev/null 2>&1 || \
		KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl create namespace $(NAMESPACE)
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl label namespace $(NAMESPACE) pod-security.kubernetes.io/enforce=baseline pod-security.kubernetes.io/audit=restricted pod-security.kubernetes.io/warn=restricted pod-security.kubernetes.io/enforce-version=latest pod-security.kubernetes.io/audit-version=latest pod-security.kubernetes.io/warn-version=latest --overwrite
	@if [ "$(DEPLOY_NAMESPACE_RESOURCE_QUOTA)" = "false" ]; then \
		echo "ResourceQuota disabled for this deploy; removing stale $(PROJECT)-quota if present."; \
		KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl -n $(NAMESPACE) delete resourcequota $(PROJECT)-quota --ignore-not-found; \
	fi

recover-helm-release: operator-kubeconfig ensure-namespace ## Recover a failed, uninstalling, or stale platform Helm release before redeploying.
	KUBECONFIG=$(OPERATOR_KUBECONFIG) HELM=$(HELM) PROJECT=$(PROJECT) NAMESPACE=$(NAMESPACE) HELM_TIMEOUT=$(HELM_TIMEOUT) DEPLOY_RECOVER_FAILED_RELEASE=$(DEPLOY_RECOVER_FAILED_RELEASE) DEPLOY_RECOVER_STALE_RESOURCES=$(DEPLOY_RECOVER_STALE_RESOURCES) DEPLOY_RECOVER_PENDING_PVCS=$(DEPLOY_RECOVER_PENDING_PVCS) DEPLOY_RECOVER_DELETE_PVCS=$(DEPLOY_RECOVER_DELETE_PVCS) DEPLOY_RECOVER_STATEFULSETS=$(DEPLOY_RECOVER_STATEFULSETS) DEPLOY_RECOVER_CNPG_INITDB=$(DEPLOY_RECOVER_CNPG_INITDB) bash $(HELM_RECOVERY_SCRIPT)

deploy-dry-run: install-helm ## Render the Helm chart without applying it.
	$(HELM) template $(PROJECT) helm/urban-platform-infra --namespace $(NAMESPACE) -f $(VALUES) -f $(TOPOLOGY_VALUES) --dry-run > rendered.yaml

policy: ## Run policy checks against rendered manifests.
	mkdir -p reports
	$(HELM) template $(PROJECT) helm/urban-platform-infra --namespace $(NAMESPACE) -f $(VALUES) -f $(TOPOLOGY_VALUES) > reports/rendered.yaml
	$(PYTHON) tests/policy/basic_policy.py reports/rendered.yaml

package-chart: install-helm ## Package the Helm chart into dist/.
	mkdir -p dist
	$(HELM) dependency build helm/urban-platform-infra
	$(HELM) lint helm/urban-platform-infra
	$(HELM) package helm/urban-platform-infra -d dist

release-evidence: package-chart ## Generate rendered manifest, SPDX SBOM, and checksums for a release.
	$(HELM) template $(PROJECT) helm/urban-platform-infra --namespace $(NAMESPACE) -f $(VALUES) > dist/rendered.yaml
	$(PYTHON) scripts/release/generate_sbom.py --chart helm/urban-platform-infra --dist dist --rendered dist/rendered.yaml --sbom dist/urban-platform-infra.spdx.json --manifest dist/release-evidence.json --checksums dist/SHA256SUMS
	$(PYTHON) scripts/release/verify_release_evidence.py --chart helm/urban-platform-infra --policy config/supply-chain-policy.yaml --tag "$(RELEASE_TAG)" --report "$(RELEASE_VERIFY_REPORT)"

verify-release-evidence: ## Verify existing release evidence without rebuilding artifacts.
	$(PYTHON) scripts/release/verify_release_evidence.py --chart helm/urban-platform-infra --policy config/supply-chain-policy.yaml --tag "$(RELEASE_TAG)" --report "$(RELEASE_VERIFY_REPORT)"

deploy: install-operators ensure-namespace recover-helm-release ## Deploy/upgrade the HA application platform.
	@if [ "$(DEPLOY_CONFIGURE_EDGE_PORTS)" = "true" ]; then \
		$(MAKE) configure-edge-ports ENV=$(ENV) ENGINE=$(ENGINE) INVENTORY=$(INVENTORY) ANSIBLE_CONFIG=$(ANSIBLE_CONFIG) ANSIBLE_PLAYBOOK=$(ANSIBLE_PLAYBOOK) ANSIBLE_ARGS="$(ANSIBLE_ARGS)" DEPLOY_ALLOWED_CIDRS="$(DEPLOY_ALLOWED_CIDRS)"; \
	fi
	@attempt=1; \
	while true; do \
		echo "Running Helm upgrade/install (attempt $$attempt/$(HELM_DEPLOY_RETRIES))."; \
		if KUBECONFIG=$(OPERATOR_KUBECONFIG) $(HELM) upgrade --install $(PROJECT) helm/urban-platform-infra --namespace $(NAMESPACE) --cleanup-on-fail --timeout $(HELM_TIMEOUT) $(HELM_DEPLOY_SET_ARGS) -f $(VALUES) -f $(TOPOLOGY_VALUES) $(HELM_EXTRA_ARGS); then \
			break; \
		fi; \
		status=$$?; \
		if [ "$$attempt" -ge "$(HELM_DEPLOY_RETRIES)" ]; then \
			exit "$$status"; \
		fi; \
		echo "Helm upgrade failed; retrying in $(HELM_DEPLOY_RETRY_DELAY)s."; \
		sleep "$(HELM_DEPLOY_RETRY_DELAY)"; \
		attempt=$$((attempt + 1)); \
	done

deploy-auto: DEPLOY_RECOVER_FAILED_RELEASE = true
deploy-auto: DEPLOY_RECOVER_STATEFULSETS = true
deploy-auto: DEPLOY_RECOVER_CNPG_INITDB = true
deploy-auto: DEPLOY_LAB_STORAGE = true
deploy-auto: DEPLOY_SKIP_PLACEHOLDER_WORKLOADS = true
deploy-auto: DEPLOY_REDIS_SENTINEL = false
deploy-auto: DEPLOY_TLS_SECRET_NAME = urban-platform-tls
deploy-auto: DEPLOY_TLS_CREATE_SECRET = false
deploy-auto: DEPLOY_CONFIGURE_EDGE_PORTS = true
deploy-auto: DEPLOY_NAMESPACE_RESOURCE_QUOTA = false
deploy-auto: MIGRATION_AUTO_REPAIR_CLUSTER = true
deploy-auto: deploy ## Automatically recover common lab/import deploy failures and use compact local-path storage sizes.

deploy-strimzi-kafka: DEPLOY_ENABLE_STRIMZI = true
deploy-strimzi-kafka: DEPLOY_NAMESPACE_RESOURCE_QUOTA = false
deploy-strimzi-kafka: STRIMZI_PRELOAD_IMAGES = true
deploy-strimzi-kafka: HELM_EXTRA_ARGS += --set messaging.kafka.versionProfile=apache-4.2-strimzi --set messaging.kafka.provider=strimzi --set messaging.kafka.mode=operator --set messaging.kafka.strimzi.apiVersion=kafka.strimzi.io/v1 --set messaging.kafka.strimzi.kafkaVersion=$(STRIMZI_KAFKA_VERSION) --set messaging.kafka.zookeeper.enabled=false
deploy-strimzi-kafka: deploy-auto ## Deploy Apache Kafka through Strimzi with automatic RKE2 image preload and lab quota relaxation.

status: ## Show cluster and workload status.
	KUBECONFIG=$(OPERATOR_KUBECONFIG) scripts/health/status.sh $(NAMESPACE)

observability-status: ## Show monitoring and observability resources.
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl -n $(NAMESPACE) get prometheusrules.monitoring.coreos.com,servicemonitors.monitoring.coreos.com 2>/dev/null || true
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl -n observability get pods,svc 2>/dev/null || true

docker-up: ## Start Docker fallback profile. Use Docker Swarm for replicas.
	docker compose -f compose/docker-compose.ha.yml up -d

docker-down: ## Stop Docker fallback profile.
	docker compose -f compose/docker-compose.ha.yml down

docker-status: ## Show Docker fallback profile status.
	docker compose -f compose/docker-compose.ha.yml ps

docker-standalone-config: ## Generate private standalone Docker nginx/TLS runtime config from .env.standalone.
	STANDALONE_ENV_FILE="$(STANDALONE_ENV_FILE)" bash scripts/tools/standalone-docker-config.sh

docker-standalone-up: docker-standalone-config ## Start standalone Docker profile with local IP/FQDN/TLS overrides.
	@env_flag=""; \
	if [ -f "$(STANDALONE_ENV_FILE)" ]; then env_flag="--env-file $(STANDALONE_ENV_FILE)"; fi; \
	docker compose $$env_flag -f compose/docker-compose.ha.yml -f compose/docker-compose.standalone.yml up -d

docker-standalone-down: ## Stop standalone Docker profile.
	@env_flag=""; \
	if [ -f "$(STANDALONE_ENV_FILE)" ]; then env_flag="--env-file $(STANDALONE_ENV_FILE)"; fi; \
	docker compose $$env_flag -f compose/docker-compose.ha.yml -f compose/docker-compose.standalone.yml down

docker-standalone-status: ## Show standalone Docker profile status.
	@env_flag=""; \
	if [ -f "$(STANDALONE_ENV_FILE)" ]; then env_flag="--env-file $(STANDALONE_ENV_FILE)"; fi; \
	docker compose $$env_flag -f compose/docker-compose.ha.yml -f compose/docker-compose.standalone.yml ps

clean: ## Remove generated local files.
	rm -rf rendered.yaml reports dist $(ANSIBLE_COLLECTIONS_STAMP)
