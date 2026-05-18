SHELL := /usr/bin/env bash
PROJECT ?= urban-platform-infra
ENV ?= prod
ENGINE ?= rke2
INGRESS ?= traefik
WEB ?= nginx
DB ?= postgresql
OBS ?= elasticsearch
NAMESPACE ?= urban-platform
VALUES ?= helm/urban-platform-infra/values.yaml
TOPOLOGY ?= three-node-ha
TOPOLOGY_VALUES ?= helm/urban-platform-infra/topologies/$(TOPOLOGY).yaml
INVENTORY ?= inventories/$(ENV)/hosts.yml
ANSIBLE_CONFIG ?= ansible/ansible.cfg
ANSIBLE_ARGS ?=
ANSIBLE_DIFF ?= --diff
VENV ?= .venv
VENV_BIN := $(VENV)/bin
VENV_PYTHON := $(wildcard $(VENV_BIN)/python3)
PYTHON ?= $(if $(VENV_PYTHON),$(VENV_BIN)/python3,python3)
PIP ?= $(PYTHON) -m pip
ANSIBLE_PLAYBOOK ?= $(if $(VENV_PYTHON),$(VENV_BIN)/ansible-playbook,ansible-playbook)
ANSIBLE_GALAXY ?= $(if $(VENV_PYTHON),$(VENV_BIN)/ansible-galaxy,ansible-galaxy)
ANSIBLE_COLLECTION_REQUIREMENTS ?= ansible/requirements.yml
ANSIBLE_COLLECTIONS_STAMP ?= .ansible/collections/.$(subst /,_,$(ANSIBLE_COLLECTION_REQUIREMENTS)).stamp
PYTHON_DEPS_STAMP ?= .ansible/.python-deps.stamp
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
HELMFILE_SYNC_RETRIES ?= 4
HELMFILE_SYNC_RETRY_DELAY ?= 20
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
DEPLOY_LAB_STORAGE ?= false
DEPLOY_LAB_REPLICA_OVERRIDE ?= 1
DEPLOY_LAB_AUTOSCALING ?= false
DEPLOY_LAB_TOPOLOGY_SPREAD ?= false
DEPLOY_SKIP_PLACEHOLDER_WORKLOADS ?= false
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
DEPLOY_ENABLE_LOKI ?= true
DEPLOY_ENABLE_CLICKHOUSE ?= true
DEPLOY_OBSERVABILITY_SERVICE_TYPE ?= NodePort
DEPLOY_KIBANA_NODE_PORT ?= 30561
DEPLOY_ELASTICSEARCH_NODE_PORT ?= 30920
DEPLOY_GRAFANA_NODE_PORT ?= 30300
DEPLOY_LOKI_NODE_PORT ?= 30310
DEPLOY_CLICKHOUSE_HTTP_NODE_PORT ?= 30812
DEPLOY_CLICKHOUSE_TCP_NODE_PORT ?= 30900
DEPLOY_DATABASE_STORAGE_SIZE ?= 2Gi
DEPLOY_DATABASE_STORAGE_CLASS ?= $(LOCAL_PATH_STORAGE_CLASS)
DEPLOY_ELASTICSEARCH_STORAGE ?= 5Gi
DEPLOY_KAFKA_STORAGE ?= 5Gi
DEPLOY_ZOOKEEPER_STORAGE ?= 2Gi
DEPLOY_REDIS_STORAGE ?= 2Gi
DEPLOY_REDIS_SENTINEL ?= true
DEPLOY_INGRESS_HOST ?= $(MIGRATION_INGRESS_HOST)
DEPLOY_CLUSTER_DOMAIN ?= $(if $(MIGRATION_CLUSTER_DOMAIN),$(MIGRATION_CLUSTER_DOMAIN),$(DEPLOY_INGRESS_HOST))
DEPLOY_CLUSTER_VIP ?= $(MIGRATION_CLUSTER_VIP)
DEPLOY_TLS_SECRET_NAME ?=
DEPLOY_TLS_CREATE_SECRET ?=
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
MIGRATION_TLS_CERT_FILE ?=
MIGRATION_TLS_KEY_FILE ?=
MIGRATION_RKE2_VERSION ?=
MIGRATION_AUTO_REPAIR_CLUSTER ?= false
MIGRATION_KEEPALIVED_AUTH_PASS ?=
MIGRATION_KEEPALIVED_INTERFACE ?=
MIGRATION_IMAGE_MODE ?= registry
MIGRATION_IMAGE_OUTPUT_DIR ?= $(MIGRATION_PRIVATE_DIR)/images
MIGRATION_RKE2_NODES ?=
MIGRATION_RKE2_IMAGE_DIR ?= /var/lib/rancher/rke2/agent/images
MIGRATION_RKE2_IMPORT_IMAGES ?= true
MIGRATION_CLEANUP_OPERATOR_IMAGES ?= true
MIGRATION_PRUNE_OPERATOR_CACHE ?= true
MIGRATION_SKIP_DOCKER_SOCKET_SERVICES ?= true
MIGRATION_SKIP_UNAVAILABLE_DATABASES ?= true
MIGRATION_SSH_USER ?= root
MIGRATION_SSH_KEY ?=
MIGRATION_BECOME_PASSWORD_FILE ?=
MIGRATION_BECOME_PASSWORD_PROMPT ?= auto
MIGRATION_CONTAINER_TOOL ?= auto
MIGRATION_POSTGRES_CLIENT_IMAGE ?= docker.io/library/postgres:18.3
MIGRATION_REGISTRY ?=
MIGRATION_IMAGE_TAG ?= imported-0.1.0
MIGRATION_NAMESPACE ?= $(NAMESPACE)
MIGRATION_DUMP_DIR ?= $(MIGRATION_PRIVATE_DIR)/db-dumps
MIGRATION_DB_TARGETS ?= $(MIGRATION_PRIVATE_DIR)/db-targets.yaml

