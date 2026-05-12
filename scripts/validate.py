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
    'requirements-ci.txt', 'requirements-ci-modern.txt',
    'ansible/requirements.yml', 'ansible/requirements-modern.yml',
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
ingress_values = values.get('ingress', {})
if ingress_values.get('tls', {}).get('enabled') is not True:
    errors.append('Ingress TLS must be enabled by default so HTTPS is available')
for redirect_key in ['sslRedirect', 'forceSslRedirect']:
    if ingress_values.get(redirect_key) is not True:
        errors.append(f'Ingress HTTPS redirect must be enabled by default: {redirect_key}')
if values.get('webserver', {}).get('ingress', {}).get('enabled') is not True:
    errors.append('Webserver root ingress must be enabled by default')
if values.get('monitoring', {}).get('enabled') is not False:
    errors.append('Monitoring CRDs must be disabled by default so the chart renders before operators are installed')
observability_values = values.get('observability', {})
if observability_values.get('stack', {}).get('name') != 'elastic-eck-prometheus-grafana-opentelemetry':
    errors.append('Default observability stack must be Elastic ECK + Prometheus/Grafana + OpenTelemetry')
for observability_component in ['elasticsearch', 'kibana', 'logstash', 'grafana', 'prometheus', 'opentelemetry']:
    if observability_values.get(observability_component, {}).get('enabled') is not True:
        errors.append(f'Default observability component must be enabled: {observability_component}')
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
for ci_token in [
    'ansible-2.14-py311',
    'ansible-2.20-py312',
    'ansible-2.20-py313',
    'ansible-2.20-py314',
    'python-3.12',
    'python-3.13',
    'python-3.14',
    'requirements-ci-modern.txt',
    'ansible/requirements-modern.yml',
]:
    if ci_token not in ci_workflow_text:
        errors.append(f'CI missing Python/Ansible compatibility lane token: {ci_token}')

modern_requirements_text = (ROOT / 'requirements-ci-modern.txt').read_text(encoding='utf-8')
for modern_requirement in [
    'ansible-core==2.20.5',
    'PyYAML==6.0.3',
    'yamllint==1.38.0',
]:
    if modern_requirement not in modern_requirements_text:
        errors.append(f'Modern CI requirements missing pinned dependency: {modern_requirement}')

modern_ansible_requirements_text = (ROOT / 'ansible/requirements-modern.yml').read_text(encoding='utf-8')
for modern_collection in [
    'version: "2.1.0"',
    'version: "12.6.0"',
    'version: "6.3.0"',
    'version: "5.2.0"',
]:
    if modern_collection not in modern_ansible_requirements_text:
        errors.append(f'Modern Ansible collection requirements missing pin: {modern_collection}')

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

preflight_text = (ROOT / 'ansible/playbooks/preflight.yml').read_text(encoding='utf-8')
for preflight_token in [
    'oraclelinux',
    'oracle-linux-server',
    'supported_oracle_linux_major_versions',
    'supported_oracle_linux_distributions',
    'Validate RedHat-family major 10 target Python compatibility',
    'supported_ansible_220_target_python_min: "3.9"',
    'supported_ansible_220_target_python_max_exclusive: "3.15"',
]:
    if preflight_token not in preflight_text:
        errors.append(f'Ansible preflight missing RedHat-family major 10 compatibility token: {preflight_token}')

rke2_server_config_template = (ROOT / 'ansible/roles/rke2/templates/config.yaml.j2').read_text(encoding='utf-8')
for rke2_config_token in [
    "{% if inventory_hostname != groups['rke2_servers'][0] %}",
    'server: "https://{{ cluster_vip }}:{{ rke2_registration_vip_port | default(9346) }}"',
]:
    if rke2_config_token not in rke2_server_config_template:
        errors.append(f'RKE2 server config template missing HA bootstrap token: {rke2_config_token}')
if 'cluster-init:' in rke2_server_config_template:
    errors.append('RKE2 server config template must not set cluster-init; first server bootstraps by omitting server')

