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
ANSIBLE_PLAYBOOK ?= ansible-playbook
ANSIBLE_GALAXY ?= ansible-galaxy
ANSIBLE_CONFIG ?= ansible/ansible.cfg
ANSIBLE_ARGS ?=
ANSIBLE_DIFF ?= --diff
ANSIBLE_COLLECTION_REQUIREMENTS ?= ansible/requirements.yml
ANSIBLE_COLLECTIONS_STAMP ?= .ansible/collections/.$(subst /,_,$(ANSIBLE_COLLECTION_REQUIREMENTS)).stamp
CONFIRM_PROD ?= false
HELM ?= helm
HELM_INSTALL_SCRIPT ?= scripts/tools/install-helm.sh
HELMFILE ?= helmfile
HELMFILE_CONFIG ?= deploy/helmfile.yaml.gotmpl
HELMFILE_INSTALL_SCRIPT ?= scripts/tools/install-helmfile.sh
OPERATOR_CRD_TIMEOUT ?= 180s
OPERATOR_KUBECONFIG ?= $(if $(KUBECONFIG),$(KUBECONFIG),$(HOME)/.kube/config)
KUBECONFIG_SCRIPT ?= scripts/tools/ensure-kubeconfig.sh
PROJECT_PATH ?=
IMPORT_REPORT ?=
IMPORT_STRICT ?= false
IMPORT_REDACT ?= false

.PHONY: help validate image-policy lint configure import-check ansible-collections preflight bootstrap-check bootstrap install-cluster-check install-cluster operator-kubeconfig install-helm install-helmfile install-operators wait-operator-crds ensure-namespace deploy deploy-dry-run package-chart release-evidence status observability-status docker-up docker-down docker-status policy clean

define require_prod_confirmation
	@if [ "$(ENV)" = "prod" ] && [ "$(CONFIRM_PROD)" != "true" ]; then \
		echo "Refusing to mutate prod without CONFIRM_PROD=true. Run preflight/check targets first."; \
		exit 2; \
	fi
endef

help:
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make <target> [ENV=prod ENGINE=rke2 INGRESS=traefik WEB=nginx DB=postgresql OBS=elasticsearch TOPOLOGY=three-node-ha]\n\nTargets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  %-22s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

validate: ## Validate YAML, Helm chart structure, scripts, and config catalogs.
	python3 scripts/validate.py
	python3 scripts/images/validate-images.py

image-policy: ## Validate image tag, digest, and approved runtime-image policy.
	python3 scripts/images/validate-images.py

lint: ## Run local static checks that mirror the CI static gate.
	yamllint .
	shellcheck $$(git ls-files '*.sh')

configure: ## Update selected runtime defaults in Helm values.
	python3 scripts/configure.py --engine $(ENGINE) --ingress-controller $(INGRESS) --webserver $(WEB) --database $(DB) --observability $(OBS) --values $(VALUES)

import-check: ## Check an external Compose project before importing or migrating it.
	@if [ -z "$(PROJECT_PATH)" ]; then \
		echo "Set PROJECT_PATH=/path/to/compose-project, for example: make import-check PROJECT_PATH=/path/to/compose-project"; \
		exit 2; \
	fi
	python3 scripts/import_project.py --project-path "$(PROJECT_PATH)" --values "$(VALUES)" --ingress-controller "$(INGRESS)" --webserver "$(WEB)" --database "$(DB)" $(if $(IMPORT_REPORT),--report "$(IMPORT_REPORT)",) $(if $(filter true,$(IMPORT_REDACT)),--redact-sensitive,) $(if $(filter true,$(IMPORT_STRICT)),--strict,)

$(ANSIBLE_COLLECTIONS_STAMP): $(ANSIBLE_COLLECTION_REQUIREMENTS)
	mkdir -p .ansible/collections
	ANSIBLE_CONFIG=$(ANSIBLE_CONFIG) $(ANSIBLE_GALAXY) collection install -r $(ANSIBLE_COLLECTION_REQUIREMENTS) --force
	touch $(ANSIBLE_COLLECTIONS_STAMP)