.PHONY: help validate image-policy lint configure import-check import-plan import-migrate import-auto python-deps ansible-collections preflight bootstrap-check bootstrap install-cluster-check install-cluster operator-kubeconfig configure-edge-ports install-helm install-helmfile install-local-path-storage ensure-storageclass install-operators wait-operator-crds ensure-namespace recover-helm-release deploy deploy-auto deploy-dry-run package-chart release-evidence status observability-status docker-up docker-down docker-status policy clean

HELM_DEPLOY_SET_ARGS = \
	--set namespace.create=false \
	$(if $(DEPLOY_INGRESS_HOST),--set ingress.host=$(DEPLOY_INGRESS_HOST),) \
	$(if $(DEPLOY_CLUSTER_DOMAIN),--set global.cluster.domain=$(DEPLOY_CLUSTER_DOMAIN),) \
	$(if $(DEPLOY_CLUSTER_VIP),--set global.cluster.vip=$(DEPLOY_CLUSTER_VIP),) \
	$(if $(DEPLOY_TLS_SECRET_NAME),--set ingress.tls.secretName=$(DEPLOY_TLS_SECRET_NAME),) \
	$(if $(DEPLOY_TLS_CREATE_SECRET),--set ingress.tls.createSecret=$(DEPLOY_TLS_CREATE_SECRET),) \
	$(if $(filter true,$(DEPLOY_SKIP_PLACEHOLDER_WORKLOADS)),--set global.skipPlaceholderWorkloads=true,) \
	$(if $(DEPLOY_ROOT_IMAGE_REPOSITORY),--set workloads.$(DEPLOY_ROOT_WORKLOAD).image.repository=$(DEPLOY_ROOT_IMAGE_REPOSITORY),) \
	$(if $(DEPLOY_ROOT_IMAGE_TAG),--set-string workloads.$(DEPLOY_ROOT_WORKLOAD).image.tag=$(DEPLOY_ROOT_IMAGE_TAG),) \
	$(if $(DEPLOY_ROOT_CONTAINER_PORT),--set 'workloads.$(DEPLOY_ROOT_WORKLOAD).ports[0].containerPort=$(DEPLOY_ROOT_CONTAINER_PORT)',) \
	$(if $(DEPLOY_ROOT_SERVICE_PORT),--set 'workloads.$(DEPLOY_ROOT_WORKLOAD).ports[0].servicePort=$(DEPLOY_ROOT_SERVICE_PORT)',) \
	$(if $(DEPLOY_ROOT_PROBE_PORT),--set workloads.$(DEPLOY_ROOT_WORKLOAD).probe.port=$(DEPLOY_ROOT_PROBE_PORT),) \
	$(if $(DEPLOY_ROOT_INGRESS_ENABLED),--set workloads.$(DEPLOY_ROOT_WORKLOAD).ingress.enabled=$(DEPLOY_ROOT_INGRESS_ENABLED),) \
	$(if $(DEPLOY_ROOT_INGRESS_PATH),--set workloads.$(DEPLOY_ROOT_WORKLOAD).ingress.path=$(DEPLOY_ROOT_INGRESS_PATH),) \
	$(if $(DEPLOY_ALLOWED_CIDRS),--set ingress.sourceAllowList.enabled=true --set-string ingress.sourceAllowList.cidrsText="$(DEPLOY_ALLOWED_CIDRS)",) \
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
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make <target> [ENV=prod ENGINE=rke2 INGRESS=traefik WEB=nginx DB=postgresql OBS=elasticsearch TOPOLOGY=three-node-ha]\n\nTargets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  %-22s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