rke2_role_tasks_text = (ROOT / 'ansible/roles/rke2/tasks/main.yml').read_text(encoding='utf-8')
for rke2_wait_token in [
    'Reject unsupported RKE2 cluster-init config',
    'Check RKE2 server join URL in rendered config',
    'Show initial RKE2 startup state',
    'Scan recent RKE2 journal for corrupt embedded etcd snapshot state',
    'rke2_corrupt_etcd_journal_lines',
    'Detect corrupt RKE2 embedded etcd snapshot state',
    'failed to recover v3 backend from snapshot',
    'Archive corrupt RKE2 datastore before retry',
    'db.corrupt.$(date -u +%Y%m%dT%H%M%SZ)',
    'rke2_auto_recover_corrupt_etcd_snapshot',
    'Show recovered RKE2 startup state',
    'ExecMainStatus',
    'systemctl is-failed --quiet "{{ rke2_service_name }}"',
    'rke2_registration_probe',
    'until: rke2_registration_probe.rc in [0, 2]',
    'Fail when RKE2 service fails during registration wait',
    'RKE2 did not open local registration port 9345 before timeout.',
    'Recent journal:',
    'registration_waiting',
    'ss -ltnH',
]:
    if rke2_wait_token not in rke2_role_tasks_text:
        errors.append(f'RKE2 role missing registration wait diagnostic token: {rke2_wait_token}')

workload_template_text = (ROOT / 'helm/urban-platform-infra/templates/workloads.yaml').read_text(encoding='utf-8')
webserver_template_text = (ROOT / 'helm/urban-platform-infra/templates/webserver.yaml').read_text(encoding='utf-8')
for ingress_template_token in [
    'nginx.ingress.kubernetes.io/ssl-redirect',
    'nginx.ingress.kubernetes.io/force-ssl-redirect',
    'secretName: {{ $.Values.ingress.tls.secretName | quote }}',
]:
    if ingress_template_token not in workload_template_text:
        errors.append(f'Workload ingress template missing HTTPS token: {ingress_template_token}')
for webserver_ingress_token in [
    'kind: Ingress',
    'name: webserver',
    'path: {{ .Values.webserver.ingress.path | default "/" | quote }}',
    'number: {{ .Values.webserver.ingress.servicePort | default 80 }}',
    'nginx.ingress.kubernetes.io/ssl-redirect',
]:
    if webserver_ingress_token not in webserver_template_text:
        errors.append(f'Webserver template missing root HTTPS ingress token: {webserver_ingress_token}')

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

platforms = yaml.safe_load((ROOT / 'config/platforms.yaml').read_text(encoding='utf-8'))
required_debian_family_platforms = {
    'ubuntu-22.04', 'ubuntu-24.04', 'ubuntu-26.04',
    'debian-11', 'debian-12', 'debian-13',
}
required_rhel_family_platforms = {
    'rhel-7', 'rhel-8', 'rhel-9', 'rhel-10',
    'rocky-linux-7', 'rocky-linux-8', 'rocky-linux-9', 'rocky-linux-10',
    'alma-linux-7', 'alma-linux-8', 'alma-linux-9', 'alma-linux-10',
    'oracle-linux-10',
    'centos-stream-9', 'centos-stream-10',
}
linux_production_nodes = set(platforms.get('linuxProductionNodes', []))
missing_debian_family_platforms = required_debian_family_platforms - linux_production_nodes
if missing_debian_family_platforms:
    errors.append(
        'Platform matrix missing required Debian-family production nodes: '
        + ', '.join(sorted(missing_debian_family_platforms))
    )
missing_rhel_family_platforms = required_rhel_family_platforms - linux_production_nodes
if missing_rhel_family_platforms:
    errors.append(
        'Platform matrix missing required RHEL-family production nodes: '
        + ', '.join(sorted(missing_rhel_family_platforms))
    )
debian_family_versions = platforms.get('debianFamilyVersions', {})
for family, expected_versions in {
    'ubuntu': {'22.04', '24.04', '26.04'},
    'debian': {'11', '12', '13'},
}.items():
    actual_versions = set(str(version) for version in debian_family_versions.get(family, []))
    if actual_versions != expected_versions:
        errors.append(f'Platform matrix {family} versions must be: {", ".join(sorted(expected_versions))}')

rhel_family_versions = platforms.get('rhelFamilyMajorVersions', {})
for family, expected_versions in {
    'rhel': {'7', '8', '9', '10'},
    'rocky-linux': {'7', '8', '9', '10'},
    'alma-linux': {'7', '8', '9', '10'},
    'oracle-linux': {'10'},
    'centos-stream': {'9', '10'},
}.items():
    actual_versions = set(str(version) for version in rhel_family_versions.get(family, []))
    if actual_versions != expected_versions:
        errors.append(f'Platform matrix {family} versions must be: {", ".join(sorted(expected_versions))}')