ansible-collections: $(ANSIBLE_COLLECTIONS_STAMP) ## Install repo-pinned Ansible collections.

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
	ENV=$(ENV) ENGINE=$(ENGINE) INVENTORY=$(INVENTORY) ANSIBLE_CONFIG=$(ANSIBLE_CONFIG) ANSIBLE_PLAYBOOK=$(ANSIBLE_PLAYBOOK) OPERATOR_KUBECONFIG=$(OPERATOR_KUBECONFIG) ANSIBLE_ARGS="$(ANSIBLE_ARGS)" bash $(KUBECONFIG_SCRIPT)

install-helm: ## Install Helm on the operator machine when it is missing.
	bash $(HELM_INSTALL_SCRIPT)

install-helmfile: install-helm ## Install Helmfile on the operator machine when it is missing.
	bash $(HELMFILE_INSTALL_SCRIPT)

wait-operator-crds: ## Wait until CRDs required by the default platform chart exist.
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl wait --for=condition=Established crd/clusters.postgresql.cnpg.io --timeout=$(OPERATOR_CRD_TIMEOUT)
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl wait --for=condition=Established crd/imagecatalogs.postgresql.cnpg.io --timeout=$(OPERATOR_CRD_TIMEOUT)
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl wait --for=condition=Established crd/elasticsearches.elasticsearch.k8s.elastic.co --timeout=$(OPERATOR_CRD_TIMEOUT)
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl wait --for=condition=Established crd/kibanas.kibana.k8s.elastic.co --timeout=$(OPERATOR_CRD_TIMEOUT)

install-operators: install-helmfile operator-kubeconfig ## Install optional operators/charts needed for HA data and observability profiles.
	KUBECONFIG=$(OPERATOR_KUBECONFIG) $(HELMFILE) -f $(HELMFILE_CONFIG) sync
	$(MAKE) wait-operator-crds OPERATOR_CRD_TIMEOUT=$(OPERATOR_CRD_TIMEOUT) OPERATOR_KUBECONFIG=$(OPERATOR_KUBECONFIG)

ensure-namespace: ## Create and label the target namespace before deploying the platform chart.
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl get namespace $(NAMESPACE) >/dev/null 2>&1 || \
		KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl create namespace $(NAMESPACE)
	KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl label namespace $(NAMESPACE) pod-security.kubernetes.io/enforce=baseline pod-security.kubernetes.io/audit=restricted pod-security.kubernetes.io/warn=restricted pod-security.kubernetes.io/enforce-version=latest pod-security.kubernetes.io/audit-version=latest pod-security.kubernetes.io/warn-version=latest --overwrite

deploy-dry-run: install-helm ## Render the Helm chart without applying it.
	$(HELM) template $(PROJECT) helm/urban-platform-infra --namespace $(NAMESPACE) -f $(VALUES) -f $(TOPOLOGY_VALUES) --dry-run > rendered.yaml

policy: ## Run policy checks against rendered manifests.
	mkdir -p reports
	$(HELM) template $(PROJECT) helm/urban-platform-infra --namespace $(NAMESPACE) -f $(VALUES) -f $(TOPOLOGY_VALUES) > reports/rendered.yaml
	python3 tests/policy/basic_policy.py reports/rendered.yaml

package-chart: install-helm ## Package the Helm chart into dist/.
	mkdir -p dist
	$(HELM) dependency build helm/urban-platform-infra
	$(HELM) lint helm/urban-platform-infra
	$(HELM) package helm/urban-platform-infra -d dist

release-evidence: package-chart ## Generate rendered manifest, SPDX SBOM, and checksums for a release.
	$(HELM) template $(PROJECT) helm/urban-platform-infra --namespace $(NAMESPACE) -f $(VALUES) > dist/rendered.yaml
	python3 scripts/release/generate_sbom.py --chart helm/urban-platform-infra --dist dist --rendered dist/rendered.yaml --sbom dist/urban-platform-infra.spdx.json --checksums dist/SHA256SUMS

deploy: install-operators ensure-namespace ## Deploy/upgrade the HA application platform.
	KUBECONFIG=$(OPERATOR_KUBECONFIG) $(HELM) upgrade --install $(PROJECT) helm/urban-platform-infra --namespace $(NAMESPACE) --cleanup-on-fail --set namespace.create=false -f $(VALUES) -f $(TOPOLOGY_VALUES)

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