$(PYTHON_DEPS_STAMP): requirements-ci.txt requirements-ci-modern.txt
	mkdir -p .ansible
	@$(install_python_deps)

python-deps: $(PYTHON_DEPS_STAMP) ## Install Python/Ansible dependencies compatible with the current Python.
	@if ! $(PYTHON) -c 'import ansible, yaml' >/dev/null 2>&1 || ! $(ANSIBLE_PLAYBOOK) --version >/dev/null 2>&1 || ! $(ANSIBLE_GALAXY) --version >/dev/null 2>&1; then \
		echo "Python/Ansible dependencies are missing from $(PYTHON); reinstalling."; \
		$(install_python_deps); \
	fi

validate: python-deps ## Validate YAML, Helm chart structure, scripts, and config catalogs.
	$(PYTHON) scripts/validate.py
	$(PYTHON) scripts/images/validate-images.py

image-policy: ## Validate image tag, digest, and approved runtime-image policy.
	$(PYTHON) scripts/images/validate-images.py

lint: ## Run local static checks that mirror the CI static gate.
	yamllint .
	shellcheck $$(git ls-files '*.sh')

configure: ## Update selected runtime defaults in Helm values.
	$(PYTHON) scripts/configure.py --engine $(ENGINE) --ingress-controller $(INGRESS) --webserver $(WEB) --database $(DB) --observability $(OBS) --values $(VALUES)

import-check: python-deps ## Check an external Compose project before importing or migrating it.
	@if [ -z "$(PROJECT_PATH)" ]; then \
		echo "Set PROJECT_PATH=/path/to/compose-project, for example: make import-check PROJECT_PATH=/path/to/compose-project"; \
		exit 2; \
	fi
	$(PYTHON) scripts/import_project.py --project-path "$(PROJECT_PATH)" --values "$(VALUES)" --ingress-controller "$(INGRESS)" --webserver "$(WEB)" --database "$(DB)" $(if $(IMPORT_REPORT),--report "$(IMPORT_REPORT)",) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,) $(if $(filter true,$(IMPORT_STRICT)),--strict,)

import-plan: MIGRATION_STAGE = prepare
import-plan: ## Generate private import diagnostics and action plan without applying changes.
	$(MAKE) import-migrate MIGRATION_STAGE=prepare MIGRATION_EXECUTE=false

