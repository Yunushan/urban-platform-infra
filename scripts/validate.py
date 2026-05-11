#!/usr/bin/env python3
from pathlib import Path
import re
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
YAML_DIRS = [
    '.github',
    'ansible/playbooks',
    'compose',
    'config',
    'deploy',
    'examples',
    'inventories',
]
YAML_SKIP = {
    Path('deploy/helmfile.yaml'),
}
REQUIRED = [
    'README.md', 'LICENSE', '.github/workflows/ci.yml', '.gitlab-ci.yml',
    '.github/workflows/release.yml', '.github/dependabot.yml', '.pre-commit-config.yaml',
    'requirements-ci.txt',
    '.sops.yaml.example', 'ansible/playbooks/preflight.yml',
    'helm/urban-platform-infra/Chart.yaml', 'helm/urban-platform-infra/values.yaml',
    'config/services.catalog.yaml', 'config/cluster-profiles.yaml',
    'config/deployment-topologies.yaml', 'config/secrets.contract.yaml',
    'config/supply-chain-policy.yaml', 'config/image-policy.yaml', 'config/slo.yaml',
    'scripts/images/validate-images.py', 'scripts/release/generate_sbom.py',
    'tests/policy/basic_policy.py', 'docs/bootstrap-safety.md', 'docs/secrets-management.md',
    'docs/supply-chain.md', 'docs/image-governance.md', 'docs/observability-slo.md',
    'docs/deployment-topologies.md', 'docs/runbooks.md', 'docs/release-guide.md',
    'helm/urban-platform-infra/topologies/single-node.yaml',
    'helm/urban-platform-infra/topologies/two-node-lab.yaml',
    'helm/urban-platform-infra/topologies/three-node-ha.yaml',
    'helm/urban-platform-infra/topologies/multi-node-ha.yaml',
    'inventories/topologies/single-node/hosts.yml',
    'inventories/topologies/two-node-lab/hosts.yml',
    'inventories/topologies/three-node-ha/hosts.yml',
    'inventories/topologies/multi-node-ha/hosts.yml',
    'SECURITY.md', 'CONTRIBUTING.md',
]
SENSITIVE_DIRS = [
    'secrets',
    'inventories/prod',
]
TEXT_SCAN_SKIP = {
    Path('scripts/validate.py'),
}
LEGACY_ACTION_REFS = [
    'actions/checkout@v4',
    'actions/setup-python@v5',
    'actions/upload-artifact@v4',
    'azure/setup-helm@v4',
    'aquasecurity/trivy-action@master',
]
FLOATING_ACTION_REF_PATTERN = re.compile(r'uses:\s+[^@\s]+@(main|master)\b')
NODE_20_PATTERN = re.compile(r'node-version:\s*[\'"]?20\b')
HIGH_CONFIDENCE_SECRET_PATTERNS = [
    re.compile(pattern)
    for pattern in [
        r'ghp_[A-Za-z0-9_]{20,}',
        r'github_pat_[A-Za-z0-9_]{20,}',
        r'glpat-[A-Za-z0-9_-]{20,}',
        r'AKIA[0-9A-Z]{16}',
        r'AIza[0-9A-Za-z\-_]{35}',
        r'xox[baprs]-[0-9A-Za-z-]{10,}',
        r'sk-[A-Za-z0-9]{20,}',
        r'-----BEGIN [A-Z ]*PRIVATE KEY-----',
    ]
]
PRIVATE_LOOKING_IP_PATTERN = re.compile(
    r'\b(10\.10\.10\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3})\b'
)
DISCLOSURE_IDENTIFIER_PATTERN = re.compile(
    r'(istanbulkart|iett|vms|tsc2a9|smartflow|scm-|tsc-|camera-ttu|taxi-stand|car-park|'
    r'bicycle-road|pedestrian-button|tsd-junction|program-archive|camera-manager|ops-scm-log|'
    r'services-(?!networking))',
    re.IGNORECASE,
)

def check_yaml(path):
    with open(path, 'r', encoding='utf-8') as f:
        return list(yaml.safe_load_all(f))

def relative_name(path):
    return path.relative_to(ROOT).as_posix()

def text_files():
    for path in ROOT.rglob('*'):
        relative_path = path.relative_to(ROOT)
        if relative_path in TEXT_SCAN_SKIP:
            continue
        if path.is_file() and '.git' not in path.parts:
            try:
                path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                continue
            yield path

errors = []
for required_path in REQUIRED:
    if not (ROOT / required_path).exists():
        errors.append(f'Missing required file: {required_path}')

