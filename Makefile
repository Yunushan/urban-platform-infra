SHELL := /usr/bin/env bash
PROJECT ?= urban-platform-infra
ENV ?= prod
ENGINE ?= rke2
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

.PHONY: help validate image-policy lint configure ansible-collections preflight bootstrap-check bootstrap install-cluster-check install-cluster install-helm install-operators deploy deploy-dry-run package-chart release-evidence status observability-status docker-up docker-down docker-status policy clean

define require_prod_confirmation
	@if [ "$(ENV)" = "prod" ] && [ "$(CONFIRM_PROD)" != "true" ]; then \
		echo "Refusing to mutate prod without CONFIRM_PROD=true. Run preflight/check targets first."; \
		exit 2; \
	fi
endef

help:
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make <target> [ENV=prod ENGINE=rke2 WEB=nginx DB=postgresql OBS=elasticsearch TOPOLOGY=three-node-ha]\n\nTargets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  %-22s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

validate: ## Validate YAML, Helm chart structure, scripts, and config catalogs.
	python3 scripts/validate.py
	python3 scripts/images/validate-images.py

image-policy: ## Validate image tag, digest, and approved runtime-image policy.
	python3 scripts/images/validate-images.py

lint: ## Run local static checks that mirror the CI static gate.
	yamllint .
	shellcheck $$(git ls-files '*.sh')

configure: ## Update selected runtime defaults in Helm values.
	python3 scripts/configure.py --engine $(ENGINE) --webserver $(WEB) --database $(DB) --observability $(OBS) --values $(VALUES)

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

install-helm: ## Install Helm on the operator machine when it is missing.
	bash $(HELM_INSTALL_SCRIPT)

install-operators: install-helm ## Install optional operators/charts needed for HA data and observability profiles.
	helmfile -f deploy/helmfile.yaml apply

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

deploy: install-helm ## Deploy/upgrade the HA application platform.
	$(HELM) upgrade --install $(PROJECT) helm/urban-platform-infra --namespace $(NAMESPACE) --create-namespace -f $(VALUES) -f $(TOPOLOGY_VALUES)

status: ## Show cluster and workload status.
	scripts/health/status.sh $(NAMESPACE)

observability-status: ## Show monitoring and observability resources.
	kubectl -n $(NAMESPACE) get prometheusrules.monitoring.coreos.com,servicemonitors.monitoring.coreos.com 2>/dev/null || true
	kubectl -n observability get pods,svc 2>/dev/null || true

docker-up: ## Start Docker fallback profile. Use Docker Swarm for replicas.
	docker compose -f compose/docker-compose.ha.yml up -d

docker-down: ## Stop Docker fallback profile.
	docker compose -f compose/docker-compose.ha.yml down

docker-status: ## Show Docker fallback profile status.
	docker compose -f compose/docker-compose.ha.yml ps

clean: ## Remove generated local files.
	rm -rf rendered.yaml reports dist $(ANSIBLE_COLLECTIONS_STAMP)