import-migrate: python-deps ## Generate or execute guarded migration automation for an external Compose project.
	@if [ -z "$(PROJECT_PATH)" ]; then \
		echo "Set PROJECT_PATH=/path/to/compose-project, for example: make import-migrate PROJECT_PATH=/path/to/compose-project"; \
		exit 2; \
	fi
	$(PYTHON) scripts/migrate_project.py --project-path "$(PROJECT_PATH)" --values "$(VALUES)" --output "$(MIGRATION_OUTPUT)" --private-dir "$(MIGRATION_PRIVATE_DIR)" --namespace "$(MIGRATION_NAMESPACE)" --kubeconfig "$(MIGRATION_KUBECONFIG)" --ingress-host "$(MIGRATION_INGRESS_HOST)" --tls-cert-file "$(MIGRATION_TLS_CERT_FILE)" --tls-key-file "$(MIGRATION_TLS_KEY_FILE)" --ingress-controller "$(INGRESS)" --webserver "$(WEB)" --database "$(DB)" --image-mode "$(MIGRATION_IMAGE_MODE)" --image-output-dir "$(MIGRATION_IMAGE_OUTPUT_DIR)" --rke2-nodes "$(MIGRATION_RKE2_NODES)" --rke2-image-dir "$(MIGRATION_RKE2_IMAGE_DIR)" --ssh-user "$(MIGRATION_SSH_USER)" --ssh-key "$(MIGRATION_SSH_KEY)" --become-password-file "$(MIGRATION_BECOME_PASSWORD_FILE)" --container-tool "$(MIGRATION_CONTAINER_TOOL)" --postgres-client-image "$(MIGRATION_POSTGRES_CLIENT_IMAGE)" --registry "$(MIGRATION_REGISTRY)" --image-tag "$(MIGRATION_IMAGE_TAG)" --dump-dir "$(MIGRATION_DUMP_DIR)" --db-targets "$(MIGRATION_DB_TARGETS)" --stage "$(MIGRATION_STAGE)" $(if $(filter true,$(MIGRATION_AUTO_PREPARE)),--auto-prepare,) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,) $(if $(filter true,$(MIGRATION_EXECUTE)),--execute,) $(if $(filter true,$(MIGRATION_ALLOW_SECRET_MATERIAL)),--allow-secret-material,) $(if $(filter false,$(MIGRATION_RKE2_IMPORT_IMAGES)),--no-rke2-import-images,--rke2-import-images) $(if $(filter false,$(MIGRATION_CLEANUP_OPERATOR_IMAGES)),--no-cleanup-operator-images,--cleanup-operator-images) $(if $(filter false,$(MIGRATION_PRUNE_OPERATOR_CACHE)),--no-prune-operator-cache,--prune-operator-cache) $(if $(filter false,$(MIGRATION_SKIP_DOCKER_SOCKET_SERVICES)),--include-docker-socket-services,--skip-docker-socket-services) $(if $(filter false,$(MIGRATION_SKIP_UNAVAILABLE_DATABASES)),--strict-database-migration,--skip-unavailable-databases)

import-auto: MIGRATION_AUTO_REPAIR_CLUSTER = true
import-auto: operator-kubeconfig ## Run the full import migration workflow with preparation, execution, and validation.
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
	ANSIBLE_CONFIG=$(ANSIBLE_CONFIG) $(ANSIBLE_PLAYBOOK) -i "$$edge_inventory" ansible/playbooks/edge-ports.yml -e cluster_engine=$(ENGINE) -e deployment_environment=$(ENV) -e edge_allowed_cidrs_text="$(DEPLOY_ALLOWED_CIDRS)" $(ANSIBLE_ARGS)

install-helm: ## Install Helm on the operator machine when it is missing.
	bash $(HELM_INSTALL_SCRIPT)

install-helmfile: install-helm ## Install Helmfile on the operator machine when it is missing.
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
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl wait --for=condition=Established crd/elasticsearches.elasticsearch.k8s.elastic.co --timeout=$(OPERATOR_CRD_TIMEOUT)
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl wait --for=condition=Established crd/kibanas.kibana.k8s.elastic.co --timeout=$(OPERATOR_CRD_TIMEOUT)
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl -n cnpg-system rollout status deployment/cloudnative-pg --timeout=$(OPERATOR_CRD_TIMEOUT)