for d in YAML_DIRS:
    for path in (ROOT / d).rglob('*'):
        relative_path = path.relative_to(ROOT)
        if relative_path in YAML_SKIP:
            continue
        if path.suffix in {'.yaml', '.yml'}:
            try:
                documents = check_yaml(path)
            except Exception as exc:
                errors.append(f'YAML error in {relative_name(path)}: {exc}')
                continue
            for document in documents:
                if isinstance(document, dict) and document.get('kind') == 'Secret':
                    errors.append(f'Plain Kubernetes Secret manifest is not allowed: {relative_name(path)}')

for path in [ROOT / '.sops.yaml.example']:
    try:
        check_yaml(path)
    except Exception as exc:
        errors.append(f'YAML error in {relative_name(path)}: {exc}')

values = yaml.safe_load((ROOT / 'helm/urban-platform-infra/values.yaml').read_text())
if values['global']['cluster']['engine'] != 'rke2':
    errors.append('Default engine must be rke2')
if values['global']['cluster']['nodes'] != 3:
    errors.append('Default cluster node count must be 3')
if values['global'].get('replicaOverride') is not None:
    errors.append('Default global.replicaOverride must be null; topology overrides may set it')
if values['webserver']['provider'] != 'nginx':
    errors.append('Default webserver must be nginx')
if values.get('secretManagement', {}).get('enabled') is not False:
    errors.append('Secret management chart rendering must be disabled by default')
if values.get('monitoring', {}).get('enabled') is not False:
    errors.append('Monitoring CRDs must be disabled by default so the chart renders before operators are installed')
monitoring_values = values.get('monitoring', {})
if monitoring_values.get('prometheusRules', {}).get('enabled') is not True:
    errors.append('Monitoring values must enable PrometheusRule generation when monitoring.enabled is true')
if not monitoring_values.get('prometheusRules', {}).get('runbookBaseUrl', '').startswith('https://example.com/'):
    errors.append('Default monitoring runbook URL must be an example.com placeholder')
if len(values.get('workloads', {})) < 30:
    errors.append('Expected application workload catalog to contain at least 30 services')

workloads = values.get('workloads', {})
if len(workloads) != 38:
    errors.append(f'Expected exactly 38 sanitized application workloads, found {len(workloads)}')
for name, workload in workloads.items():
    if not re.fullmatch(r'app-\d{2}', name):
        errors.append(f'Workload name must be sanitized app-NN form: {name}')
    repository = workload.get('image', {}).get('repository', '')
    if not re.fullmatch(r'example-app-\d{2}', repository):
        errors.append(f'Workload image repository must be sanitized example-app-NN form: {name} -> {repository}')

for sensitive_dir in SENSITIVE_DIRS:
    path = ROOT / sensitive_dir
    if not path.exists():
        errors.append(f'Missing sensitive placeholder directory: {sensitive_dir}')
        continue
    allowed = {'.gitkeep'}
    unexpected = [child.name for child in path.iterdir() if child.name not in allowed]
    if unexpected:
        errors.append(f'{sensitive_dir} contains non-placeholder files: {", ".join(sorted(unexpected))}')

workflow_text = '\n'.join(
    path.read_text(encoding='utf-8')
    for path in [
        ROOT / '.github/workflows/ci.yml',
        ROOT / '.github/workflows/release.yml',
    ]
    if path.exists()
)
for action_ref in LEGACY_ACTION_REFS:
    if action_ref in workflow_text:
        errors.append(f'Workflow still uses Node 20-generation action: {action_ref}')
floating_ref = FLOATING_ACTION_REF_PATTERN.search(workflow_text)
if floating_ref:
    errors.append(f'Workflow uses floating GitHub Action ref: {floating_ref.group(0)}')
if NODE_20_PATTERN.search(workflow_text):
    errors.append('Workflow must not pin setup-node to Node 20; use Node 24 LTS when Node is required')

release_workflow_text = (ROOT / '.github/workflows/release.yml').read_text(encoding='utf-8')
for release_token in [
    'id-token: write',
    'attestations: write',
    'artifact-metadata: write',
    'actions/attest@v4',
    'subject-checksums',
    'sbom-path',
    'SHA256SUMS',
    'spdx.json',
    'Validate release tag matches chart version',
]:
    if release_token not in release_workflow_text:
        errors.append(f'Release workflow missing supply-chain control: {release_token}')

ci_workflow_text = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
if 'actions/dependency-review-action@v5' not in ci_workflow_text:
    errors.append('CI must review dependency changes with dependency-review-action@v5')

dependabot_text = (ROOT / '.github/dependabot.yml').read_text(encoding='utf-8')
for dependabot_token in [
    'package-ecosystem: "github-actions"',
    'package-ecosystem: "pip"',
    'github-actions:',
    'ci-python:',
]:
    if dependabot_token not in dependabot_text:
        errors.append(f'Dependabot missing supply-chain update control: {dependabot_token}')

