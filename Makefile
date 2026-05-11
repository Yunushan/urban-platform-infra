SHELL := /usr/bin/env bash
PROJECT ?= city-intersection-project
ENV ?= prod
ENGINE ?= rke2
WEB ?= nginx
DB ?= postgresql
OBS ?= elasticsearch
NAMESPACE ?= city-intersection
VALUES ?= helm/city-intersection-platform/values.yaml
TOPOLOGY ?= three-node-ha
TOPOLOGY_VALUES ?= helm/city-intersection-platform/topologies/$(TOPOLOGY).yaml
INVENTORY ?= inventories/$(ENV)/hosts.yml
ANSIBLE_PLAYBOOK ?= ansible-playbook
ANSIBLE_ARGS ?=
CONFIRM_PROD ?= false

.PHONY: help validate image-policy lint configure preflight bootstrap-check bootstrap install-cluster-check install-cluster install-operators deploy deploy-dry-run package-chart release-evidence status observability-status docker-up docker-down docker-status policy clean

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

preflight: ## Validate inventory and target readiness before bootstrap/install.
	$(ANSIBLE_PLAYBOOK) -i $(INVENTORY) ansible/playbooks/preflight.yml -e cluster_engine=$(ENGINE) -e deployment_environment=$(ENV) $(ANSIBLE_ARGS)

bootstrap-check: ## Dry-run bootstrap with Ansible check mode and diff.
	$(ANSIBLE_PLAYBOOK) -i $(INVENTORY) ansible/playbooks/bootstrap.yml -e cluster_engine=$(ENGINE) -e deployment_environment=$(ENV) --check --diff $(ANSIBLE_ARGS)

bootstrap: ## Bootstrap nodes with common packages, Chrony, HAProxy, Keepalived.
	$(call require_prod_confirmation)
	$(ANSIBLE_PLAYBOOK) -i $(INVENTORY) ansible/playbooks/bootstrap.yml -e cluster_engine=$(ENGINE) -e deployment_environment=$(ENV) $(ANSIBLE_ARGS)

install-cluster-check: ## Dry-run cluster install with Ansible check mode and diff.
	$(ANSIBLE_PLAYBOOK) -i $(INVENTORY) ansible/playbooks/install-cluster.yml -e cluster_engine=$(ENGINE) -e deployment_environment=$(ENV) --check --diff $(ANSIBLE_ARGS)

install-cluster: ## Install selected cluster engine: rke2, k3s, microk8s, docker, or raw.
	$(call require_prod_confirmation)
	$(ANSIBLE_PLAYBOOK) -i $(INVENTORY) ansible/playbooks/install-cluster.yml -e cluster_engine=$(ENGINE) -e deployment_environment=$(ENV) $(ANSIBLE_ARGS)

install-operators: ## Install optional operators/charts needed for HA data and observability profiles.
	helmfile -f deploy/helmfile.yaml apply

deploy-dry-run: ## Render the Helm chart without applying it.
	helm template $(PROJECT) helm/city-intersection-platform --namespace $(NAMESPACE) -f $(VALUES) -f $(TOPOLOGY_VALUES) --dry-run > rendered.yaml

policy: ## Run policy checks against rendered manifests.
	mkdir -p reports
	helm template $(PROJECT) helm/city-intersection-platform --namespace $(NAMESPACE) -f $(VALUES) -f $(TOPOLOGY_VALUES) > reports/rendered.yaml
	python3 tests/policy/basic_policy.py reports/rendered.yaml

package-chart: ## Package the Helm chart into dist/.
	mkdir -p dist
	helm dependency build helm/city-intersection-platform
	helm lint helm/city-intersection-platform
	helm package helm/city-intersection-platform -d dist

release-evidence: package-chart ## Generate rendered manifest, SPDX SBOM, and checksums for a release.
	helm template $(PROJECT) helm/city-intersection-platform --namespace $(NAMESPACE) -f $(VALUES) > dist/rendered.yaml
	python3 scripts/release/generate_sbom.py --chart helm/city-intersection-platform --dist dist --rendered dist/rendered.yaml --sbom dist/city-intersection-platform.spdx.json --checksums dist/SHA256SUMS

deploy: ## Deploy/upgrade the HA application platform.
	helm upgrade --install $(PROJECT) helm/city-intersection-platform --namespace $(NAMESPACE) --create-namespace -f $(VALUES) -f $(TOPOLOGY_VALUES)

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
	rm -rf rendered.yaml reports dist