install-operators: install-helmfile operator-kubeconfig ensure-storageclass ## Install optional operators/charts needed for HA data and observability profiles.
	KUBECONFIG=$(OPERATOR_KUBECONFIG) OPERATOR_KUBECONFIG=$(OPERATOR_KUBECONFIG) HELMFILE=$(HELMFILE) HELMFILE_CONFIG=$(HELMFILE_CONFIG) HELMFILE_SYNC_RETRIES=$(HELMFILE_SYNC_RETRIES) HELMFILE_SYNC_RETRY_DELAY=$(HELMFILE_SYNC_RETRY_DELAY) KUBECONFIG_SCRIPT=$(KUBECONFIG_SCRIPT) ENV=$(ENV) ENGINE=$(ENGINE) INVENTORY=$(INVENTORY) ANSIBLE_CONFIG=$(ANSIBLE_CONFIG) ANSIBLE_PLAYBOOK=$(ANSIBLE_PLAYBOOK) ANSIBLE_ARGS="$(ANSIBLE_ARGS)" MIGRATION_RKE2_NODES="$(MIGRATION_RKE2_NODES)" MIGRATION_SSH_USER="$(MIGRATION_SSH_USER)" MIGRATION_SSH_KEY="$(MIGRATION_SSH_KEY)" MIGRATION_BECOME_PASSWORD_FILE="$(MIGRATION_BECOME_PASSWORD_FILE)" MIGRATION_BECOME_PASSWORD_PROMPT="$(MIGRATION_BECOME_PASSWORD_PROMPT)" MIGRATION_CLUSTER_VIP="$(if $(MIGRATION_CLUSTER_VIP),$(MIGRATION_CLUSTER_VIP),$(DEPLOY_CLUSTER_VIP))" MIGRATION_KUBERNETES_API_VIP_PORT="$(MIGRATION_KUBERNETES_API_VIP_PORT)" MIGRATION_CLUSTER_DOMAIN="$(MIGRATION_CLUSTER_DOMAIN)" MIGRATION_RKE2_VERSION="$(MIGRATION_RKE2_VERSION)" MIGRATION_KEEPALIVED_AUTH_PASS="$(MIGRATION_KEEPALIVED_AUTH_PASS)" MIGRATION_KEEPALIVED_INTERFACE="$(MIGRATION_KEEPALIVED_INTERFACE)" INSTALL_LOKI="$(DEPLOY_ENABLE_LOKI)" INSTALL_CLICKHOUSE="$(DEPLOY_ENABLE_CLICKHOUSE)" GRAFANA_SERVICE_TYPE="$(DEPLOY_OBSERVABILITY_SERVICE_TYPE)" GRAFANA_NODE_PORT="$(DEPLOY_GRAFANA_NODE_PORT)" LOKI_SERVICE_TYPE="$(DEPLOY_OBSERVABILITY_SERVICE_TYPE)" LOKI_NODE_PORT="$(DEPLOY_LOKI_NODE_PORT)" CLICKHOUSE_SERVICE_TYPE="$(DEPLOY_OBSERVABILITY_SERVICE_TYPE)" CLICKHOUSE_HTTP_NODE_PORT="$(DEPLOY_CLICKHOUSE_HTTP_NODE_PORT)" CLICKHOUSE_TCP_NODE_PORT="$(DEPLOY_CLICKHOUSE_TCP_NODE_PORT)" bash $(HELMFILE_SYNC_SCRIPT)
	$(MAKE) wait-operator-crds OPERATOR_CRD_TIMEOUT=$(OPERATOR_CRD_TIMEOUT) OPERATOR_KUBECONFIG=$(OPERATOR_KUBECONFIG)

ensure-namespace: ## Create and label the target namespace before deploying the platform chart.
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl get namespace $(NAMESPACE) >/dev/null 2>&1 || \
		KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl create namespace $(NAMESPACE)
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl label namespace $(NAMESPACE) pod-security.kubernetes.io/enforce=baseline pod-security.kubernetes.io/audit=restricted pod-security.kubernetes.io/warn=restricted pod-security.kubernetes.io/enforce-version=latest pod-security.kubernetes.io/audit-version=latest pod-security.kubernetes.io/warn-version=latest --overwrite

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
	$(PYTHON) scripts/release/generate_sbom.py --chart helm/urban-platform-infra --dist dist --rendered dist/rendered.yaml --sbom dist/urban-platform-infra.spdx.json --checksums dist/SHA256SUMS

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
deploy-auto: MIGRATION_AUTO_REPAIR_CLUSTER = true
deploy-auto: deploy ## Automatically recover common lab/import deploy failures and use compact local-path storage sizes.

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

clean: ## Remove generated local files.
	rm -rf rendered.yaml reports dist $(ANSIBLE_COLLECTIONS_STAMP)