gitlab_ci_text = (ROOT / '.gitlab-ci.yml').read_text(encoding='utf-8')
for gitlab_token in [
    'aquasec/trivy:0.70.0',
    'alpine/helm:3.19.0',
    'release-evidence:',
    'SHA256SUMS',
    'urban-platform-infra.spdx.json',
]:
    if gitlab_token not in gitlab_ci_text:
        errors.append(f'GitLab CI missing release integrity control: {gitlab_token}')
if 'aquasec/trivy:latest' in gitlab_ci_text:
    errors.append('GitLab CI must not use floating aquasec/trivy:latest')

ansible_cfg_text = (ROOT / 'ansible/ansible.cfg').read_text(encoding='utf-8')
if re.search(r'(?m)^\s*host_key_checking\s*=\s*False\s*$', ansible_cfg_text):
    errors.append('Ansible host key checking must not be disabled')

makefile_text = (ROOT / 'Makefile').read_text(encoding='utf-8')
if 'CONFIRM_PROD' not in makefile_text:
    errors.append('Makefile mutating Ansible targets must require production confirmation')
if 'bootstrap-check' not in makefile_text or 'install-cluster-check' not in makefile_text:
    errors.append('Makefile must expose Ansible check-mode targets')

bootstrap_script = (ROOT / 'scripts/bootstrap.sh').read_text(encoding='utf-8')
if 'CONFIRM_PROD' not in bootstrap_script:
    errors.append('scripts/bootstrap.sh must require production confirmation')

gitignore_text = (ROOT / '.gitignore').read_text(encoding='utf-8')
for required_ignore in ['secrets/*', 'inventories/prod/*', '*.decrypted.*', '*.plain.*', '*.sops.dec.*']:
    if required_ignore not in gitignore_text:
        errors.append(f'.gitignore must protect secret artifact pattern: {required_ignore}')

precommit_text = (ROOT / '.pre-commit-config.yaml').read_text(encoding='utf-8')
for hook_id in ['detect-private-key', 'detect-aws-credentials']:
    if hook_id not in precommit_text:
        errors.append(f'pre-commit must include secret hygiene hook: {hook_id}')

secret_contract = yaml.safe_load((ROOT / 'config/secrets.contract.yaml').read_text(encoding='utf-8'))
if secret_contract.get('policy', {}).get('plaintextKubernetesSecretsAllowed') is not False:
    errors.append('Secret contract must disallow plaintext Kubernetes Secrets')

deployment_topologies = yaml.safe_load((ROOT / 'config/deployment-topologies.yaml').read_text(encoding='utf-8'))
expected_topologies = {
    'single-node': {'minimumNodes': 1, 'production': False},
    'two-node-lab': {'minimumNodes': 2, 'production': False},
    'three-node-ha': {'minimumNodes': 3, 'production': True},
    'multi-node-ha': {'minimumNodes': 4, 'production': True},
}
topologies = deployment_topologies.get('topologies', {})
if deployment_topologies.get('default') != 'three-node-ha':
    errors.append('Default deployment topology must be three-node-ha')
for topology_name, expectations in expected_topologies.items():
    topology = topologies.get(topology_name)
    if not topology:
        errors.append(f'Missing deployment topology: {topology_name}')
        continue
    for key, expected_value in expectations.items():
        if topology.get(key) != expected_value:
            errors.append(f'Deployment topology {topology_name} must set {key}={expected_value}')
    for path_key in ['helmValues', 'inventory']:
        referenced = topology.get(path_key)
        if not referenced or not (ROOT / referenced).exists():
            errors.append(f'Deployment topology {topology_name} references missing {path_key}: {referenced}')
    helm_values = yaml.safe_load((ROOT / topology['helmValues']).read_text(encoding='utf-8'))
    if helm_values.get('global', {}).get('cluster', {}).get('nodes', 0) < topology.get('minimumNodes'):
        errors.append(f'Deployment topology {topology_name} Helm override must be >= minimumNodes')
    inventory = yaml.safe_load((ROOT / topology['inventory']).read_text(encoding='utf-8'))
    groups = inventory.get('all', {}).get('children', {})
    if 'cluster_nodes' not in groups or 'rke2_servers' not in groups:
        errors.append(f'Deployment topology {topology_name} inventory must define cluster_nodes and rke2_servers')

supply_chain_policy = yaml.safe_load((ROOT / 'config/supply-chain-policy.yaml').read_text(encoding='utf-8'))
policy = supply_chain_policy.get('policy', {})
if policy.get('nodeLtsMajor') != 24:
    errors.append('Supply-chain policy must require Node 24 LTS for Node-based workflow tooling')
release_integrity = policy.get('releaseIntegrity', {})
for control in [
    'requireChartVersionMatchesTag',
    'requireChecksums',
    'requireSbom',
    'requireGithubArtifactAttestations',
    'requireOidcForSigning',
]:
    if release_integrity.get(control) is not True:
        errors.append(f'Supply-chain policy must enable release control: {control}')