cluster_profiles = yaml.safe_load((ROOT / 'config/cluster-profiles.yaml').read_text(encoding='utf-8'))
cluster_profile_catalog = cluster_profiles.get('profiles', {})
for profile_name in ['rke2', 'k3s', 'docker']:
    supported_node_os = set(cluster_profile_catalog.get(profile_name, {}).get('supportedNodeOs', []))
    missing_debian_platforms = required_debian_family_platforms - supported_node_os
    if missing_debian_platforms:
        errors.append(
            f'{profile_name} profile missing required Debian-family node OS entries: '
            + ', '.join(sorted(missing_debian_platforms))
        )
    missing_rhel_platforms = required_rhel_family_platforms - supported_node_os
    if missing_rhel_platforms:
        errors.append(
            f'{profile_name} profile missing required RHEL-family node OS entries: '
            + ', '.join(sorted(missing_rhel_platforms))
        )

microk8s_supported_node_os = set(cluster_profile_catalog.get('microk8s', {}).get('supportedNodeOs', []))
missing_microk8s_debian_platforms = required_debian_family_platforms - microk8s_supported_node_os
if missing_microk8s_debian_platforms:
    errors.append(
        'microk8s profile missing required Debian-family node OS entries: '
        + ', '.join(sorted(missing_microk8s_debian_platforms))
    )

raw_supported_os = set(cluster_profile_catalog.get('raw', {}).get('supportedOs', []))
missing_raw_debian_platforms = required_debian_family_platforms - raw_supported_os
if missing_raw_debian_platforms:
    errors.append(
        'raw profile missing required Debian-family OS entries: '
        + ', '.join(sorted(missing_raw_debian_platforms))
    )
missing_raw_rhel_platforms = required_rhel_family_platforms - raw_supported_os
if missing_raw_rhel_platforms:
    errors.append(
        'raw profile missing required RHEL-family OS entries: '
        + ', '.join(sorted(missing_raw_rhel_platforms))
    )

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
if 'latest-pg18' not in blocked_tags:
    errors.append('Image policy must block TimescaleDB latest-pg18 mutable tag')
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

runtime_image_surface_text = '\n'.join(
    (ROOT / runtime_image_file).read_text(encoding='utf-8')
    for runtime_image_file in [
        'README.md',
        'config/image-policy.yaml',
        'config/services.catalog.yaml',
        'config/databases.catalog.yaml',
        'config/webservers.yaml',
        'helm/urban-platform-infra/values.yaml',
        'compose/docker-compose.ha.yml',
    ]
)
for current_runtime_image in [
    'nginx:1.30.0',
    'confluentinc/cp-kafka:7.9.6',
    'confluentinc/cp-zookeeper:7.9.6',
    'redis:8.6.2',
    'postgres:18.3',
    'postgis/postgis:18-3.6',
    'timescale/timescaledb:2.26.4-pg18',
    'docker.elastic.co/elasticsearch/elasticsearch:9.4.0',
    'docker.elastic.co/kibana/kibana:9.4.0',
    'docker.elastic.co/logstash/logstash:9.4.0',
    'zabbix/zabbix-agent2:ubuntu-7.4.10',
]:
    if current_runtime_image not in runtime_image_surface_text:
        errors.append(f'Runtime image surface missing current pin: {current_runtime_image}')
for retired_runtime_image in [
    'nginx:1.18',
    'confluentinc/cp-kafka:7.5.0',
    'confluentinc/cp-zookeeper:7.5.0',
    'redis:6.2',
    'postgres:16.2',
    'postgis/postgis:16-3.4',
    'elasticsearch:8.12.0',
    'kibana:8.12.0',
    'logstash:8.12.0',
    'zabbix/zabbix-agent2:ubuntu-7.0.25',
]:
    if retired_runtime_image in runtime_image_surface_text:
        errors.append(f'Runtime image surface still contains retired pin: {retired_runtime_image}')

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
observability_contract = yaml.safe_load((ROOT / 'config/observability.yaml').read_text(encoding='utf-8'))
if observability_contract.get('defaultStack') != 'elastic-eck-prometheus-grafana-opentelemetry':
    errors.append('Observability contract must declare the enterprise default stack')
for observability_profile in ['elasticsearch', 'grafana', 'prometheus', 'opentelemetry']:
    if observability_contract.get('profiles', {}).get(observability_profile, {}).get('enabled') is not True:
        errors.append(f'Observability contract must enable default profile: {observability_profile}')
helmfile_text = (ROOT / 'deploy/helmfile.yaml').read_text(encoding='utf-8')
for helmfile_token in [
    'open-telemetry.github.io/opentelemetry-helm-charts',
    'opentelemetry-collector',
    'INSTALL_OPENTELEMETRY',
    'kube-prometheus-stack',
    'eck-operator',
]:
    if helmfile_token not in helmfile_text:
        errors.append(f'Helmfile missing default observability stack token: {helmfile_token}')

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
