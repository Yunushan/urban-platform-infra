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
    Path('deploy/helmfile.yaml.gotmpl'),
}
REQUIRED = [
    'README.md', 'LICENSE', '.github/workflows/ci.yml', '.gitlab-ci.yml',
    '.github/workflows/release.yml', '.github/dependabot.yml', '.pre-commit-config.yaml',
    'requirements-ci.txt', 'requirements-ci-modern.txt',
    'ansible/requirements.yml', 'ansible/requirements-modern.yml',
    '.sops.yaml.example', 'ansible/playbooks/preflight.yml',
    'ansible/playbooks/operator-kubeconfig.yml',
    'ansible/roles/rke2/templates/traefik-config.yaml.j2',
    'ansible/roles/rke2/templates/traefik-helmchart.yaml.j2',
    'helm/urban-platform-infra/Chart.yaml', 'helm/urban-platform-infra/values.yaml',
    'helm/urban-platform-infra/templates/databases-cnpg-imagecatalogs.yaml',
    'config/services.catalog.yaml', 'config/cluster-profiles.yaml',
    'config/deployment-topologies.yaml', 'config/secrets.contract.yaml',
    'config/supply-chain-policy.yaml', 'config/image-policy.yaml', 'config/slo.yaml',
    'scripts/images/validate-images.py', 'scripts/release/generate_sbom.py',
    'scripts/import_project.py',
    'scripts/migrate_project.py',
    'scripts/tools/install-helm.sh', 'scripts/tools/install-helmfile.sh',
    'scripts/tools/ensure-kubeconfig.sh',
    'tests/policy/basic_policy.py', 'docs/bootstrap-safety.md', 'docs/secrets-management.md',
    'docs/supply-chain.md', 'docs/image-governance.md', 'docs/observability-slo.md',
    'docs/deployment-topologies.md', 'docs/runbooks.md', 'docs/release-guide.md',
    'docs/project-import.md',
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
TEXT_SCAN_EXCLUDED_DIRS = {
    '.ansible',
    '.git',
    '.terraform',
    '.venv',
    'build',
    'charts',
    'coverage',
    'dist',
    'node_modules',
    'rendered',
    'reports',
    'venv',
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
        if any(part in TEXT_SCAN_EXCLUDED_DIRS for part in relative_path.parts):
            continue
        if path.is_file():
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
if ingress_values.get('className') != 'traefik':
    errors.append('Default ingress class must be traefik')
for redirect_key in ['sslRedirect', 'forceSslRedirect']:
    if ingress_values.get(redirect_key) is not True:
        errors.append(f'Ingress HTTPS redirect must be enabled by default: {redirect_key}')
if values.get('webserver', {}).get('ingress', {}).get('enabled') is not True:
    errors.append('Webserver root ingress must be enabled by default')
if values.get('namespace', {}).get('create') is not True:
    errors.append('Namespace manifest rendering must be enabled by default for GitOps and policy checks')
if values.get('monitoring', {}).get('enabled') is not False:
    errors.append('Monitoring CRDs must be disabled by default so the chart renders before operators are installed')
timescaledb_values = values.get('databases', {}).get('instances', {}).get('timescaledb', {})
timescaledb_catalog_ref = timescaledb_values.get('imageCatalogRef', {})
if timescaledb_catalog_ref.get('kind') != 'ImageCatalog' or timescaledb_catalog_ref.get('major') != 18:
    errors.append('TimescaleDB must use a CNPG ImageCatalog reference for PostgreSQL 18 image detection')
timescaledb_catalog = values.get('databases', {}).get('imageCatalogs', {}).get('timescaledb', {})
if timescaledb_catalog.get('enabled') is not True:
    errors.append('TimescaleDB CNPG ImageCatalog must be enabled by default')
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

legacy_requirements_text = (ROOT / 'requirements-ci.txt').read_text(encoding='utf-8')
if 'Legacy CI lane: Python 3.11 with ansible-core 2.14.x.' not in legacy_requirements_text:
    errors.append('Legacy CI requirements must document the Python 3.11 / Ansible 2.14 lane.')
if not re.search(r'^ansible-core==2\.14\.\d+\b', legacy_requirements_text, re.MULTILINE):
    errors.append('Legacy CI requirements must keep ansible-core pinned to 2.14.x for Python 3.11.')
for legacy_tool in ['PyYAML', 'yamllint']:
    if not re.search(rf'^{legacy_tool}==[0-9][0-9A-Za-z.!+_-]*\b', legacy_requirements_text, re.MULTILINE):
        errors.append(f'Legacy CI requirements must keep {legacy_tool} explicitly pinned.')

modern_requirements_text = (ROOT / 'requirements-ci-modern.txt').read_text(encoding='utf-8')
if 'Modern CI lane: Python 3.12+ with ansible-core 2.20.x.' not in modern_requirements_text:
    errors.append('Modern CI requirements must document the Python 3.12+ / Ansible 2.20 lane.')
if not re.search(r'^ansible-core==2\.20\.\d+\b', modern_requirements_text, re.MULTILINE):
    errors.append('Modern CI requirements must keep ansible-core pinned to 2.20.x for Python 3.12+.')
for modern_tool in ['PyYAML', 'yamllint']:
    if not re.search(rf'^{modern_tool}==[0-9][0-9A-Za-z.!+_-]*\b', modern_requirements_text, re.MULTILINE):
        errors.append(f'Modern CI requirements must keep {modern_tool} explicitly pinned.')

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
    'dependency-name: "ansible-core"',
    'version-update:semver-major',
    'version-update:semver-minor',
    'requirements-ci.txt intentionally backs the legacy Python 3.11',
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
    'Validate RKE2 pod and service CIDR plan',
    'cluster_underlay_cidrs',
    'cluster_dns {cluster_dns} must be inside service_cidr',
    "rke2_ingress_controller | default('traefik')",
    "rke2_traefik_source | default('bundled')",
    'rke2_traefik_chart_version',
]:
    if preflight_token not in preflight_text:
        errors.append(f'Ansible preflight missing compatibility/safety token: {preflight_token}')

rke2_server_config_template = (ROOT / 'ansible/roles/rke2/templates/config.yaml.j2').read_text(encoding='utf-8')
for rke2_config_token in [
    "{% if inventory_hostname != groups['rke2_servers'][0] %}",
    'server: "https://{{ cluster_vip }}:{{ rke2_registration_vip_port | default(9346) }}"',
    'cluster-cidr: "{{ pod_cidr | default(\'100.64.0.0/16\') }}"',
    'service-cidr: "{{ service_cidr | default(\'100.65.0.0/16\') }}"',
    'cluster-dns: "{{ cluster_dns | default(\'100.65.0.10\') }}"',
    'ingress-controller:',
    'rke2_effective_ingress_controller | default(\'traefik\')',
]:
    if rke2_config_token not in rke2_server_config_template:
        errors.append(f'RKE2 server config template missing HA bootstrap token: {rke2_config_token}')
if 'cluster-init:' in rke2_server_config_template:
    errors.append('RKE2 server config template must not set cluster-init; first server bootstraps by omitting server')

rke2_role_tasks_text = (ROOT / 'ansible/roles/rke2/tasks/main.yml').read_text(encoding='utf-8')
for rke2_wait_token in [
    "rke2_ingress_controller | default('traefik')",
    "rke2_traefik_source | default('bundled')",
    'rke2_effective_ingress_controller',
    "'ingress-nginx'",
    'Render RKE2 Traefik HelmChartConfig',
    'rke2-traefik-config.yaml',
    'Render upstream Traefik HelmChart when pinned mode is selected',
    'traefik-helmchart.yaml',
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
    'Scan recent RKE2 journal for stale child process restart loop',
    'rke2_stale_processes_detected',
    'Recover stale RKE2 child processes after failed startup',
    'systemctl',
    'kill',
    '--kill-who=control-group',
    '[/]var/lib/rancher/rke2/.*/containerd-shim',
    'containerd-shim-runc-v2 .* -address /run/k3s/containerd/containerd.sock',
    'rke2_cleanup_stale_processes',
    'ExecMainStatus',
    'systemctl is-failed --quiet "{{ rke2_service_name }}"',
    'rke2_registration_probe',
    'until: rke2_registration_probe.rc in [0, 2]',
    'rke2_api_ready_probe',
    '--request-timeout=10s',
    'get --raw=/readyz',
    'RKE2 local Kubernetes API did not become ready before timeout.',
    'Fail when RKE2 service fails during registration wait',
    'RKE2 did not open local registration port 9345 before timeout.',
    'Recent journal:',
    'registration_waiting',
    'ss -ltnH',
    "default(['80/tcp', '443/tcp', '8472/udp', '10250/tcp'])",
    'Trust RKE2 pod and service CIDRs in firewalld',
    "zone: trusted",
    "pod_cidr | default('100.64.0.0/16')",
    "service_cidr | default('100.65.0.0/16')",
    'Enable firewalld masquerade for RKE2 overlay egress',
]:
    if rke2_wait_token not in rke2_role_tasks_text:
        errors.append(f'RKE2 role missing registration wait diagnostic token: {rke2_wait_token}')

common_role_tasks_text = (ROOT / 'ansible/roles/common/tasks/main.yml').read_text(encoding='utf-8')
for common_swap_token in [
    'Disable Linux swap for Kubernetes',
    'Disable persistent swap entries on Linux',
    "common_swap_disable_strategy | default('swapoff')",
    'Reboot Linux host to clear active swap',
    'Verify Linux swap is disabled',
]:
    if common_swap_token not in common_role_tasks_text:
        errors.append(f'Common role missing safe swap handling token: {common_swap_token}')
if 'swapoff -a' in common_role_tasks_text:
    errors.append('Common role must not use blind swapoff -a; disable active devices safely')

for kubeconfig_playbook in [
    'ansible/playbooks/operator-kubeconfig.yml',
    'ansible/playbooks/install-cluster.yml',
]:
    kubeconfig_playbook_text = (ROOT / kubeconfig_playbook).read_text(encoding='utf-8')
    for kubeconfig_token in [
        'Copy operator kubeconfig from RKE2 primary server',
        'content: "{{ rke2_operator_kubeconfig.content | b64decode }}"',
        'Rewrite operator kubeconfig to use VIP endpoint',
        "regexp: 'server: https://[^\\n]+'",
        'replace: "server: {{ rke2_operator_api_url }}"',
        'Validate operator kubeconfig syntax',
        '- config',
        '- view',
        '- --minify',
    ]:
        if kubeconfig_token not in kubeconfig_playbook_text:
            errors.append(f'{kubeconfig_playbook} missing kubeconfig safety token: {kubeconfig_token}')
    if 'operator_kubeconfig_rendered' in kubeconfig_playbook_text:
        errors.append(f'{kubeconfig_playbook} must not render kubeconfig through a folded scalar')

kubeconfig_script_text = (ROOT / 'scripts/tools/ensure-kubeconfig.sh').read_text(encoding='utf-8')
for kubeconfig_script_token in [
    'MIGRATION_RKE2_NODES',
    'Generated temporary operator inventory',
    'Fetching RKE2 kubeconfig directly',
    'MIGRATION_SSH_KEY',
    'MIGRATION_RKE2_KUBECONFIG_COMMAND',
    'MIGRATION_CLUSTER_VIP',
    'MIGRATION_KUBERNETES_API_VIP_PORT',
    'MIGRATION_CLUSTER_DOMAIN',
    'MIGRATION_RKE2_VERSION',
    'MIGRATION_AUTO_REPAIR_CLUSTER',
    'MIGRATION_KEEPALIVED_AUTH_PASS',
    'MIGRATION_KEEPALIVED_INTERFACE',
    'normalize_rke2_version',
    'Existing operator kubeconfig is ready',
    'command -v kubectl',
    'discover_remote_cluster_vip',
    'discover_remote_rke2_token',
    'discover_remote_rke2_version',
    'discover_remote_cluster_domain',
    'discover_remote_keepalived_auth_pass',
    'discover_remote_keepalived_interface',
    'run_cluster_repair',
    'rke2_token:',
    'rke2_version:',
    'cluster_domain:',
    'keepalived_auth_pass:',
    'kubernetes_api_vip_port',
]:
    if kubeconfig_script_token not in kubeconfig_script_text:
        errors.append(f'Kubeconfig helper missing import inventory fallback token: {kubeconfig_script_token}')

haproxy_template_text = (ROOT / 'ansible/roles/haproxy_keepalived/templates/haproxy.cfg.j2').read_text(
    encoding='utf-8'
)
for haproxy_tcp_check_token in [
    'timeout check 5s',
    'default-server inter 2s fall 3 rise 2',
    ':6443 check',
    ':9345 check',
]:
    if haproxy_tcp_check_token not in haproxy_template_text:
        errors.append(f'HAProxy template missing TCP health-check token: {haproxy_tcp_check_token}')

rke2_upstream_traefik_template = (
    ROOT / 'ansible/roles/rke2/templates/traefik-helmchart.yaml.j2'
).read_text(encoding='utf-8')
for rke2_upstream_traefik_token in [
    'kind: HelmChart',
    "rke2_traefik_chart_repo | default('https://traefik.github.io/charts')",
    'version: "{{ rke2_traefik_chart_version }}"',
    'kind: DaemonSet',
    'hostPort: 80',
    'hostPort: 443',
    'rke2_traefik_image_tag',
]:
    if rke2_upstream_traefik_token not in rke2_upstream_traefik_template:
        errors.append(f'Upstream Traefik template missing pinning token: {rke2_upstream_traefik_token}')

rke2_bundled_traefik_config_template = (
    ROOT / 'ansible/roles/rke2/templates/traefik-config.yaml.j2'
).read_text(encoding='utf-8')
for rke2_bundled_traefik_token in [
    'kind: HelmChartConfig',
    'redirections:',
    'entryPoint:',
    'to: websecure',
    'scheme: https',
    'permanent: true',
]:
    if rke2_bundled_traefik_token not in rke2_bundled_traefik_config_template:
        errors.append(f'Bundled Traefik config missing HTTPS redirect token: {rke2_bundled_traefik_token}')

workload_template_text = (ROOT / 'helm/urban-platform-infra/templates/workloads.yaml').read_text(encoding='utf-8')
webserver_template_text = (ROOT / 'helm/urban-platform-infra/templates/webserver.yaml').read_text(encoding='utf-8')
helpers_template_text = (ROOT / 'helm/urban-platform-infra/templates/_helpers.tpl').read_text(encoding='utf-8')
traefik_middleware_template_text = (
    ROOT / 'helm/urban-platform-infra/templates/ingress-traefik-middleware.yaml'
).read_text(encoding='utf-8')
ingress_tls_secret_template_text = (
    ROOT / 'helm/urban-platform-infra/templates/ingress-tls-secret.yaml'
).read_text(encoding='utf-8')
for ingress_template_token in [
    'include "cip.ingressAnnotations"',
    'secretName: {{ $ingressTlsSecretName | quote }}',
    'include "cip.ingressHost"',
]:
    if ingress_template_token not in workload_template_text:
        errors.append(f'Workload ingress template missing HTTPS token: {ingress_template_token}')
for webserver_ingress_token in [
    'kind: Ingress',
    'name: webserver',
    'path: {{ .Values.webserver.ingress.path | default "/" | quote }}',
    'number: {{ .Values.webserver.ingress.servicePort | default 80 }}',
    'include "cip.ingressAnnotations"',
    'name: webserver-redirect',
    'include "cip.traefikHttpRedirectAnnotations"',
    'secretName: {{ $ingressTlsSecretName | quote }}',
    'podSecurityContext',
    'resources:',
]:
    if webserver_ingress_token not in webserver_template_text:
        errors.append(f'Webserver template missing root HTTPS ingress token: {webserver_ingress_token}')
for traefik_redirect_token in [
    'cip.traefikRedirectMiddlewareRef',
    'cip.traefikHttpRedirectAnnotations',
    'router.entrypoints: "web"',
    'router.middlewares',
    'cip.ingressHost',
    'cip.ingressTlsSecretName',
]:
    if traefik_redirect_token not in helpers_template_text:
        errors.append(f'Ingress helpers missing Traefik redirect token: {traefik_redirect_token}')
for traefik_middleware_token in [
    'kind: Middleware',
    'apiVersion: traefik.io/v1alpha1',
    'name: redirect-https',
    'redirectScheme:',
    'permanent: true',
]:
    if traefik_middleware_token not in traefik_middleware_template_text:
        errors.append(f'Traefik middleware template missing redirect token: {traefik_middleware_token}')
for ingress_tls_token in [
    'apiVersion: cert-manager.io/v1',
    'kind: Certificate',
    'kind: {{ $issuerKind }}',
    'selfSigned: {}',
    'secretName: {{ $secretName | quote }}',
    'urban-platform.io/tls-source',
    'hasKey $tls "createSecret"',
    '$tls.certManager',
]:
    if ingress_tls_token not in ingress_tls_secret_template_text:
        errors.append(f'Ingress TLS certificate template missing token: {ingress_tls_token}')

cnpg_cluster_template_text = (ROOT / 'helm/urban-platform-infra/templates/databases-cnpg.yaml').read_text(encoding='utf-8')
for cnpg_cluster_token in ['imageCatalogRef:', 'imageName:', '$db.imageCatalogRef.major']:
    if cnpg_cluster_token not in cnpg_cluster_template_text:
        errors.append(f'CNPG cluster template missing ImageCatalog support token: {cnpg_cluster_token}')
cnpg_catalog_template_text = (
    ROOT / 'helm/urban-platform-infra/templates/databases-cnpg-imagecatalogs.yaml'
).read_text(encoding='utf-8')
for cnpg_catalog_token in ['kind: ImageCatalog', '.Values.databases.imageCatalogs', 'include "cip.image"']:
    if cnpg_catalog_token not in cnpg_catalog_template_text:
        errors.append(f'CNPG ImageCatalog template missing token: {cnpg_catalog_token}')

makefile_text = (ROOT / 'Makefile').read_text(encoding='utf-8')
if 'CONFIRM_PROD' not in makefile_text:
    errors.append('Makefile mutating Ansible targets must require production confirmation')
if 'bootstrap-check' not in makefile_text or 'install-cluster-check' not in makefile_text:
    errors.append('Makefile must expose Ansible check-mode targets')
for makefile_helm_token in [
    'INGRESS ?= traefik',
    'PROJECT_PATH ?=',
    'IMPORT_REPORT ?=',
    'IMPORT_REDACT ?=',
    'MIGRATION_OUTPUT ?=',
    'MIGRATION_EXECUTE ?=',
    'MIGRATION_ALLOW_SECRET_MATERIAL ?=',
    'MIGRATION_STAGE ?=',
    'MIGRATION_AUTO_PREPARE ?=',
    'MIGRATION_PRIVATE_DIR ?=',
    'MIGRATION_CLUSTER_DOMAIN ?=',
    'MIGRATION_RKE2_VERSION ?=',
    'MIGRATION_AUTO_REPAIR_CLUSTER ?=',
    'MIGRATION_KEEPALIVED_AUTH_PASS ?=',
    'MIGRATION_KEEPALIVED_INTERFACE ?=',
    'MIGRATION_IMAGE_MODE ?=',
    'MIGRATION_RKE2_NODES ?=',
    '--image-mode "$(MIGRATION_IMAGE_MODE)"',
    '--rke2-nodes "$(MIGRATION_RKE2_NODES)"',
    '--private-dir "$(MIGRATION_PRIVATE_DIR)"',
    '--stage "$(MIGRATION_STAGE)"',
    '--auto-prepare',
    '--ingress-controller $(INGRESS)',
    'import-check:',
    'import-migrate:',
    'scripts/import_project.py --project-path "$(PROJECT_PATH)"',
    'scripts/migrate_project.py --project-path "$(PROJECT_PATH)"',
    '--redact-sensitive',
    'OPERATOR_KUBECONFIG ?=',
    'KUBECONFIG_SCRIPT ?= scripts/tools/ensure-kubeconfig.sh',
    'operator-kubeconfig:',
    'import-auto: MIGRATION_AUTO_REPAIR_CLUSTER = true',
    'OPERATOR_KUBECONFIG=$(OPERATOR_KUBECONFIG)',
    'MIGRATION_SSH_KEY="$(MIGRATION_SSH_KEY)"',
    'MIGRATION_CLUSTER_DOMAIN="$(MIGRATION_CLUSTER_DOMAIN)"',
    'MIGRATION_RKE2_VERSION="$(MIGRATION_RKE2_VERSION)"',
    'MIGRATION_AUTO_REPAIR_CLUSTER="$(MIGRATION_AUTO_REPAIR_CLUSTER)"',
    'MIGRATION_KEEPALIVED_AUTH_PASS="$(MIGRATION_KEEPALIVED_AUTH_PASS)"',
    'MIGRATION_KEEPALIVED_INTERFACE="$(MIGRATION_KEEPALIVED_INTERFACE)"',
    'install-helm:',
    'HELM_INSTALL_SCRIPT',
    'install-helmfile:',
    'HELMFILE_CONFIG',
    'deploy/helmfile.yaml.gotmpl',
    'HELMFILE_INSTALL_SCRIPT',
    'wait-operator-crds:',
    '$(HELMFILE) -f $(HELMFILE_CONFIG) sync',
    'KUBECONFIG=$(OPERATOR_KUBECONFIG) $(HELMFILE)',
    'KUBECONFIG=$(OPERATOR_KUBECONFIG) kubectl wait',
    'crd/clusters.postgresql.cnpg.io',
    'crd/imagecatalogs.postgresql.cnpg.io',
    'crd/elasticsearches.elasticsearch.k8s.elastic.co',
    'crd/kibanas.kibana.k8s.elastic.co',
    'ensure-namespace:',
    'kubectl get namespace $(NAMESPACE)',
    'kubectl create namespace $(NAMESPACE)',
    'kubectl label namespace $(NAMESPACE)',
    '--set namespace.create=false',
    'deploy: install-operators ensure-namespace',
]:
    if makefile_helm_token not in makefile_text:
        errors.append(f'Makefile must prepare operator tooling before deploy: {makefile_helm_token}')

project_import_text = (ROOT / 'scripts/import_project.py').read_text(encoding='utf-8')
for project_import_token in [
    'find_compose_files',
    'docker-compose',
    '--project-path',
    'nginxinc/nginx-unprivileged:1.30.0',
    'CloudNativePG',
    'config/image-policy.yaml',
    'literal secret value',
    'ReportRedactor',
    '--redact-sensitive',
    'Migration Plan',
    'database_target_images',
    'pg_dump --format=custom',
    'ingressClassName: traefik',
]:
    if project_import_token not in project_import_text:
        errors.append(f'Project import checker missing token: {project_import_token}')

migration_automation_text = (ROOT / 'scripts/migrate_project.py').read_text(encoding='utf-8')
for migration_automation_token in [
    'stage_databases',
    'pg_dump',
    'pg_restore',
    'stage_images',
    'stage_secrets',
    'stage_prepare',
    'require_kubernetes_api',
    'kubectl_command',
    'postgres_client_container_command',
    'MIGRATION_POSTGRES_CLIENT_IMAGE',
    'docker.io/library/postgres:18.3',
    'MIGRATION_SKIP_UNAVAILABLE_DATABASES',
    '--strict-database-migration',
    'sys.executable',
    'PYTHON="${PYTHON:-python3}"',
    'kubernetes_service_exists',
    'Skipping ingress candidate',
    'No ingress candidates were applied because their backend services are not present yet.',
    'write_database_target_map',
    'preload_archives_to_nodes',
    'import_preloaded_archives_to_containerd',
    'cleanup_operator_container_tags',
    'cleanup_operator_archives',
    'prune_operator_container_cache',
    'legacy_image_archive_name',
    'generated_archives',
    'stale_archive_names',
    'run_remote_sudo_upload',
    'sudo -n true',
    'sudo -k -S',
    'removed staged tar files',
    'ensure_source_image',
    'explicit_pull_reference',
    'container_tool',
    'docker.io/library/',
    'container_command(args, "pull", pull_source)',
    '--container-tool',
    '--prune-operator-cache',
    '--rke2-import-images',
    '--cleanup-operator-images',
    '--kubeconfig',
    'MIGRATION_IMAGE_MODE',
    'MIGRATION_CONTAINER_TOOL',
    'MIGRATION_KUBECONFIG',
    'MIGRATION_RKE2_IMPORT_IMAGES',
    'MIGRATION_CLEANUP_OPERATOR_IMAGES',
    'MIGRATION_PRUNE_OPERATOR_CACHE',
    'MIGRATION_REGISTRY_USERNAME',
    'MIGRATION_ALLOW_SECRET_MATERIAL',
    'run-migration.sh',
    'traefik-ingress-candidates.yaml',
    'Migration automation bundle written to',
]:
    if migration_automation_token not in migration_automation_text:
        errors.append(f'Project migration automation missing token: {migration_automation_token}')

project_import_docs_text = (ROOT / 'docs/project-import.md').read_text(encoding='utf-8')
for project_import_docs_token in [
    'make import-check PROJECT_PATH=/path/to/compose-project',
    'INGRESS=traefik',
    'WEB=nginx',
    'DB=postgresql',
    'IMPORT_STRICT=true',
    'IMPORT_REDACT=true',
    'reports/` directory is ignored by Git',
    'Every report includes a migration plan section',
    'database upgrades',
    'make import-migrate PROJECT_PATH=/path/to/compose-project',
    'make import-auto PROJECT_PATH=/path/to/compose-project',
    'operator-kubeconfig repair target',
    'prepares the private operator workspace',
    'MIGRATION_STAGE=databases',
    'MIGRATION_IMAGE_MODE=preload',
    'MIGRATION_RKE2_NODES',
    'MIGRATION_CLEANUP_OPERATOR_IMAGES=false',
    'MIGRATION_EXECUTE=true',
    'MIGRATION_REGISTRY_USERNAME',
    'secretRef',
    'generated Ingress candidates are applied only if',
]:
    if project_import_docs_token not in project_import_docs_text:
        errors.append(f'Project import docs missing token: {project_import_docs_token}')

helm_installer_text = (ROOT / 'scripts/tools/install-helm.sh').read_text(encoding='utf-8')
for helm_installer_token in [
    'command -v helm',
    'https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3',
    'helm version --short',
]:
    if helm_installer_token not in helm_installer_text:
        errors.append(f'Helm installer script missing token: {helm_installer_token}')

helmfile_installer_text = (ROOT / 'scripts/tools/install-helmfile.sh').read_text(encoding='utf-8')
for helmfile_installer_token in [
    'command -v helmfile',
    'HELMFILE_VERSION',
    'github.com/helmfile/helmfile/releases/download',
    'helmfile --version',
]:
    if helmfile_installer_token not in helmfile_installer_text:
        errors.append(f'Helmfile installer script missing token: {helmfile_installer_token}')

bootstrap_script = (ROOT / 'scripts/bootstrap.sh').read_text(encoding='utf-8')
if 'CONFIRM_PROD' not in bootstrap_script:
    errors.append('scripts/bootstrap.sh must require production confirmation')

gitignore_text = (ROOT / '.gitignore').read_text(encoding='utf-8')
for required_ignore in [
    '.ansible/',
    'secrets/*',
    'inventories/prod/*',
    '*.decrypted.*',
    '*.plain.*',
    '*.sops.dec.*',
]:
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
    'nginxinc/nginx-unprivileged',
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
    'nginxinc/nginx-unprivileged:1.30.0',
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
helmfile_text = (ROOT / 'deploy/helmfile.yaml.gotmpl').read_text(encoding='utf-8')
for helmfile_token in [
    'open-telemetry.github.io/opentelemetry-helm-charts',
    'opentelemetry-collector',
    'INSTALL_OPENTELEMETRY',
    'kube-prometheus-stack',
    'eck-operator',
    'version: 0.28.0',
    'version: 3.4.0',
    'memory: 512Mi',
]:
    if helmfile_token not in helmfile_text:
        errors.append(f'Helmfile missing default observability stack token: {helmfile_token}')

cert_manager_release = re.search(
    r'(?ms)^  - name: cert-manager\n.*?(?=^  - name:|\Z)',
    helmfile_text,
)
if not cert_manager_release:
    errors.append('Helmfile missing cert-manager release')
else:
    cert_manager_text = cert_manager_release.group(0)
    if 'crds:' not in cert_manager_text or 'enabled: true' not in cert_manager_text:
        errors.append('cert-manager Helmfile release must use crds.enabled=true')
    if 'installCRDs' in cert_manager_text:
        errors.append('cert-manager Helmfile release must not use deprecated installCRDs')

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