if 'master' not in policy.get('githubActions', {}).get('disallowFloatingRefs', []):
    errors.append('Supply-chain policy must disallow floating @master action refs')
if 'main' not in policy.get('githubActions', {}).get('disallowFloatingRefs', []):
    errors.append('Supply-chain policy must disallow floating @main action refs')
if policy.get('dependencyReview', {}).get('enabledForPullRequests') is not True:
    errors.append('Supply-chain policy must enable pull-request dependency review')

image_policy = yaml.safe_load((ROOT / 'config/image-policy.yaml').read_text(encoding='utf-8'))
image_policy_controls = image_policy.get('policy', {})
if image_policy_controls.get('requireExplicitTags') is not True:
    errors.append('Image policy must require explicit image tags')
if image_policy_controls.get('requireDigestsForProduction') is not True:
    errors.append('Image policy must require digest pins for production overrides')
blocked_tags = set(image_policy_controls.get('disallowMutableTags', []))
if 'latest' not in blocked_tags:
    errors.append('Image policy must block the latest tag')
if image_policy_controls.get('defaultApplicationTag') != '0.1.0':
    errors.append('Image policy must pin placeholder application images to 0.1.0')
for approved_repository in [
    'confluentinc/cp-zookeeper',
    'provectuslabs/kafka-ui',
    'timescale/timescaledb',
    'zabbix/zabbix-agent2',
]:
    if approved_repository not in (ROOT / 'config/image-policy.yaml').read_text(encoding='utf-8'):
        errors.append(f'Image policy missing approved runtime image: {approved_repository}')

slo_contract = yaml.safe_load((ROOT / 'config/slo.yaml').read_text(encoding='utf-8'))
objectives = slo_contract.get('objectives', {})
if len(objectives) < 5:
    errors.append('SLO contract must define at least five production objectives')
for objective_name, objective in objectives.items():
    for required_key in ['target', 'sli', 'source', 'alert', 'runbook']:
        if required_key not in objective:
            errors.append(f'SLO objective {objective_name} missing required key: {required_key}')
    target = objective.get('target')
    if not isinstance(target, (int, float)) or target <= 0 or target > 100:
        errors.append(f'SLO objective {objective_name} target must be a percentage between 0 and 100')
if slo_contract.get('owner') != 'platform':
    errors.append('SLO contract owner must be platform')
monitoring_rules_text = (ROOT / 'helm/urban-platform-infra/templates/monitoring-rules.yaml').read_text(encoding='utf-8')
for alert_name in [
    'CityIntersectionDeploymentReplicasUnavailable',
    'CityIntersectionStatefulSetReplicasUnavailable',
    'CityIntersectionContainerRestartingTooOften',
    'CityIntersectionHPASaturated',
    'CityIntersectionPersistentVolumeFilling',
]:
    if alert_name not in monitoring_rules_text:
        errors.append(f'Monitoring rules missing alert: {alert_name}')
for required_monitoring_token in ['PrometheusRule', 'runbook_url', 'release:']:
    if required_monitoring_token not in monitoring_rules_text:
        errors.append(f'Monitoring rules missing required token: {required_monitoring_token}')
monitoring_services_text = (ROOT / 'helm/urban-platform-infra/templates/monitoring-servicemonitors.yaml').read_text(encoding='utf-8')
if 'ServiceMonitor' not in monitoring_services_text or 'namespaceSelector' not in monitoring_services_text:
    errors.append('Monitoring ServiceMonitor template must define namespace-scoped generic targets')
status_script = (ROOT / 'scripts/health/status.sh').read_text(encoding='utf-8')
for status_token in ['prometheusrules.monitoring.coreos.com', 'servicemonitors.monitoring.coreos.com', 'observability']:
    if status_token not in status_script:
        errors.append(f'status script missing observability check: {status_token}')

for path in text_files():
    if any(marker in path.name for marker in ['.decrypted.', '.plain.', '.sops.dec.']):
        errors.append(f'Decrypted secret artifact must not be committed: {relative_name(path)}')
    content = path.read_text(encoding='utf-8')
    for pattern in HIGH_CONFIDENCE_SECRET_PATTERNS:
        if pattern.search(content):
            errors.append(f'High-confidence secret pattern found in {relative_name(path)}')
            break
    if PRIVATE_LOOKING_IP_PATTERN.search(content):
        errors.append(f'Private-looking infrastructure IP found in {relative_name(path)}')
    if DISCLOSURE_IDENTIFIER_PATTERN.search(content):
        errors.append(f'Original disclosure-prone service identifier found in {relative_name(path)}')

if errors:
    for err in errors:
        print(f'ERROR: {err}', file=sys.stderr)
    sys.exit(1)
print('Validation passed')
