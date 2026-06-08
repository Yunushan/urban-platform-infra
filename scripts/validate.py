#!/usr/bin/env python3
from pathlib import Path
import re
import sys
from typing import Any, Optional

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - used on lean operator workstations.
    yaml = None


def _strip_yaml_comment(line: str) -> str:
    quote = ''
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == '\\':
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = ''
            continue
        if char in {'"', "'"}:
            quote = char
            continue
        if char == '#' and (index == 0 or line[index - 1].isspace()):
            return line[:index].rstrip()
    return line.rstrip()


def _yaml_scalar(value: str) -> Any:
    value = value.strip()
    if value in {'', "''", '""'}:
        return ''
    lowered = value.lower()
    if lowered in {'true', 'false'}:
        return lowered == 'true'
    if lowered in {'null', '~'}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.startswith('[') and value.endswith(']'):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_yaml_scalar(part.strip()) for part in inner.split(',')]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _yaml_lines(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith('#'):
            continue
        stripped = raw_line.strip()
        if stripped in {'---', '...'}:
            continue
        line = _strip_yaml_comment(raw_line.rstrip())
        if not line.strip():
            continue
        lines.append((len(line) - len(line.lstrip(' ')), line.lstrip()))
    return lines


def _next_yaml_indent(lines: list[tuple[int, str]], index: int, current_indent: int) -> Optional[int]:
    for next_indent, stripped in lines[index + 1:]:
        if next_indent == current_indent and stripped.startswith('- '):
            return next_indent
        if next_indent > current_indent:
            return next_indent
        if next_indent <= current_indent:
            return None
    return None


def _parse_yaml_block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines) or lines[index][0] < indent:
        return {}, index
    if lines[index][1].startswith('- '):
        items: list[Any] = []
        while index < len(lines):
            line_indent, stripped = lines[index]
            if line_indent < indent or not stripped.startswith('- '):
                break
            if line_indent > indent:
                break
            item_text = stripped[2:].strip()
            if not item_text:
                child_indent = _next_yaml_indent(lines, index, line_indent)
                if child_indent is None:
                    items.append({})
                    index += 1
                else:
                    child, index = _parse_yaml_block(lines, index + 1, child_indent)
                    items.append(child)
                continue
            if ':' in item_text and not item_text.startswith(('"', "'")):
                key, raw_value = item_text.split(':', 1)
                item: dict[str, Any] = {}
                raw_value = raw_value.strip()
                if raw_value in {'|', '>'}:
                    child_indent = _next_yaml_indent(lines, index, line_indent)
                    item[key.strip().strip('"\'')] = ''
                    index = _consume_yaml_multiline(lines, index + 1, child_indent or line_indent + 2)[1]
                elif raw_value:
                    item[key.strip().strip('"\'')] = _yaml_scalar(raw_value)
                    index += 1
                else:
                    child_indent = _next_yaml_indent(lines, index, line_indent)
                    if child_indent is None:
                        item[key.strip().strip('"\'')] = {}
                        index += 1
                    else:
                        child, index = _parse_yaml_block(lines, index + 1, child_indent)
                        item[key.strip().strip('"\'')] = child
                while index < len(lines) and lines[index][0] > line_indent:
                    continuation, index = _parse_yaml_block(lines, index, lines[index][0])
                    if isinstance(continuation, dict):
                        item.update(continuation)
                    else:
                        break
                items.append(item)
                continue
            items.append(_yaml_scalar(item_text))
            index += 1
        return items, index

    mapping: dict[str, Any] = {}
    while index < len(lines):
        line_indent, stripped = lines[index]
        if line_indent < indent or stripped.startswith('- '):
            break
        if line_indent > indent:
            break
        if ':' not in stripped:
            index += 1
            continue
        key, raw_value = stripped.split(':', 1)
        key = key.strip().strip('"\'')
        raw_value = raw_value.strip()
        if raw_value in {'|', '>'}:
            child_indent = _next_yaml_indent(lines, index, line_indent)
            mapping[key], index = _consume_yaml_multiline(lines, index + 1, child_indent or line_indent + 2)
        elif raw_value:
            mapping[key] = _yaml_scalar(raw_value)
            index += 1
        else:
            child_indent = _next_yaml_indent(lines, index, line_indent)
            if child_indent is None:
                mapping[key] = {}
                index += 1
            else:
                mapping[key], index = _parse_yaml_block(lines, index + 1, child_indent)
    return mapping, index


def _consume_yaml_multiline(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[str, int]:
    values: list[str] = []
    while index < len(lines) and lines[index][0] >= indent:
        values.append(lines[index][1])
        index += 1
    return '\n'.join(values), index


def _yaml_input_text(stream_or_text: Any) -> str:
    if hasattr(stream_or_text, 'read'):
        return stream_or_text.read()
    return str(stream_or_text)


def safe_load(stream_or_text: Any) -> Any:
    if yaml is not None:
        return yaml.safe_load(stream_or_text)
    text = _yaml_input_text(stream_or_text)
    parsed, _ = _parse_yaml_block(_yaml_lines(text), 0, 0)
    return parsed


def safe_load_all(stream_or_text: Any) -> list[Any]:
    if yaml is not None:
        return list(yaml.safe_load_all(stream_or_text))
    text = _yaml_input_text(stream_or_text)
    documents = re.split(r'(?m)^---\s*$', text)
    return [safe_load(document) for document in documents if document.strip()]

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
    '.env.standalone.example', 'compose/docker-compose.standalone.yml',
    'scripts/tools/setup_local.py', 'scripts/tools/doctor_local.py',
    'scripts/tools/validate_ci_contract.py', 'scripts/tools/private_data_audit.py',
    'ansible/requirements.yml', 'ansible/requirements-modern.yml',
    '.sops.yaml.example', 'ansible/playbooks/preflight.yml',
    'ansible/playbooks/operator-kubeconfig.yml',
    'ansible/roles/rke2/templates/traefik-config.yaml.j2',
    'ansible/roles/rke2/templates/traefik-helmchart.yaml.j2',
    'helm/urban-platform-infra/Chart.yaml', 'helm/urban-platform-infra/values.yaml',
    'helm/urban-platform-infra/templates/databases-cnpg-imagecatalogs.yaml',
    'config/services.catalog.yaml', 'config/cluster-profiles.yaml',
    'config/deployment-topologies.yaml', 'config/secrets.contract.yaml',
    'config/secret-provider-adapters.yaml',
    'config/storage-tiers.yaml',
    'config/backup-policy.yaml',
    'config/platform-capabilities.yaml',
    'config/import-profiles.yaml',
    'config/lab-capacity.yaml',
    'config/image-cache.yaml',
    'config/registry-promotion.yaml',
    'config/runtime-hardening.yaml',
    'config/gitops-delivery.yaml',
    'config/progressive-delivery.yaml',
    'config/scaling-policy.yaml',
    'config/network-connectivity.yaml',
    'config/access-governance.yaml',
    'config/compliance-evidence.yaml',
    'config/incident-response.yaml',
    'config/change-management.yaml',
    'config/cutover-gates.yaml',
    'config/smoke-tests.yaml',
    'config/release-runbook.yaml',
    'config/cluster-upgrade.yaml',
    'config/disaster-recovery.yaml',
    'config/database-migration.yaml',
    'config/edge-migration.yaml',
    'config/environment-profiles.yaml',
    'config/supply-chain-policy.yaml', 'config/image-policy.yaml', 'config/slo.yaml',
    'scripts/images/validate-images.py', 'scripts/images/promotion_plan.py',
    'scripts/images/registry_promotion_controller.py',
    'scripts/runtime_hardening_plan.py',
    'scripts/gitops_delivery_plan.py',
    'scripts/progressive_delivery_plan.py',
    'scripts/scaling_policy_plan.py',
    'scripts/network_connectivity_plan.py',
    'scripts/access_governance_plan.py',
    'scripts/compliance_evidence_plan.py',
    'scripts/incident_response_plan.py',
    'scripts/change_management_plan.py',
    'scripts/cutover_gate_plan.py',
    'scripts/smoke_test_plan.py',
    'scripts/release_runbook_plan.py',
    'scripts/cluster_upgrade_plan.py',
    'scripts/disaster_recovery_plan.py',
    'scripts/release/generate_sbom.py',
    'scripts/release/verify_release_evidence.py',
    'scripts/backup_plan.py',
    'scripts/observability_plan.py',
    'scripts/cluster_doctor.py',
    'scripts/lab_deploy_plan.py',
    'scripts/capacity_preflight.py',
    'scripts/import_recovery_plan.py',
    'scripts/image_cache_plan.py',
    'scripts/database_migration_controller.py',
    'scripts/edge_migration_plan.py',
    'scripts/environment_profile_plan.py',
    'scripts/import_project.py',
    'scripts/migrate_project.py',
    'scripts/tools/install-helm.sh', 'scripts/tools/install-helmfile.sh',
    'scripts/tools/helmfile-sync-retry.sh',
    'scripts/tools/install-local-path-storage.sh', 'scripts/tools/recover-helm-release.sh',
    'scripts/tools/ensure-kubeconfig.sh', 'scripts/tools/standalone-docker-config.sh',
    'tests/policy/basic_policy.py', 'docs/hld.md', 'docs/lld.md',
    'docs/local-toolchain.md', 'docs/ci-validation.md',
    'docs/operator-workflows.md',
    'docs/bootstrap-safety.md', 'docs/secrets-management.md',
    'docs/secret-provider-adapters.md',
    'docs/supply-chain.md', 'docs/image-governance.md', 'docs/observability-slo.md',
    'docs/deployment-topologies.md', 'docs/storage-tiers.md',
    'docs/runbooks.md', 'docs/release-guide.md',
    'docs/project-import.md',
    'docs/import-recovery.md',
    'docs/cluster-doctor.md',
    'docs/lab-capacity.md',
    'docs/image-cache-preload.md',
    'docs/registry-promotion-controller.md',
    'docs/runtime-hardening-admission.md',
    'docs/gitops-delivery.md',
    'docs/progressive-delivery.md',
    'docs/scaling-policy.md',
    'docs/network-connectivity.md',
    'docs/access-governance.md',
    'docs/compliance-evidence.md',
    'docs/incident-response.md',
    'docs/change-management.md',
    'docs/cutover-gates.md',
    'docs/smoke-tests.md',
    'docs/release-runbook.md',
    'docs/cluster-upgrade.md',
    'docs/disaster-recovery.md',
    'docs/database-migration-controller.md',
    'docs/edge-migration.md',
    'docs/environment-profiles.md',
    'docs/backup-restore.md',
    'docs/platform-capabilities.md',
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
    Path('scripts/tools/private_data_audit.py'),
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
        return safe_load_all(f)

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

values = safe_load((ROOT / 'helm/urban-platform-infra/values.yaml').read_text())
if values['global']['cluster']['engine'] != 'rke2':
    errors.append('Default engine must be rke2')
if values['global']['cluster']['nodes'] != 3:
    errors.append('Default cluster node count must be 3')
if values['global'].get('replicaOverride') != 1:
    errors.append('Default global.replicaOverride must be 1 for the low-resource lab profile')
if values['global'].get('skipPlaceholderWorkloads') is not True:
    errors.append('Default placeholder workloads must be skipped for the low-resource lab profile')
if values.get('autoscaling', {}).get('enabled') is not False:
    errors.append('Autoscaling must default to disabled for the low-resource lab profile')
if values['webserver']['provider'] != 'nginx':
    errors.append('Default webserver must be nginx')
if values.get('secretManagement', {}).get('enabled') is not False:
    errors.append('Secret management chart rendering must be disabled by default')
secret_provider_adapters = values.get('secretManagement', {}).get('providerAdapters', {})
for secret_provider_name in ['kubernetesDirect', 'externalSecrets', 'vault', 'sops', 'sealedSecrets']:
    adapter_values = secret_provider_adapters.get(secret_provider_name, {})
    if adapter_values.get('enabled') is not False:
        errors.append(f'Secret provider adapter must be disabled by default: {secret_provider_name}')
    if secret_provider_name != 'kubernetesDirect' and adapter_values.get('rendersPlainKubernetesSecrets') is not False:
        errors.append(f'Secret provider adapter must not render plain Kubernetes Secrets: {secret_provider_name}')
image_promotion_controller_values = values.get('imagePromotionController', {})
if image_promotion_controller_values.get('enabled') is not False:
    errors.append('Image promotion controller must be disabled by default')
if image_promotion_controller_values.get('profile') != 'disabled':
    errors.append('Image promotion controller profile must default to disabled')
if image_promotion_controller_values.get('requireDigestPins') is not True:
    errors.append('Image promotion controller must require digest pins in production intent')
if image_promotion_controller_values.get('reports', {}).get('controller') != 'reports/registry-promotion-controller.md':
    errors.append('Image promotion controller must point at the public-safe controller report')
runtime_hardening_values = values.get('runtimeHardening', {})
if runtime_hardening_values.get('enabled') is not False:
    errors.append('Runtime hardening must be disabled by default')
if runtime_hardening_values.get('profile') != 'disabled':
    errors.append('Runtime hardening profile must default to disabled')
if runtime_hardening_values.get('policyEngine') != 'none':
    errors.append('Runtime hardening policy engine must default to none')
if runtime_hardening_values.get('workloadSecurity', {}).get('requireReadOnlyRootFilesystem') is not False:
    errors.append('Runtime hardening must not require read-only root filesystems by default')
if runtime_hardening_values.get('reports', {}).get('plan') != 'reports/runtime-hardening-plan.md':
    errors.append('Runtime hardening must point at the public-safe plan report')
gitops_delivery_values = values.get('gitOpsDelivery', {})
if gitops_delivery_values.get('enabled') is not False:
    errors.append('GitOps delivery must be disabled by default')
if gitops_delivery_values.get('profile') != 'operator-managed':
    errors.append('GitOps delivery profile must default to operator-managed')
if gitops_delivery_values.get('controller') != 'none':
    errors.append('GitOps delivery controller must default to none')
if gitops_delivery_values.get('driftDetection') != 'report-only':
    errors.append('GitOps delivery drift detection must default to report-only')
if gitops_delivery_values.get('prune') is not False:
    errors.append('GitOps delivery pruning must be disabled by default')
if gitops_delivery_values.get('reports', {}).get('plan') != 'reports/gitops-delivery-plan.md':
    errors.append('GitOps delivery must point at the public-safe plan report')
progressive_delivery_values = values.get('progressiveDelivery', {})
if progressive_delivery_values.get('enabled') is not False:
    errors.append('Progressive delivery must be disabled by default')
if progressive_delivery_values.get('profile') != 'disabled':
    errors.append('Progressive delivery profile must default to disabled')
if progressive_delivery_values.get('strategy') != 'rolling-update':
    errors.append('Progressive delivery strategy must default to rolling-update')
if progressive_delivery_values.get('controller') != 'none':
    errors.append('Progressive delivery controller must default to none')
if progressive_delivery_values.get('analysis', {}).get('mode') != 'disabled':
    errors.append('Progressive delivery analysis mode must default to disabled')
if progressive_delivery_values.get('reports', {}).get('plan') != 'reports/progressive-delivery-plan.md':
    errors.append('Progressive delivery must point at the public-safe plan report')
scaling_policy_values = values.get('scalingPolicy', {})
if scaling_policy_values.get('enabled') is not False:
    errors.append('Scaling policy must be disabled by default')
if scaling_policy_values.get('profile') != 'disabled':
    errors.append('Scaling policy profile must default to disabled')
if scaling_policy_values.get('mode') != 'disabled':
    errors.append('Scaling policy mode must default to disabled')
if scaling_policy_values.get('metricsSource') != 'none':
    errors.append('Scaling policy metrics source must default to none')
if scaling_policy_values.get('hpa', {}).get('enabled') is not False:
    errors.append('Scaling policy HPA must be disabled by default')
if scaling_policy_values.get('vpa', {}).get('enabled') is not False:
    errors.append('Scaling policy VPA must be disabled by default')
if scaling_policy_values.get('keda', {}).get('enabled') is not False:
    errors.append('Scaling policy KEDA must be disabled by default')
if scaling_policy_values.get('clusterAutoscaler', {}).get('enabled') is not False:
    errors.append('Scaling policy cluster autoscaler must be disabled by default')
if scaling_policy_values.get('reports', {}).get('plan') != 'reports/scaling-policy-plan.md':
    errors.append('Scaling policy must point at the public-safe plan report')
network_connectivity_values = values.get('networkConnectivity', {})
if network_connectivity_values.get('enabled') is not False:
    errors.append('Network connectivity must be disabled by default')
if network_connectivity_values.get('profile') != 'disabled':
    errors.append('Network connectivity profile must default to disabled')
if network_connectivity_values.get('mode') != 'baseline':
    errors.append('Network connectivity mode must default to baseline')
if network_connectivity_values.get('ingressClassName') != 'traefik':
    errors.append('Network connectivity ingress class must default to traefik')
if network_connectivity_values.get('networkPolicy', {}).get('enabled') is not True:
    errors.append('Network connectivity must preserve NetworkPolicy enabled intent by default')
if network_connectivity_values.get('serviceMesh', {}).get('enabled') is not False:
    errors.append('Network connectivity service mesh must be disabled by default')
if network_connectivity_values.get('serviceMesh', {}).get('provider') != 'none':
    errors.append('Network connectivity service mesh provider must default to none')
if network_connectivity_values.get('egress', {}).get('requireExplicitCidrs') is not False:
    errors.append('Network connectivity explicit CIDR requirement must be disabled by default')
if network_connectivity_values.get('reports', {}).get('plan') != 'reports/network-connectivity-plan.md':
    errors.append('Network connectivity must point at the public-safe plan report')
access_governance_values = values.get('accessGovernance', {})
if access_governance_values.get('enabled') is not False:
    errors.append('Access governance must be disabled by default')
if access_governance_values.get('profile') != 'disabled':
    errors.append('Access governance profile must default to disabled')
if access_governance_values.get('mode') != 'baseline':
    errors.append('Access governance mode must default to baseline')
if access_governance_values.get('rbac', {}).get('enabled') is not False:
    errors.append('Access governance RBAC automation must be disabled by default')
if access_governance_values.get('rbac', {}).get('serviceAccountTokenAutomount') is not False:
    errors.append('Access governance service account token automount must default to false')
if access_governance_values.get('identity', {}).get('enabled') is not False:
    errors.append('Access governance identity automation must be disabled by default')
if access_governance_values.get('identity', {}).get('provider') != 'none':
    errors.append('Access governance identity provider must default to none')
if access_governance_values.get('audit', {}).get('enabled') is not False:
    errors.append('Access governance audit automation must be disabled by default')
if access_governance_values.get('tenantIsolation', {}).get('enabled') is not False:
    errors.append('Access governance tenant isolation must be disabled by default')
if access_governance_values.get('reports', {}).get('plan') != 'reports/access-governance-plan.md':
    errors.append('Access governance must point at the public-safe plan report')
compliance_evidence_values = values.get('complianceEvidence', {})
if compliance_evidence_values.get('enabled') is not False:
    errors.append('Compliance evidence must be disabled by default')
if compliance_evidence_values.get('profile') != 'disabled':
    errors.append('Compliance evidence profile must default to disabled')
if compliance_evidence_values.get('mode') != 'baseline':
    errors.append('Compliance evidence mode must default to baseline')
if compliance_evidence_values.get('evidence', {}).get('collectReports') is not False:
    errors.append('Compliance evidence collection must be disabled by default')
if compliance_evidence_values.get('evidence', {}).get('requirePrivateIndex') is not False:
    errors.append('Compliance evidence private index requirement must default to false')
if compliance_evidence_values.get('retention', {}).get('enabled') is not False:
    errors.append('Compliance evidence retention must be disabled by default')
if compliance_evidence_values.get('packaging', {}).get('enabled') is not False:
    errors.append('Compliance evidence packaging must be disabled by default')
if compliance_evidence_values.get('reports', {}).get('plan') != 'reports/compliance-evidence-plan.md':
    errors.append('Compliance evidence must point at the public-safe plan report')
incident_response_values = values.get('incidentResponse', {})
if incident_response_values.get('enabled') is not False:
    errors.append('Incident response must be disabled by default')
if incident_response_values.get('profile') != 'disabled':
    errors.append('Incident response profile must default to disabled')
if incident_response_values.get('mode') != 'baseline':
    errors.append('Incident response mode must default to baseline')
if incident_response_values.get('severityModel') != 'none':
    errors.append('Incident response severity model must default to none')
if incident_response_values.get('alerting', {}).get('enabled') is not False:
    errors.append('Incident response alerting automation must be disabled by default')
if incident_response_values.get('alerting', {}).get('requirePaging') is not False:
    errors.append('Incident response paging requirement must default to false')
if incident_response_values.get('runbooks', {}).get('enabled') is not False:
    errors.append('Incident response runbook automation must be disabled by default')
if incident_response_values.get('communications', {}).get('enabled') is not False:
    errors.append('Incident response communications automation must be disabled by default')
if incident_response_values.get('drills', {}).get('enabled') is not False:
    errors.append('Incident response drill automation must be disabled by default')
if incident_response_values.get('reports', {}).get('plan') != 'reports/incident-response-plan.md':
    errors.append('Incident response must point at the public-safe plan report')
change_management_values = values.get('changeManagement', {})
if change_management_values.get('enabled') is not False:
    errors.append('Change management must be disabled by default')
if change_management_values.get('profile') != 'disabled':
    errors.append('Change management profile must default to disabled')
if change_management_values.get('mode') != 'baseline':
    errors.append('Change management mode must default to baseline')
if change_management_values.get('approvalModel') != 'none':
    errors.append('Change management approval model must default to none')
if change_management_values.get('changeControl', {}).get('enabled') is not False:
    errors.append('Change management control automation must be disabled by default')
if change_management_values.get('changeControl', {}).get('requireChangeTicket') is not False:
    errors.append('Change management ticket requirement must default to false')
if change_management_values.get('maintenanceWindow', {}).get('enabled') is not False:
    errors.append('Change management maintenance window automation must be disabled by default')
if change_management_values.get('rollout', {}).get('enabled') is not False:
    errors.append('Change management rollout gates must be disabled by default')
if change_management_values.get('evidence', {}).get('enabled') is not False:
    errors.append('Change management evidence collection must be disabled by default')
if change_management_values.get('reports', {}).get('plan') != 'reports/change-management-plan.md':
    errors.append('Change management must point at the public-safe plan report')
cutover_gates_values = values.get('cutoverGates', {})
if cutover_gates_values.get('enabled') is not False:
    errors.append('Cutover gates must be disabled by default')
if cutover_gates_values.get('profile') != 'disabled':
    errors.append('Cutover gates profile must default to disabled')
if cutover_gates_values.get('mode') != 'baseline':
    errors.append('Cutover gates mode must default to baseline')
if cutover_gates_values.get('trafficSwitch', {}).get('enabled') is not False:
    errors.append('Cutover traffic switch automation must be disabled by default')
if cutover_gates_values.get('trafficSwitch', {}).get('method') != 'none':
    errors.append('Cutover traffic switch method must default to none')
if cutover_gates_values.get('trafficSwitch', {}).get('requireDnsTlsEvidence') is not False:
    errors.append('Cutover DNS/TLS evidence requirement must default to false')
if cutover_gates_values.get('preCutover', {}).get('requireImportPreflight') is not False:
    errors.append('Cutover import preflight requirement must default to false')
if cutover_gates_values.get('preCutover', {}).get('requireReleaseEvidence') is not False:
    errors.append('Cutover release evidence requirement must default to false')
if cutover_gates_values.get('smokeTests', {}).get('enabled') is not False:
    errors.append('Cutover smoke-test automation must be disabled by default')
if cutover_gates_values.get('smokeTests', {}).get('requirePostMigrationCheck') is not False:
    errors.append('Cutover post-migration check requirement must default to false')
if cutover_gates_values.get('rollback', {}).get('enabled') is not False:
    errors.append('Cutover rollback automation must be disabled by default')
if cutover_gates_values.get('rollback', {}).get('requireRecoveryPlan') is not False:
    errors.append('Cutover recovery plan requirement must default to false')
if cutover_gates_values.get('postCutover', {}).get('enabled') is not False:
    errors.append('Cutover post-cutover automation must be disabled by default')
if cutover_gates_values.get('reports', {}).get('plan') != 'reports/cutover-gate-plan.md':
    errors.append('Cutover gates must point at the public-safe plan report')
smoke_testing_values = values.get('smokeTesting', {})
if smoke_testing_values.get('enabled') is not False:
    errors.append('Smoke testing must be disabled by default')
if smoke_testing_values.get('profile') != 'disabled':
    errors.append('Smoke testing profile must default to disabled')
if smoke_testing_values.get('mode') != 'baseline':
    errors.append('Smoke testing mode must default to baseline')
if smoke_testing_values.get('execution', {}).get('enabled') is not False:
    errors.append('Smoke testing execution must be disabled by default')
if smoke_testing_values.get('execution', {}).get('runner') != 'none':
    errors.append('Smoke testing runner must default to none')
if smoke_testing_values.get('probes', {}).get('kubernetesRollout') is not False:
    errors.append('Smoke testing Kubernetes rollout probes must be disabled by default')
if smoke_testing_values.get('probes', {}).get('databaseConnections') is not False:
    errors.append('Smoke testing database probes must be disabled by default')
if smoke_testing_values.get('probes', {}).get('messagingConnections') is not False:
    errors.append('Smoke testing messaging probes must be disabled by default')
if smoke_testing_values.get('evidence', {}).get('requirePlan') is not False:
    errors.append('Smoke testing plan evidence must be disabled by default')
if smoke_testing_values.get('evidence', {}).get('requireResults') is not False:
    errors.append('Smoke testing result evidence must be disabled by default')
if smoke_testing_values.get('evidence', {}).get('requireOwnerReview') is not False:
    errors.append('Smoke testing owner review must be disabled by default')
if smoke_testing_values.get('reports', {}).get('plan') != 'reports/smoke-test-plan.md':
    errors.append('Smoke testing must point at the public-safe plan report')
release_runbook_values = values.get('releaseRunbook', {})
if release_runbook_values.get('enabled') is not False:
    errors.append('Release runbook must be disabled by default')
if release_runbook_values.get('profile') != 'disabled':
    errors.append('Release runbook profile must default to disabled')
if release_runbook_values.get('mode') != 'baseline':
    errors.append('Release runbook mode must default to baseline')
if release_runbook_values.get('execution', {}).get('enabled') is not False:
    errors.append('Release runbook execution must be disabled by default')
if release_runbook_values.get('execution', {}).get('publisher') != 'none':
    errors.append('Release runbook publisher must default to none')
if release_runbook_values.get('execution', {}).get('deployer') != 'none':
    errors.append('Release runbook deployer must default to none')
for release_runbook_gate in [
    'requireReleaseTag',
    'requireCleanWorktree',
    'requireArtifactEvidence',
    'requireSbom',
    'requireChecksums',
    'requireAttestation',
    'requireChangeApproval',
    'requireSmokeTestPlan',
    'requireCutoverGate',
    'requireRollbackPlan',
]:
    if release_runbook_values.get('gates', {}).get(release_runbook_gate) is not False:
        errors.append(f'Release runbook gate {release_runbook_gate} must be disabled by default')
for release_runbook_evidence in [
    'requirePublicBundle',
    'requirePrivateApprovalIndex',
    'requireOwnerReview',
]:
    if release_runbook_values.get('evidence', {}).get(release_runbook_evidence) is not False:
        errors.append(f'Release runbook evidence {release_runbook_evidence} must be disabled by default')
if release_runbook_values.get('reports', {}).get('plan') != 'reports/release-runbook-plan.md':
    errors.append('Release runbook must point at the public-safe plan report')
cluster_upgrade_values = values.get('clusterUpgrade', {})
if cluster_upgrade_values.get('enabled') is not False:
    errors.append('Cluster upgrade must be disabled by default')
if cluster_upgrade_values.get('profile') != 'disabled':
    errors.append('Cluster upgrade profile must default to disabled')
if cluster_upgrade_values.get('mode') != 'baseline':
    errors.append('Cluster upgrade mode must default to baseline')
if cluster_upgrade_values.get('engine') != 'rke2':
    errors.append('Cluster upgrade engine must default to rke2')
if cluster_upgrade_values.get('orchestration', {}).get('enabled') is not False:
    errors.append('Cluster upgrade orchestration must be disabled by default')
if cluster_upgrade_values.get('orchestration', {}).get('strategy') != 'none':
    errors.append('Cluster upgrade strategy must default to none')
if cluster_upgrade_values.get('orchestration', {}).get('drainNodes') is not False:
    errors.append('Cluster upgrade node drain must be disabled by default')
if cluster_upgrade_values.get('orchestration', {}).get('restartServices') is not False:
    errors.append('Cluster upgrade service restart must be disabled by default')
if cluster_upgrade_values.get('versions', {}).get('maxMinorSkew') != 0:
    errors.append('Cluster upgrade max minor skew must default to zero')
for cluster_upgrade_gate in [
    'requirePinnedVersion',
    'requireSupportedSkew',
    'requireEtcdSnapshot',
    'requireBackupRestore',
    'requireMaintenanceWindow',
    'requireCapacityHeadroom',
    'requireNodeHealth',
    'requireRollbackPlan',
    'requireAddOnCompatibility',
    'requirePostUpgradeSmokeTest',
]:
    if cluster_upgrade_values.get('gates', {}).get(cluster_upgrade_gate) is not False:
        errors.append(f'Cluster upgrade gate {cluster_upgrade_gate} must be disabled by default')
for cluster_upgrade_evidence in [
    'requireClusterDoctor',
    'requireInventoryReview',
    'requireReleaseNotesReview',
    'requireOwnerApproval',
]:
    if cluster_upgrade_values.get('evidence', {}).get(cluster_upgrade_evidence) is not False:
        errors.append(f'Cluster upgrade evidence {cluster_upgrade_evidence} must be disabled by default')
if cluster_upgrade_values.get('reports', {}).get('plan') != 'reports/cluster-upgrade-plan.md':
    errors.append('Cluster upgrade must point at the public-safe plan report')
disaster_recovery_values = values.get('disasterRecovery', {})
if disaster_recovery_values.get('enabled') is not False:
    errors.append('Disaster recovery must be disabled by default')
if disaster_recovery_values.get('profile') != 'disabled':
    errors.append('Disaster recovery profile must default to disabled')
if disaster_recovery_values.get('mode') != 'baseline':
    errors.append('Disaster recovery mode must default to baseline')
if disaster_recovery_values.get('failoverModel') != 'none':
    errors.append('Disaster recovery failover model must default to none')
if disaster_recovery_values.get('recoveryObjectives', {}).get('enabled') is not False:
    errors.append('Disaster recovery objective automation must be disabled by default')
if disaster_recovery_values.get('replication', {}).get('enabled') is not False:
    errors.append('Disaster recovery replication automation must be disabled by default')
if disaster_recovery_values.get('restoreDrills', {}).get('enabled') is not False:
    errors.append('Disaster recovery drill automation must be disabled by default')
if disaster_recovery_values.get('continuity', {}).get('enabled') is not False:
    errors.append('Disaster recovery continuity automation must be disabled by default')
if disaster_recovery_values.get('evidence', {}).get('enabled') is not False:
    errors.append('Disaster recovery evidence collection must be disabled by default')
if disaster_recovery_values.get('reports', {}).get('plan') != 'reports/disaster-recovery-plan.md':
    errors.append('Disaster recovery must point at the public-safe plan report')
backup_values = values.get('backup', {})
if backup_values.get('enabled') is not False:
    errors.append('Global backup automation must be disabled by default')
if backup_values.get('profile') != 'disabled':
    errors.append('Default backup profile must be disabled')
if backup_values.get('velero', {}).get('enabled') is not False:
    errors.append('Velero backups must be disabled by default')
if backup_values.get('velero', {}).get('installOperator') is not False:
    errors.append('Velero operator installation must be disabled by default')
if backup_values.get('rke2Etcd', {}).get('enabled') is not False:
    errors.append('RKE2 etcd backup automation must be disabled by default')
if backup_values.get('imageArchives', {}).get('enabled') is not False:
    errors.append('Image archive backup retention must be disabled by default')
external_backup_providers = backup_values.get('externalProviders', {})
for external_backup_provider in ['urbackup', 'restic', 'kopia', 'borg']:
    provider_values = external_backup_providers.get(external_backup_provider, {})
    if provider_values.get('enabled') is not False:
        errors.append(f'External backup provider must be disabled by default: {external_backup_provider}')
    if provider_values.get('installInCluster') is True:
        errors.append(f'External backup provider must not install in-cluster by default: {external_backup_provider}')
ingress_values = values.get('ingress', {})
if ingress_values.get('tls', {}).get('enabled') is not True:
    errors.append('Ingress TLS must be enabled by default so HTTPS is available')
if ingress_values.get('className') != 'traefik':
    errors.append('Default ingress class must be traefik')
if ingress_values.get('sourceAllowList', {}).get('enabled') is not False:
    errors.append('Ingress source allowlist must default to disabled so lab access is not locked out accidentally')
for redirect_key in ['sslRedirect', 'forceSslRedirect']:
    if ingress_values.get(redirect_key) is not True:
        errors.append(f'Ingress HTTPS redirect must be enabled by default: {redirect_key}')
if values.get('webserver', {}).get('ingress', {}).get('enabled') is not False:
    errors.append('Webserver root ingress must be disabled by default; the imported gateway owns the public root route')
if values.get('namespace', {}).get('create') is not True:
    errors.append('Namespace manifest rendering must be enabled by default for GitOps and policy checks')
namespace_values = values.get('namespace', {})
if namespace_values.get('limitRange', {}).get('enabled') is not True:
    errors.append('Namespace LimitRange must be enabled by default for lab resource guardrails')
if namespace_values.get('resourceQuota', {}).get('enabled') is not True:
    errors.append('Namespace ResourceQuota must be enabled by default for lab resource guardrails')
if values.get('monitoring', {}).get('enabled') is not False:
    errors.append('Monitoring CRDs must be disabled by default so the chart renders before operators are installed')
timescaledb_values = values.get('databases', {}).get('instances', {}).get('timescaledb', {})
timescaledb_catalog_ref = timescaledb_values.get('imageCatalogRef', {})
if timescaledb_catalog_ref.get('kind') != 'ImageCatalog' or timescaledb_catalog_ref.get('major') != 18:
    errors.append('TimescaleDB must use a CNPG ImageCatalog reference for PostgreSQL 18 image detection')
timescaledb_catalog = values.get('databases', {}).get('imageCatalogs', {}).get('timescaledb', {})
if timescaledb_catalog.get('enabled') is not True:
    errors.append('TimescaleDB CNPG ImageCatalog must be enabled by default')
if timescaledb_values.get('postgresUID') != 70 or timescaledb_values.get('postgresGID') != 70:
    errors.append('TimescaleDB CNPG cluster must run the Alpine postgres user as UID/GID 70')
database_values = values.get('databases', {})
if database_values.get('postgresUID') != 999 or database_values.get('postgresGID') != 999:
    errors.append('CNPG database defaults must run Docker Hub Postgres-family images as UID/GID 999')
database_backup_values = database_values.get('backup', {})
if database_backup_values.get('enabled') is not False:
    errors.append('CloudNativePG backup rendering must be disabled by default')
if database_backup_values.get('objectStore', {}).get('enabled') is not False:
    errors.append('CloudNativePG object-store backups must be disabled by default')
if database_backup_values.get('schedule', {}).get('enabled') is not False:
    errors.append('CloudNativePG scheduled backups must be disabled by default')
platform_capability_values = values.get('platformCapabilities', {})
if platform_capability_values.get('enabled') is not False:
    errors.append('Optional platform capabilities must be disabled by default')
platform_capability_checks = {
    'minio': platform_capability_values.get('objectStorage', {}).get('minio', {}),
    'mqtt': platform_capability_values.get('messaging', {}).get('mqtt', {}),
    'emqx': platform_capability_values.get('messaging', {}).get('mqtt', {}).get('emqx', {}),
    'mosquitto': platform_capability_values.get('messaging', {}).get('mqtt', {}).get('mosquitto', {}),
    'rabbitmq': platform_capability_values.get('messaging', {}).get('rabbitmq', {}),
    'nats': platform_capability_values.get('messaging', {}).get('nats', {}),
    'schemaRegistry': platform_capability_values.get('kafkaEcosystem', {}).get('schemaRegistry', {}),
    'kafkaConnect': platform_capability_values.get('kafkaEcosystem', {}).get('kafkaConnect', {}),
    'debezium': platform_capability_values.get('kafkaEcosystem', {}).get('debezium', {}),
    'keycloak': platform_capability_values.get('identity', {}).get('keycloak', {}),
    'vault': platform_capability_values.get('secrets', {}).get('vault', {}),
    'kyverno': platform_capability_values.get('policy', {}).get('kyverno', {}),
    'temporal': platform_capability_values.get('workflows', {}).get('temporal', {}),
    'argoWorkflows': platform_capability_values.get('workflows', {}).get('argoWorkflows', {}),
    'serviceMesh': platform_capability_values.get('serviceMesh', {}),
    'linkerd': platform_capability_values.get('serviceMesh', {}).get('linkerd', {}),
    'istio': platform_capability_values.get('serviceMesh', {}).get('istio', {}),
}
for capability_name, capability_values in platform_capability_checks.items():
    if capability_values.get('enabled') is not False:
        errors.append(f'Optional platform capability must be disabled by default: {capability_name}')
observability_values = values.get('observability', {})
if observability_values.get('profile') != 'disabled' or observability_values.get('stack', {}).get('name') != 'disabled':
    errors.append('Default observability stack must be disabled for the low-resource lab profile')
for observability_component in ['elasticsearch', 'kibana', 'logstash', 'grafana', 'prometheus', 'opentelemetry', 'loki', 'clickhouse']:
    if observability_values.get(observability_component, {}).get('enabled') is not False:
        errors.append(f'Default observability component must be disabled: {observability_component}')
elasticsearch_resources = observability_values.get('elasticsearch', {}).get('resources', {})
if not elasticsearch_resources.get('requests', {}).get('cpu') or not elasticsearch_resources.get('limits', {}).get('cpu'):
    errors.append('Default Elasticsearch ECK resources must include CPU requests and limits')
if observability_values.get('elasticsearch', {}).get('service', {}).get('nodePort') != 30920:
    errors.append('Default Elasticsearch service must expose the expected NodePort 30920 for edge VIP forwarding')
kibana_values = observability_values.get('kibana', {})
if kibana_values.get('service', {}).get('nodePort') != 30561:
    errors.append('Default Kibana service must expose the expected NodePort 30561 for edge VIP forwarding')
if kibana_values.get('ingress', {}).get('enabled') is True:
    errors.append('Default Kibana ingress must not own the public root route')
gateway_values = values.get('workloads', {}).get('app-27', {})
if gateway_values.get('category') != 'gateway':
    errors.append('app-27 must remain the imported gateway workload')
if gateway_values.get('ingress', {}).get('path') != '/':
    errors.append('Imported gateway workload app-27 must own the public root path')
if gateway_values.get('ports', [{}])[0].get('servicePort') != 5000:
    errors.append('Imported gateway workload app-27 must expose service port 5000')
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
    'RELEASE_MANIFEST',
    '--manifest "${RELEASE_MANIFEST}"',
    'SHA256SUMS',
    'release-evidence.json',
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
    'Validate CI contract',
    'scripts/tools/validate_ci_contract.py',
    'Audit private data guardrails',
    'scripts/tools/private_data_audit.py',
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
    'pip install -r requirements-ci-modern.txt',
    'python3 scripts/tools/validate_ci_contract.py',
    'python3 scripts/tools/private_data_audit.py',
    'release-evidence:',
    'SHA256SUMS',
    'release-evidence.json',
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
    'Clean stale bundled Traefik Helm controller resources',
    'rke2_cleanup_stale_bundled_traefik',
    'helm-delete-rke2-traefik-crd',
    'wrangler.cattle.io/on-helm-chart-remove',
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
    'auto_repair_cluster_enabled',
    'MIGRATION_REPAIR_MIN_REACHABLE_RKE2_NODES',
    'minimum_reachable_repair_nodes',
    'Automatic HA repair requires at least',
    'MIGRATION_KEEPALIVED_AUTH_PASS',
    'MIGRATION_KEEPALIVED_INTERFACE',
    'MIGRATION_BECOME_PASSWORD_PROMPT',
    'validate_become_password_input',
    'prompt_for_become_password_if_needed',
    'MIGRATION_SKIP_UNREACHABLE_RKE2_NODES',
    'filter_ssh_reachable_nodes',
    'recover_become_password_from_fallback_inventory',
    'remote_sudo_sh',
    'rewrite_existing_kubeconfig_endpoint',
    'kubernetes_api_ready_verbose',
    '/openapi/v2',
    'MIGRATION_KUBE_API_OPENAPI_TIMEOUT',
    'tls-server-name',
    'MIGRATION_KUBE_API_TLS_SERVER_NAME',
    'MIGRATION_KUBE_API_TUNNEL_REMOTE_HOST',
    'Trying existing operator kubeconfig against',
    'Existing kubeconfig was not ready through direct endpoints; trying SSH tunnel fallback',
    'normalize_rke2_version',
    'Existing operator kubeconfig is ready',
    'command -v kubectl',
    'discover_remote_cluster_vip',
    'discover_remote_rke2_token',
    'discover_remote_rke2_version',
    'discover_remote_rke2_version_from_nodes',
    'write_kubeconfig_from_available_node',
    '/var/lib/rancher/rke2/bin/rke2 --version',
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
if 'Recovered MIGRATION_RKE2_NODES from ${FALLBACK_INVENTORY_PATH}: ${MIGRATION_RKE2_NODES}' in kubeconfig_script_text:
    errors.append('Kubeconfig helper must not print recovered RKE2 node addresses')

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
for workload_template_token in [
    'skipPlaceholderWorkloads',
    'regexMatch "^example-app-[0-9]+$"',
]:
    if workload_template_token not in workload_template_text:
        errors.append(f'Workload template missing token: {workload_template_token}')

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
    '$webserverIngressEnabled',
    'ne (toString .Values.webserver.ingress.enabled) "false"',
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
    'cip.traefikSourceAllowListMiddlewareRef',
    'cip.ingressSourceAllowListCidrs',
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
    'ipAllowList:',
    'sourceRange:',
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
for cnpg_cluster_token in ['postgresUID:', 'postgresGID:', '$db.postgresUID', '$db.postgresGID']:
    if cnpg_cluster_token not in cnpg_cluster_template_text:
        errors.append(f'CNPG cluster template missing Postgres image UID/GID token: {cnpg_cluster_token}')
for cnpg_cluster_token in ['barmanObjectStore:', 'retentionPolicy:', 'kind: ScheduledBackup', '$backupReady']:
    if cnpg_cluster_token not in cnpg_cluster_template_text:
        errors.append(f'CNPG cluster template missing disabled backup support token: {cnpg_cluster_token}')
cnpg_catalog_template_text = (
    ROOT / 'helm/urban-platform-infra/templates/databases-cnpg-imagecatalogs.yaml'
).read_text(encoding='utf-8')
for cnpg_catalog_token in ['kind: ImageCatalog', '.Values.databases.imageCatalogs', 'include "cip.image"']:
    if cnpg_catalog_token not in cnpg_catalog_template_text:
        errors.append(f'CNPG ImageCatalog template missing token: {cnpg_catalog_token}')
networkpolicy_template_text = (ROOT / 'helm/urban-platform-infra/templates/networkpolicy.yaml').read_text(
    encoding='utf-8'
)
for networkpolicy_token in [
    'urban-platform-cnpg-operator-ingress',
    '.Values.networkPolicy.cloudnativePgOperator.namespace',
    'app.kubernetes.io/managed-by: cloudnative-pg',
    'urban-platform-eck-operator-ingress',
    '.Values.networkPolicy.eckOperator.namespace',
    'common.k8s.elastic.co/type: elasticsearch',
]:
    if networkpolicy_token not in networkpolicy_template_text:
        errors.append(f'NetworkPolicy template missing operator ingress token: {networkpolicy_token}')

makefile_text = (ROOT / 'Makefile').read_text(encoding='utf-8')
if 'CONFIRM_PROD' not in makefile_text:
    errors.append('Makefile mutating Ansible targets must require production confirmation')
if 'bootstrap-check' not in makefile_text or 'install-cluster-check' not in makefile_text:
    errors.append('Makefile must expose Ansible check-mode targets')
if re.search(r'^PROJECT_PATH\s*\?=\s*/', makefile_text, re.MULTILINE):
    errors.append('PROJECT_PATH must not have a committed machine-specific absolute default')
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
    'MIGRATION_FALLBACK_INVENTORY ?=',
    'MIGRATION_CLUSTER_DOMAIN ?=',
    'MIGRATION_PROFILE ?= lab',
    'MIGRATION_LAB_WORKLOAD_CPU_REQUEST ?=',
    'MIGRATION_LAB_WORKLOAD_MEMORY_REQUEST ?=',
    'MIGRATION_LAB_WORKLOAD_CPU_LIMIT ?=',
    'MIGRATION_LAB_WORKLOAD_MEMORY_LIMIT ?=',
    'MIGRATION_PREFLIGHT_MIN_NODE_MEMORY ?=',
    'MIGRATION_PREFLIGHT_MIN_NODE_DISK_FREE ?=',
    'MIGRATION_PREFLIGHT_MAX_IMPORTED_WORKLOADS ?=',
    'MIGRATION_PREFLIGHT_CAPACITY_UTILIZATION_LIMIT ?=',
    'MIGRATION_PREFLIGHT_REQUIRE_INGRESS_ENDPOINT ?=',
    'MIGRATION_BATCH_SIZE ?=',
    'MIGRATION_IMPORT_BATCH ?=',
    'MIGRATION_RUNTIME_VALIDATION_TIMEOUT ?=',
    'MIGRATION_RUNTIME_VALIDATION_INTERVAL ?=',
    'MIGRATION_STATE_FILE ?=',
    'MIGRATION_RESUME ?= true',
    'MIGRATION_FORCE_RERUN ?= false',
    'IMPORT_RECOVERY_OUTPUT ?=',
    'MIGRATION_IMAGE_MODE ?= $(if $(filter lab,$(MIGRATION_PROFILE)),preload,registry)',
    'MIGRATION_RKE2_VERSION ?=',
    'MIGRATION_AUTO_REPAIR_CLUSTER ?=',
    'MIGRATION_BECOME_PASSWORD_PROMPT ?=',
    'MIGRATION_KEEPALIVED_AUTH_PASS ?=',
    'MIGRATION_KEEPALIVED_INTERFACE ?=',
    'MIGRATION_IMAGE_MODE ?=',
    'MIGRATION_RKE2_NODES ?=',
    'MIGRATION_SKIP_UNAVAILABLE_DATABASES ?= $(if $(filter production,$(MIGRATION_PROFILE)),false,true)',
    'MIGRATION_SECRET_PROVIDER ?=',
    'MIGRATION_SECRET_REMOTE_PREFIX ?=',
    'MIGRATION_SECRET_STORE_NAME ?=',
    'MIGRATION_SECRET_STORE_KIND ?=',
    'MIGRATION_SECRET_REFRESH_INTERVAL ?=',
    'REGISTRY_PROMOTION_CONFIG ?=',
    'REGISTRY_PROMOTION_PROFILE ?=',
    'REGISTRY_PROMOTION_REGISTRY ?=',
    'REGISTRY_PROMOTION_OUTPUT ?=',
    'REGISTRY_PROMOTION_VALUES ?=',
    'registry-promotion-plan:',
    'scripts/images/registry_promotion_controller.py',
    '--config "$(REGISTRY_PROMOTION_CONFIG)"',
    '--overrides "$(REGISTRY_PROMOTION_VALUES)"',
    'RUNTIME_HARDENING_CONFIG ?=',
    'RUNTIME_HARDENING_PROFILE ?=',
    'RUNTIME_HARDENING_OUTPUT ?=',
    'RUNTIME_HARDENING_VALUES ?=',
    'runtime-hardening-plan:',
    'scripts/runtime_hardening_plan.py',
    '--config "$(RUNTIME_HARDENING_CONFIG)"',
    '--overrides "$(RUNTIME_HARDENING_VALUES)"',
    'GITOPS_DELIVERY_CONFIG ?=',
    'GITOPS_DELIVERY_PROFILE ?=',
    'GITOPS_DELIVERY_REPO_URL ?=',
    'GITOPS_DELIVERY_TARGET_REVISION ?=',
    'GITOPS_DELIVERY_VALUES_PATH ?=',
    'GITOPS_DELIVERY_OUTPUT ?=',
    'GITOPS_DELIVERY_VALUES ?=',
    'gitops-delivery-plan:',
    'scripts/gitops_delivery_plan.py',
    '--config "$(GITOPS_DELIVERY_CONFIG)"',
    '--profile "$(GITOPS_DELIVERY_PROFILE)"',
    '--repo-url "$(GITOPS_DELIVERY_REPO_URL)"',
    '--overrides "$(GITOPS_DELIVERY_VALUES)"',
    'PROGRESSIVE_DELIVERY_CONFIG ?=',
    'PROGRESSIVE_DELIVERY_PROFILE ?=',
    'PROGRESSIVE_DELIVERY_GITOPS_PROFILE ?=',
    'PROGRESSIVE_DELIVERY_RUNTIME_PROFILE ?=',
    'PROGRESSIVE_DELIVERY_SLO_SOURCE ?=',
    'PROGRESSIVE_DELIVERY_ROLLBACK_DRILL ?=',
    'PROGRESSIVE_DELIVERY_OUTPUT ?=',
    'PROGRESSIVE_DELIVERY_VALUES ?=',
    'progressive-delivery-plan:',
    'scripts/progressive_delivery_plan.py',
    '--config "$(PROGRESSIVE_DELIVERY_CONFIG)"',
    '--profile "$(PROGRESSIVE_DELIVERY_PROFILE)"',
    '--rollback-drill',
    '--overrides "$(PROGRESSIVE_DELIVERY_VALUES)"',
    'SCALING_POLICY_CONFIG ?=',
    'SCALING_POLICY_PROFILE ?=',
    'SCALING_POLICY_METRICS_SOURCE ?=',
    'SCALING_POLICY_EVENT_SOURCE ?=',
    'SCALING_POLICY_CAPACITY_REPORT ?=',
    'SCALING_POLICY_LOAD_TEST_EVIDENCE ?=',
    'SCALING_POLICY_OUTPUT ?=',
    'SCALING_POLICY_VALUES ?=',
    'scaling-policy-plan:',
    'scripts/scaling_policy_plan.py',
    '--config "$(SCALING_POLICY_CONFIG)"',
    '--profile "$(SCALING_POLICY_PROFILE)"',
    '--load-test-evidence',
    '--overrides "$(SCALING_POLICY_VALUES)"',
    'NETWORK_CONNECTIVITY_CONFIG ?=',
    'NETWORK_CONNECTIVITY_PROFILE ?=',
    'NETWORK_CONNECTIVITY_TRAFFIC_INVENTORY ?=',
    'NETWORK_CONNECTIVITY_EGRESS_CONTRACT ?=',
    'NETWORK_CONNECTIVITY_DNS_TLS_EVIDENCE ?=',
    'NETWORK_CONNECTIVITY_MESH_READINESS ?=',
    'NETWORK_CONNECTIVITY_OUTPUT ?=',
    'NETWORK_CONNECTIVITY_VALUES ?=',
    'network-connectivity-plan:',
    'scripts/network_connectivity_plan.py',
    '--config "$(NETWORK_CONNECTIVITY_CONFIG)"',
    '--profile "$(NETWORK_CONNECTIVITY_PROFILE)"',
    '--dns-tls-evidence',
    '--mesh-readiness',
    '--overrides "$(NETWORK_CONNECTIVITY_VALUES)"',
    'ACCESS_GOVERNANCE_CONFIG ?=',
    'ACCESS_GOVERNANCE_PROFILE ?=',
    'ACCESS_GOVERNANCE_IDENTITY_PROVIDER ?=',
    'ACCESS_GOVERNANCE_GROUP_MAPPING ?=',
    'ACCESS_GOVERNANCE_TENANT_MODEL ?=',
    'ACCESS_GOVERNANCE_RBAC_INVENTORY ?=',
    'ACCESS_GOVERNANCE_AUDIT_EVIDENCE ?=',
    'ACCESS_GOVERNANCE_BREAK_GLASS_REVIEW ?=',
    'ACCESS_GOVERNANCE_OUTPUT ?=',
    'ACCESS_GOVERNANCE_VALUES ?=',
    'access-governance-plan:',
    'scripts/access_governance_plan.py',
    '--config "$(ACCESS_GOVERNANCE_CONFIG)"',
    '--profile "$(ACCESS_GOVERNANCE_PROFILE)"',
    '--audit-evidence',
    '--break-glass-review',
    '--overrides "$(ACCESS_GOVERNANCE_VALUES)"',
    'COMPLIANCE_EVIDENCE_CONFIG ?=',
    'COMPLIANCE_EVIDENCE_PROFILE ?=',
    'COMPLIANCE_EVIDENCE_RELEASE_TAG ?=',
    'COMPLIANCE_EVIDENCE_PRIVATE_INDEX ?=',
    'COMPLIANCE_EVIDENCE_RESTORE_DRILL ?=',
    'COMPLIANCE_EVIDENCE_ACCESS_REVIEW ?=',
    'COMPLIANCE_EVIDENCE_INCIDENT_DRILL ?=',
    'COMPLIANCE_EVIDENCE_OUTPUT ?=',
    'COMPLIANCE_EVIDENCE_VALUES ?=',
    'compliance-evidence-plan:',
    'scripts/compliance_evidence_plan.py',
    '--config "$(COMPLIANCE_EVIDENCE_CONFIG)"',
    '--profile "$(COMPLIANCE_EVIDENCE_PROFILE)"',
    '--restore-drill-evidence',
    '--access-review-evidence',
    '--incident-drill-evidence',
    '--overrides "$(COMPLIANCE_EVIDENCE_VALUES)"',
    'INCIDENT_RESPONSE_CONFIG ?=',
    'INCIDENT_RESPONSE_PROFILE ?=',
    'INCIDENT_RESPONSE_ALERT_ROUTE_SOURCE ?=',
    'INCIDENT_RESPONSE_ESCALATION_ROTA ?=',
    'INCIDENT_RESPONSE_PAGER_SERVICE ?=',
    'INCIDENT_RESPONSE_RUNBOOK_SOURCE ?=',
    'INCIDENT_RESPONSE_INCIDENT_DRILL ?=',
    'INCIDENT_RESPONSE_POST_INCIDENT_REVIEW ?=',
    'INCIDENT_RESPONSE_OUTPUT ?=',
    'INCIDENT_RESPONSE_VALUES ?=',
    'incident-response-plan:',
    'scripts/incident_response_plan.py',
    '--config "$(INCIDENT_RESPONSE_CONFIG)"',
    '--profile "$(INCIDENT_RESPONSE_PROFILE)"',
    '--incident-drill',
    '--post-incident-review',
    '--overrides "$(INCIDENT_RESPONSE_VALUES)"',
    'CHANGE_MANAGEMENT_CONFIG ?=',
    'CHANGE_MANAGEMENT_PROFILE ?=',
    'CHANGE_MANAGEMENT_TICKET ?=',
    'CHANGE_MANAGEMENT_FREEZE_CHECK ?=',
    'CHANGE_MANAGEMENT_STAKEHOLDER_NOTICE ?=',
    'CHANGE_MANAGEMENT_POST_CHANGE_REVIEW ?=',
    'CHANGE_MANAGEMENT_OUTPUT ?=',
    'CHANGE_MANAGEMENT_VALUES ?=',
    'change-management-plan:',
    'scripts/change_management_plan.py',
    '--config "$(CHANGE_MANAGEMENT_CONFIG)"',
    '--profile "$(CHANGE_MANAGEMENT_PROFILE)"',
    '--freeze-check',
    '--stakeholder-notice',
    '--post-change-review',
    '--overrides "$(CHANGE_MANAGEMENT_VALUES)"',
    'CUTOVER_GATES_CONFIG ?=',
    'CUTOVER_GATES_PROFILE ?=',
    'CUTOVER_GATES_OUTPUT ?=',
    'CUTOVER_GATES_VALUES ?=',
    'CUTOVER_DNS_TLS_EVIDENCE ?=',
    'CUTOVER_OWNER_HANDOFF ?=',
    'cutover-gate-plan:',
    'scripts/cutover_gate_plan.py',
    '--config "$(CUTOVER_GATES_CONFIG)"',
    '--profile "$(CUTOVER_GATES_PROFILE)"',
    '--dns-tls-evidence',
    '--owner-handoff',
    '--overrides "$(CUTOVER_GATES_VALUES)"',
    'SMOKE_TEST_CONFIG ?=',
    'SMOKE_TEST_PROFILE ?=',
    'SMOKE_TEST_OUTPUT ?=',
    'SMOKE_TEST_VALUES ?=',
    'SMOKE_TEST_EVIDENCE ?=',
    'smoke-test-plan:',
    'scripts/smoke_test_plan.py',
    '--config "$(SMOKE_TEST_CONFIG)"',
    '--profile "$(SMOKE_TEST_PROFILE)"',
    '--overrides "$(SMOKE_TEST_VALUES)"',
    'RELEASE_RUNBOOK_CONFIG ?=',
    'RELEASE_RUNBOOK_PROFILE ?=',
    'RELEASE_RUNBOOK_RELEASE_EVIDENCE ?=',
    'RELEASE_RUNBOOK_OUTPUT ?=',
    'RELEASE_RUNBOOK_VALUES ?=',
    'release-runbook-plan:',
    'scripts/release_runbook_plan.py',
    '--config "$(RELEASE_RUNBOOK_CONFIG)"',
    '--profile "$(RELEASE_RUNBOOK_PROFILE)"',
    '--release-evidence "$(RELEASE_RUNBOOK_RELEASE_EVIDENCE)"',
    '--overrides "$(RELEASE_RUNBOOK_VALUES)"',
    'CLUSTER_UPGRADE_CONFIG ?=',
    'CLUSTER_UPGRADE_PROFILE ?=',
    'CLUSTER_UPGRADE_TARGET_RKE2 ?=',
    'CLUSTER_UPGRADE_OUTPUT ?=',
    'CLUSTER_UPGRADE_VALUES ?=',
    'cluster-upgrade-plan:',
    'scripts/cluster_upgrade_plan.py',
    '--config "$(CLUSTER_UPGRADE_CONFIG)"',
    '--profile "$(CLUSTER_UPGRADE_PROFILE)"',
    '--target-rke2 "$(CLUSTER_UPGRADE_TARGET_RKE2)"',
    '--overrides "$(CLUSTER_UPGRADE_VALUES)"',
    'DISASTER_RECOVERY_CONFIG ?=',
    'DISASTER_RECOVERY_PROFILE ?=',
    'DISASTER_RECOVERY_RTO_RPO ?=',
    'DISASTER_RECOVERY_DEPENDENCY_MAP ?=',
    'DISASTER_RECOVERY_BACKUP_REPLICATION ?=',
    'DISASTER_RECOVERY_POST_DRILL_REVIEW ?=',
    'DISASTER_RECOVERY_OUTPUT ?=',
    'DISASTER_RECOVERY_VALUES ?=',
    'disaster-recovery-plan:',
    'scripts/disaster_recovery_plan.py',
    '--config "$(DISASTER_RECOVERY_CONFIG)"',
    '--profile "$(DISASTER_RECOVERY_PROFILE)"',
    '--rto-rpo "$(DISASTER_RECOVERY_RTO_RPO)"',
    '--dependency-map "$(DISASTER_RECOVERY_DEPENDENCY_MAP)"',
    '--post-drill-review',
    '--overrides "$(DISASTER_RECOVERY_VALUES)"',
    '--image-mode "$(MIGRATION_IMAGE_MODE)"',
    '--rke2-nodes "$(MIGRATION_RKE2_NODES)"',
    '--private-dir "$(MIGRATION_PRIVATE_DIR)"',
    '--profile "$(MIGRATION_PROFILE)"',
    '--lab-workload-cpu-request "$(MIGRATION_LAB_WORKLOAD_CPU_REQUEST)"',
    '--lab-workload-memory-request "$(MIGRATION_LAB_WORKLOAD_MEMORY_REQUEST)"',
    '--lab-workload-cpu-limit "$(MIGRATION_LAB_WORKLOAD_CPU_LIMIT)"',
    '--lab-workload-memory-limit "$(MIGRATION_LAB_WORKLOAD_MEMORY_LIMIT)"',
    '--preflight-min-node-memory "$(MIGRATION_PREFLIGHT_MIN_NODE_MEMORY)"',
    '--preflight-min-node-disk-free "$(MIGRATION_PREFLIGHT_MIN_NODE_DISK_FREE)"',
    '--preflight-max-imported-workloads "$(MIGRATION_PREFLIGHT_MAX_IMPORTED_WORKLOADS)"',
    '--preflight-capacity-utilization-limit "$(MIGRATION_PREFLIGHT_CAPACITY_UTILIZATION_LIMIT)"',
    '--batch-size "$(MIGRATION_BATCH_SIZE)"',
    '--import-batch "$(MIGRATION_IMPORT_BATCH)"',
    '--state-file "$(MIGRATION_STATE_FILE)"',
    '--secret-provider "$(MIGRATION_SECRET_PROVIDER)"',
    '--secret-remote-prefix "$(MIGRATION_SECRET_REMOTE_PREFIX)"',
    '--secret-store-name "$(MIGRATION_SECRET_STORE_NAME)"',
    '--force-rerun',
    '--preflight-require-ingress-endpoint',
    '--stage "$(MIGRATION_STAGE)"',
    '--auto-prepare',
    '--ingress-controller $(INGRESS)',
    'import-check:',
    'import-preflight:',
    'import-recovery-plan:',
    'import-migrate:',
    'scripts/import_project.py --project-path "$(PROJECT_PATH)"',
    'scripts/import_recovery_plan.py',
    'scripts/migrate_project.py --project-path "$(PROJECT_PATH)"',
    '--redact-sensitive',
    'OPERATOR_KUBECONFIG ?=',
    'KUBECONFIG_SCRIPT ?= scripts/tools/ensure-kubeconfig.sh',
    'operator-kubeconfig:',
    'OPERATOR_KUBECONFIG_FORCE_REPAIR',
    'import-auto: MIGRATION_AUTO_REPAIR_CLUSTER = true',
    'OPERATOR_KUBECONFIG=$(OPERATOR_KUBECONFIG)',
    'MIGRATION_SSH_KEY="$(MIGRATION_SSH_KEY)"',
    'MIGRATION_BECOME_PASSWORD_PROMPT="$(MIGRATION_BECOME_PASSWORD_PROMPT)"',
    'MIGRATION_CLUSTER_DOMAIN="$(MIGRATION_CLUSTER_DOMAIN)"',
    'MIGRATION_RKE2_VERSION="$(MIGRATION_RKE2_VERSION)"',
    'MIGRATION_AUTO_REPAIR_CLUSTER="$(MIGRATION_AUTO_REPAIR_CLUSTER)"',
    'MIGRATION_KEEPALIVED_AUTH_PASS="$(MIGRATION_KEEPALIVED_AUTH_PASS)"',
    'MIGRATION_KEEPALIVED_INTERFACE="$(MIGRATION_KEEPALIVED_INTERFACE)"',
    'MIGRATION_DEPLOY_PLATFORM ?= true',
    'MIGRATION_RELAX_RESOURCE_QUOTA ?=',
    'MIGRATION_TLS_MODE ?= auto',
    'MIGRATION_TLS_PFX_FILE ?=',
    'MIGRATION_TLS_LE_CREATE_ISSUER ?= true',
    'MIGRATION_IMPORT_SECURITY_CONTEXT ?= $(if $(filter production,$(MIGRATION_PROFILE)),restricted,compat)',
    '--tls-mode "$(MIGRATION_TLS_MODE)"',
    '--tls-pfx-file "$(MIGRATION_TLS_PFX_FILE)"',
    '--tls-le-email "$(MIGRATION_TLS_LE_EMAIL)"',
    '--import-security-context "$(MIGRATION_IMPORT_SECURITY_CONTEXT)"',
    'Deploying/upgrading the platform chart before import',
    'Skipping platform Helm deploy because MIGRATION_DEPLOY_PLATFORM=',
    '$(MAKE) deploy-auto VALUES="$(VALUES)" NAMESPACE="$(MIGRATION_NAMESPACE)"',
    'DEPLOY_NAMESPACE_RESOURCE_QUOTA="$(if $(filter true,$(MIGRATION_RELAX_RESOURCE_QUOTA)),false,$(DEPLOY_NAMESPACE_RESOURCE_QUOTA))"',
    '--set namespace.resourceQuota.enabled=$(DEPLOY_NAMESPACE_RESOURCE_QUOTA)',
    'install-helm:',
    'HELM_INSTALL_SCRIPT',
    'install-helmfile:',
    'HELMFILE_CONFIG',
    'deploy/helmfile.yaml.gotmpl',
    'HELMFILE_INSTALL_SCRIPT',
    'HELMFILE_SYNC_SCRIPT',
    'scripts/tools/helmfile-sync-retry.sh',
    'HELMFILE_SYNC_RETRIES',
    'INSTALL_VELERO',
    'install-local-path-storage:',
    'ensure-storageclass:',
    'INSTALL_LOCAL_PATH_STORAGE',
    'scripts/tools/install-local-path-storage.sh',
    'recover-helm-release:',
    'scripts/tools/recover-helm-release.sh',
    'DEPLOY_RECOVER_FAILED_RELEASE',
    'deploy-auto:',
    'DEPLOY_LAB_STORAGE',
    'DEPLOY_LAB_REPLICA_OVERRIDE',
    'DEPLOY_SKIP_PLACEHOLDER_WORKLOADS',
    'DEPLOY_ALLOWED_CIDRS',
    'DEPLOY_CONFIGURE_EDGE_PORTS',
    'DEPLOY_ENABLE_ECK',
    'DEPLOY_ENABLE_PROMETHEUS',
    'DEPLOY_ENABLE_GRAFANA',
    'DEPLOY_ENABLE_OPENTELEMETRY',
    'DEPLOY_ENABLE_ELASTICSEARCH',
    'DEPLOY_ENABLE_KIBANA',
    'DEPLOY_ENABLE_LOGSTASH',
    'DEPLOY_ENABLE_LOKI',
    'DEPLOY_ENABLE_CLICKHOUSE',
    'DEPLOY_ENABLE_VELERO',
    'DEPLOY_ENABLE_MINIO',
    'DEPLOY_ENABLE_RABBITMQ',
    'DEPLOY_ENABLE_KEYCLOAK',
    'DEPLOY_ENABLE_EMQX',
    'DEPLOY_ENABLE_NATS',
    'DEPLOY_ENABLE_VAULT',
    'DEPLOY_ENABLE_KYVERNO',
    'DEPLOY_ENABLE_TEMPORAL',
    'DEPLOY_ENABLE_ARGO_WORKFLOWS',
    'DEPLOY_ENABLE_LINKERD',
    'DEPLOY_ENABLE_ISTIO',
    'VELERO_PROVIDER ?=',
    'VELERO_BUCKET ?=',
    'VELERO_EXISTING_SECRET ?=',
    'VELERO_SNAPSHOTS_ENABLED ?=',
    'BACKUP_POLICY ?=',
    'BACKUP_OUTPUT ?=',
    'backup-plan:',
    'scripts/backup_plan.py',
    'OBSERVABILITY_CONFIG ?=',
    'SLO_CONFIG ?=',
    'OBSERVABILITY_PLAN_OUTPUT ?=',
    'observability-plan:',
    'scripts/observability_plan.py',
    'CLUSTER_DOCTOR_OUTPUT ?=',
    'CLUSTER_DOCTOR_NODES ?=',
    'CLUSTER_DOCTOR_REPAIR ?=',
    'cluster-doctor:',
    'cluster-repair:',
    'scripts/cluster_doctor.py',
    'LAB_CAPACITY_CONFIG ?=',
    'LAB_DEPLOY_OUTPUT ?=',
    'LAB_DEPLOY_VALUES ?=',
    'CAPACITY_PREFLIGHT_OUTPUT ?=',
    'CAPACITY_PREFLIGHT_ENV_PROFILE ?=',
    'CAPACITY_PREFLIGHT_IMPORT_BATCH ?=',
    'lab-deploy-plan:',
    'capacity-preflight:',
    'scripts/lab_deploy_plan.py',
    'scripts/capacity_preflight.py',
    'IMAGE_CACHE_CONFIG ?=',
    'IMAGE_CACHE_PROFILE ?=',
    'IMAGE_CACHE_OUTPUT ?=',
    'image-cache-plan:',
    'scripts/image_cache_plan.py',
    'DB_MIGRATION_CONFIG ?=',
    'DB_MIGRATION_PROFILE ?=',
    'DB_MIGRATION_OUTPUT ?=',
    'database-migration-plan:',
    'scripts/database_migration_controller.py',
    'EDGE_MIGRATION_CONFIG ?=',
    'EDGE_MIGRATION_PROFILE ?=',
    'EDGE_MIGRATION_OUTPUT ?=',
    'edge-migration-plan:',
    'scripts/edge_migration_plan.py',
    'ENV_PROFILE_CONFIG ?=',
    'ENV_PROFILE ?=',
    'ENV_PROFILE_OUTPUT ?=',
    'ENV_PROFILE_VALUES ?=',
    'ENV_PROFILE_EVIDENCE ?=',
    'environment-profile-plan:',
    'scripts/environment_profile_plan.py',
    '--evidence-output "$(ENV_PROFILE_EVIDENCE)"',
    'RELEASE_VERIFY_REPORT ?=',
    'IMAGE_PROMOTION_REGISTRY ?=',
    'image-promotion-plan:',
    'scripts/images/promotion_plan.py',
    'release-evidence:',
    'verify-release-evidence:',
    'scripts/release/verify_release_evidence.py',
    'DEPLOY_EDGE_OBSERVABILITY_PORTS',
    'DEPLOY_KIBANA_NODE_PORT',
    'DEPLOY_ELASTICSEARCH_NODE_PORT',
    'DEPLOY_GRAFANA_NODE_PORT',
    'DEPLOY_LOKI_NODE_PORT',
    'DEPLOY_CLICKHOUSE_HTTP_NODE_PORT',
    'DEPLOY_CLICKHOUSE_TCP_NODE_PORT',
    'INSTALL_MINIO="$(DEPLOY_ENABLE_MINIO)"',
    'INSTALL_RABBITMQ="$(DEPLOY_ENABLE_RABBITMQ)"',
    'INSTALL_KEYCLOAK="$(DEPLOY_ENABLE_KEYCLOAK)"',
    'INSTALL_EMQX="$(DEPLOY_ENABLE_EMQX)"',
    'INSTALL_NATS="$(DEPLOY_ENABLE_NATS)"',
    'INSTALL_VAULT="$(DEPLOY_ENABLE_VAULT)"',
    'INSTALL_KYVERNO="$(DEPLOY_ENABLE_KYVERNO)"',
    'INSTALL_TEMPORAL="$(DEPLOY_ENABLE_TEMPORAL)"',
    'INSTALL_ARGO_WORKFLOWS="$(DEPLOY_ENABLE_ARGO_WORKFLOWS)"',
    'INSTALL_LINKERD="$(DEPLOY_ENABLE_LINKERD)"',
    'INSTALL_ISTIO="$(DEPLOY_ENABLE_ISTIO)"',
    'deploy-auto: MIGRATION_AUTO_REPAIR_CLUSTER = true',
    'configure-edge-ports:',
    'Using recovered private inventory for edge ports',
    'MIGRATION_FALLBACK_INVENTORY',
    'ansible/playbooks/edge-ports.yml',
    'wait-operator-crds:',
    'bash $(HELMFILE_SYNC_SCRIPT)',
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

helmfile_text = (ROOT / 'deploy/helmfile.yaml.gotmpl').read_text(encoding='utf-8')
for helmfile_backup_token in [
    'https://vmware-tanzu.github.io/helm-charts',
    'name: velero',
    'chart: vmware-tanzu/velero',
    'INSTALL_VELERO',
    'VELERO_EXISTING_SECRET',
    'backupStorageLocation',
]:
    if helmfile_backup_token not in helmfile_text:
        errors.append(f'Helmfile missing optional backup operator token: {helmfile_backup_token}')

for helmfile_capability_token in [
    'https://repos.emqx.io/charts',
    'https://nats-io.github.io/k8s/helm/charts/',
    'https://helm.releases.hashicorp.com',
    'https://kyverno.github.io/kyverno/',
    'https://argoproj.github.io/argo-helm',
    'https://go.temporal.io/helm-charts',
    'https://helm.linkerd.io/stable',
    'https://istio-release.storage.googleapis.com/charts',
    'name: minio',
    'chart: bitnami/minio',
    'INSTALL_MINIO',
    'name: rabbitmq',
    'chart: bitnami/rabbitmq',
    'INSTALL_RABBITMQ',
    'name: keycloak',
    'chart: bitnami/keycloak',
    'INSTALL_KEYCLOAK',
    'name: emqx',
    'chart: emqx/emqx',
    'INSTALL_EMQX',
    'name: nats',
    'chart: nats/nats',
    'INSTALL_NATS',
    'name: vault',
    'chart: hashicorp/vault',
    'INSTALL_VAULT',
    'name: kyverno',
    'chart: kyverno/kyverno',
    'INSTALL_KYVERNO',
    'name: temporal',
    'chart: temporal/temporal',
    'INSTALL_TEMPORAL',
    'name: argo-workflows',
    'chart: argo/argo-workflows',
    'INSTALL_ARGO_WORKFLOWS',
    'name: linkerd-crds',
    'chart: linkerd/linkerd-crds',
    'name: linkerd-control-plane',
    'chart: linkerd/linkerd-control-plane',
    'INSTALL_LINKERD',
    'name: istio-base',
    'chart: istio/base',
    'name: istiod',
    'chart: istio/istiod',
    'INSTALL_ISTIO',
]:
    if helmfile_capability_token not in helmfile_text:
        errors.append(f'Helmfile missing optional platform capability token: {helmfile_capability_token}')

project_import_text = (ROOT / 'scripts/import_project.py').read_text(encoding='utf-8')
for project_import_token in [
    'find_compose_files',
    'docker-compose',
    '--project-path',
    '--quiet',
    'nginxinc/nginx-unprivileged:1.30.2',
    'CloudNativePG',
    'config/image-policy.yaml',
    'literal secret value',
    'ReportRedactor',
    '--redact-sensitive',
    'Migration Plan',
    'database_target_images',
    'OPTIONAL_DATABASE_KINDS',
    'microsoft-sql-server',
    'service_uses_sqlite_files',
    'Optional database services detected',
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
    'kubectl_apply_stdin_command',
    '--server-side',
    '--field-manager=urban-platform-import',
    '--force-conflicts',
    'postgres_client_container_command',
    'MIGRATION_POSTGRES_CLIENT_IMAGE',
    'docker.io/library/postgres:18.3',
    'MIGRATION_SKIP_UNAVAILABLE_DATABASES',
    '--strict-database-migration',
    'OPTIONAL_DATABASE_PORTS',
    'OPTIONAL_DATABASE_TOOLS',
    'optional_database_target',
    'Optional database target scaffolds',
    'sys.executable',
    'PYTHON="${PYTHON:-python3}"',
    'kubernetes_service_exists',
    'kubernetes_workload_manifests',
    'MIGRATION_PROFILE',
    'LAB_PROFILE_OVERLAY',
    'lab_profile_overlay',
    'lab-profile-values.yaml',
    'import-profile.md',
    'stage_preflight',
    'import-preflight.md',
    'import-capacity.md',
    'import-batches.md',
    'import-batches.yaml',
    'import-resume.md',
    'import-recovery-plan.md',
    'write_import_batch_plan',
    'filter_service_pairs_for_import_batch',
    'stage_scope_pairs',
    'databaseTargetsFingerprint',
    'write_migration_state_report',
    'migration_stage_completed',
    'mark_migration_stage_completed',
    'preflight_check_readyz',
    'preflight_check_nodes',
    'preflight_check_storage',
    'preflight_check_imported_capacity',
    'preflight_check_ingress_endpoint',
    'preflight_check_remote_nodes',
    'MIGRATION_PREFLIGHT_MIN_NODE_MEMORY',
    'MIGRATION_PREFLIGHT_MIN_NODE_DISK_FREE',
    'MIGRATION_PREFLIGHT_MAX_IMPORTED_WORKLOADS',
    'MIGRATION_PREFLIGHT_CAPACITY_UTILIZATION_LIMIT',
    'MIGRATION_PREFLIGHT_REQUIRE_INGRESS_ENDPOINT',
    'MIGRATION_BATCH_SIZE',
    'MIGRATION_IMPORT_BATCH',
    'MIGRATION_STATE_FILE',
    'MIGRATION_RESUME',
    'MIGRATION_FORCE_RERUN',
    'MIGRATION_RUNTIME_VALIDATION_TIMEOUT',
    'MIGRATION_RUNTIME_VALIDATION_INTERVAL',
    'make import-recovery-plan IMPORT_REDACT=true',
    'cleanup boundaries',
    'rollback boundaries',
    'imported_workload_resources',
    'imported_workload_pod_security_context',
    'imported_workload_container_security_context',
    'pod_waiting_summaries',
    'wait_for_post_migration_runtime',
    'runtime_blockers_for_wait',
    'cnpg_cluster_summaries',
    'cnpg_missing_pvc_summaries',
    'pending_pvc_summaries',
    'Imported pods with waiting containers',
    'CNPG clusters needing attention',
    'CNPG expected PVCs missing',
    'CloudNativePG Missing PVCs',
    'PVCs not bound',
    'allowPrivilegeEscalation',
    'runAsNonRoot',
    'seccompProfile',
    '"drop": ["ALL"]',
    'MIGRATION_IMPORT_SECURITY_CONTEXT',
    '--import-security-context',
    '--profile',
    '--lab-workload-cpu-request',
    '--preflight-min-node-memory',
    '--preflight-max-imported-workloads',
    '--preflight-capacity-utilization-limit',
    '--batch-size',
    '--import-batch',
    '--state-file',
    '--cluster-vip',
    '--resume',
    '--no-resume',
    '--force-rerun',
    '--preflight-require-ingress-endpoint',
    'args.image_mode = "preload" if lab_profile_enabled(args) else "registry"',
    'args.profile != "production"',
    'imported-workloads.yaml',
    'Skipping ingress candidate',
    'No ingress candidates were applied because their backend services are not present yet.',
    'canonical_host_http_redirect_manifests',
    'edge_service_pairs',
    'Evaluating edge ingress candidates across the full import set',
    'redirectRegex',
    '^https?://',
    'traefik-canonical-host-redirect',
    'traefik-canonical-host-redirect-https',
    'websecure',
    'clusterVip',
    'traefik_middleware_refs',
    'write_database_target_map',
    'preload_archives_to_nodes',
    'import_preloaded_archives_to_containerd',
    'cleanup_operator_container_tags',
    'cleanup_operator_archives',
    'prune_operator_container_cache',
    'legacy_image_archive_name',
    'image_variant_suffix',
    'local_import_tag',
    'nginx_platform_base_image',
    'nginx_requires_platform_import',
    'nginx_static_import_base_image',
    'nginx_rollout_base_image',
    'expected_nginx_version_from_image',
    'verify_nginx_import_image',
    'nginx_unprivileged_port_map',
    'nginx_internal_port',
    'nginx_service_target_ports',
    'rewrite_nginx_listen_ports_for_unprivileged',
    'nginx-rollout-fingerprint',
    'nginx_mismatches',
    'nginx version mismatches',
    'selected_tls_mode',
    'generate_lab_ca_signed_certificate',
    'extract_pfx_certificate',
    'ensure_letsencrypt_certificate',
    'write_lab_ca_trust_bundle',
    'install-windows-lab-ca.ps1',
    'install-linux-lab-ca.sh',
    'MIGRATION_TLS_PFX_PASSWORD_FILE',
    'MIGRATION_TLS_LE_CREATE_ISSUER',
    'import-tls.md',
    'urban-platform.io/nginx-base-image',
    'refresh_preload_image',
    'force_remove_script',
    'force=refresh_preload_image',
    'write_post_migration_runtime_report',
    'post-migration-runtime.md',
    'Source compatibility backlog written to',
    'expected_webserver_image',
    'Aligning nginx service',
    'generated_archives',
    'stale_archive_names',
    'run_remote_sudo_upload',
    'sudo -n true',
    'sudo -k -S',
    'removed staged tar files',
    'ensure_source_image',
    'explicit_container_pull_reference',
    'container_command(args, "tag", pull_image, image)',
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
    'MIGRATION_SECRET_PROVIDER',
    'MIGRATION_SECRET_REMOTE_PREFIX',
    'MIGRATION_SECRET_STORE_NAME',
    'external-secrets',
    'vault',
    'import-secret-provider.md',
    'run-migration.sh',
    'traefik-ingress-candidates.yaml',
    'ingress_source_allowlist_cidrs',
    'traefik_source_allowlist_middleware_ref',
    'Migration automation bundle written to',
]:
    if migration_automation_token not in migration_automation_text:
        errors.append(f'Project migration automation missing token: {migration_automation_token}')

import_recovery_plan_text = (ROOT / 'scripts/import_recovery_plan.py').read_text(encoding='utf-8')
for import_recovery_plan_token in [
    'Import Recovery Plan',
    'public-safe',
    'Safe Retry Controls',
    'Cleanup Boundaries',
    'Rollback Boundaries',
    'MIGRATION_FORCE_RERUN=true',
    'MIGRATION_STATE_FILE=/path/to/private/rehearsal-state.yaml',
    'RKE2 containerd import is disabled',
]:
    if import_recovery_plan_token not in import_recovery_plan_text:
        errors.append(f'Import recovery plan script missing token: {import_recovery_plan_token}')

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
    'make environment-profile-plan',
    'reports/environment-profile-plan.md',
    'reports/environment-profile-values.yaml',
    'make import-auto PROJECT_PATH=/path/to/compose-project',
    'make import-preflight PROJECT_PATH=/path/to/compose-project',
    'operator-kubeconfig repair target',
    'import-preflight.md',
    'import-capacity.md',
    'import-batches.md',
    'import-resume.md',
    'import-recovery-plan.md',
    'MIGRATION_IMPORT_BATCH=auto',
    'MIGRATION_IMPORT_BATCH=all',
    'MIGRATION_RESUME=true',
    'MIGRATION_FORCE_RERUN=true',
    'MIGRATION_STATE_FILE',
    'make import-recovery-plan IMPORT_REDACT=true',
    'Cleanup Boundaries',
    'MIGRATION_PREFLIGHT_MAX_IMPORTED_WORKLOADS',
    'MIGRATION_PREFLIGHT_REQUIRE_INGRESS_ENDPOINT=true',
    'MIGRATION_PROFILE=lab',
    'lab-profile-values.yaml',
    'MIGRATION_PROFILE=production',
    'make image-cache-plan',
    'reports/image-cache-plan.md',
    'make database-migration-plan',
    'reports/database-migration-plan.md',
    'make edge-migration-plan',
    'reports/edge-migration-plan.md',
    'prepares the private operator workspace',
    'MIGRATION_STAGE=databases',
    'MIGRATION_IMAGE_MODE=preload',
    'MIGRATION_RKE2_NODES',
    'MIGRATION_SECRET_PROVIDER=external-secrets',
    'MIGRATION_SECRET_PROVIDER=vault',
    'MIGRATION_SECRET_REMOTE_PREFIX',
    'MIGRATION_CLEANUP_OPERATOR_IMAGES=false',
    'MIGRATION_EXECUTE=true',
    'MIGRATION_REGISTRY_USERNAME',
    'MIGRATION_TLS_MODE=lab-ca',
    'MIGRATION_TLS_MODE=pfx',
    'MIGRATION_TLS_MODE=letsencrypt',
    'MIGRATION_TLS_EXTRA_HOSTS',
    'tls-trust/',
    'NET::ERR_CERT_AUTHORITY_INVALID',
    'MIGRATION_IMPORT_SECURITY_CONTEXT=compat',
    'MIGRATION_RELAX_RESOURCE_QUOTA=true',
    'namespace.resourceQuota.enabled=false',
    'disabled privilege escalation',
    'Imported nginx edge/static services are rebuilt or retagged from the selected',
    'stable nginx-base suffix',
    'force-refresh the node-side RKE2/containerd image ref',
    'MIGRATION_DEPLOY_PLATFORM=false',
    'secretRef',
    'generated Ingress candidates are applied only if',
    'post-migration-runtime.md',
]:
    if project_import_docs_token not in project_import_docs_text:
        errors.append(f'Project import docs missing token: {project_import_docs_token}')

import_recovery_docs_text = (ROOT / 'docs/import-recovery.md').read_text(encoding='utf-8')
for import_recovery_docs_token in [
    'Import Resume, Recovery, And Cleanup',
    'make import-recovery-plan IMPORT_REDACT=true',
    'reports/import-migration/import-recovery-plan.md',
    'MIGRATION_RESUME=true',
    'MIGRATION_FORCE_RERUN=true',
    'MIGRATION_STATE_FILE=/path/to/private/rehearsal-state.yaml',
    'Cleanup Boundaries',
    'Rollback Boundaries',
    'public-safe',
]:
    if import_recovery_docs_token not in import_recovery_docs_text:
        errors.append(f'Import recovery docs missing token: {import_recovery_docs_token}')

design_docs = {
    'docs/hld.md': [
        'High-Level Design',
        'public-safe high-level design',
        'Logical Architecture',
        'Deployment Profiles',
        'Import and Migration Design',
        'Database Strategy',
        'Image Strategy',
        'Secret Strategy',
        'Backup Strategy',
        'Resource Strategy',
        'Public-Safe Boundaries',
    ],
    'docs/lld.md': [
        'Low-Level Design',
        'public-safe low-level design',
        'Repository Components',
        'Deployment Execution Flow',
        'Import Execution Flow',
        'Kubernetes Access Repair',
        'Helmfile Design',
        'Helm Chart Design',
        'Backup Implementation',
        'Image Migration Design',
        'Database Migration Design',
        'Public-Safe Review Checklist',
    ],
}
for design_doc, required_tokens in design_docs.items():
    design_doc_text = (ROOT / design_doc).read_text(encoding='utf-8')
    for required_token in required_tokens:
        if required_token not in design_doc_text:
            errors.append(f'{design_doc} missing public-safe design token: {required_token}')
    if re.search(r'\b(?:10|192\.168)\.[0-9]{1,3}\.[0-9]{1,3}\b', design_doc_text):
        errors.append(f'{design_doc} must not contain private IPv4 addresses')
    if re.search(r'\b172\.(?:1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3}\b', design_doc_text):
        errors.append(f'{design_doc} must not contain private IPv4 addresses')
    for private_design_token in ['/srv/', '/opt/', 'auyp']:
        if private_design_token in design_doc_text:
            errors.append(f'{design_doc} must not contain private token: {private_design_token}')

secret_provider_config_text = (ROOT / 'config/secret-provider-adapters.yaml').read_text(encoding='utf-8')
for secret_provider_config_token in [
    'defaultProfile: disabled',
    'kubernetes-direct:',
    'external-secrets:',
    'vault:',
    'sops:',
    'sealed-secrets:',
    'automaticProviders:',
    'planOnlyProviders:',
    'directSecretGate: MIGRATION_ALLOW_SECRET_MATERIAL=true',
    'recommendedProductionProvider: external-secrets',
]:
    if secret_provider_config_token not in secret_provider_config_text:
        errors.append(f'Secret provider adapter config missing token: {secret_provider_config_token}')

secret_provider_docs_text = (ROOT / 'docs/secret-provider-adapters.md').read_text(encoding='utf-8')
for secret_provider_docs_token in [
    'Secret Provider Adapters',
    'disabled by default',
    'MIGRATION_SECRET_PROVIDER=external-secrets',
    'MIGRATION_SECRET_PROVIDER=vault',
    'MIGRATION_SECRET_REMOTE_PREFIX',
    'SOPS',
    'Sealed Secrets',
    'ExternalSecret',
]:
    if secret_provider_docs_token not in secret_provider_docs_text:
        errors.append(f'Secret provider adapter docs missing token: {secret_provider_docs_token}')

secrets_docs_text = (ROOT / 'docs/secrets-management.md').read_text(encoding='utf-8')
for secrets_docs_token in [
    'Provider Adapters',
    'config/secret-provider-adapters.yaml',
    'MIGRATION_SECRET_PROVIDER=external-secrets',
    'MIGRATION_SECRET_PROVIDER=vault',
]:
    if secrets_docs_token not in secrets_docs_text:
        errors.append(f'Secrets management docs missing provider adapter token: {secrets_docs_token}')

storage_tiers_config_text = (ROOT / 'config/storage-tiers.yaml').read_text(encoding='utf-8')
for storage_tiers_config_token in [
    'defaultProfile: lab',
    'hot:',
    'warm:',
    'cold:',
    'objectStore:',
    's3-compatible',
    'workloadMapping:',
    'databaseBackups: cold',
    'importDumps: cold',
]:
    if storage_tiers_config_token not in storage_tiers_config_text:
        errors.append(f'Storage tier contract missing token: {storage_tiers_config_token}')

storage_tiers_docs_text = (ROOT / 'docs/storage-tiers.md').read_text(encoding='utf-8')
for storage_tiers_docs_token in [
    'optional hot/warm/cold storage architecture',
    'storageTiers:',
    'Current Chart Behavior',
    'CloudNativePG database clusters',
    'generic StatefulSet workloads',
    'Cold object-store settings are a public-safe contract',
]:
    if storage_tiers_docs_token not in storage_tiers_docs_text:
        errors.append(f'Storage tier docs missing token: {storage_tiers_docs_token}')

storage_tiers_values_text = (ROOT / 'helm/urban-platform-infra/values.yaml').read_text(encoding='utf-8')
for storage_tiers_values_token in [
    'storageTiers:',
    'description: Active low-latency PVCs',
    'description: Lower-cost PVCs',
    'description: Archive tier',
    'provider: s3-compatible',
]:
    if storage_tiers_values_token not in storage_tiers_values_text:
        errors.append(f'Helm values missing storage tier token: {storage_tiers_values_token}')

storage_tiers_template_text = '\n'.join(
    (ROOT / storage_tiers_template_file).read_text(encoding='utf-8')
    for storage_tiers_template_file in [
        'helm/urban-platform-infra/templates/_helpers.tpl',
        'helm/urban-platform-infra/templates/databases-cnpg.yaml',
        'helm/urban-platform-infra/templates/messaging-kafka.yaml',
        'helm/urban-platform-infra/templates/redis.yaml',
        'helm/urban-platform-infra/templates/workloads.yaml',
    ]
)
for storage_tiers_template_token in [
    'define "cip.storageClassName"',
    'storageTiers',
    '$zookeeperStorageClass',
    '$kafkaStorageClass',
    '$redisStorageClass',
    '$statefulStorageClass',
]:
    if storage_tiers_template_token not in storage_tiers_template_text:
        errors.append(f'Helm templates missing storage tier token: {storage_tiers_template_token}')

backup_policy_text = (ROOT / 'config/backup-policy.yaml').read_text(encoding='utf-8')
for backup_policy_token in [
    'defaultProfile: disabled',
    'enabledByDefault: false',
    'rke2Etcd:',
    'cloudnativePg:',
    'velero:',
    'imageArchives:',
    'urbackup:',
    'restic:',
    'kopia:',
    'borg:',
    'installInCluster: false',
    'backupPlaintext: false',
    'restore-drill-runbook-reviewed',
]:
    if backup_policy_token not in backup_policy_text:
        errors.append(f'Backup policy missing disabled-by-default token: {backup_policy_token}')

backup_docs_text = (ROOT / 'docs/backup-restore.md').read_text(encoding='utf-8')
for backup_docs_token in [
    'Backups are disabled by default',
    'make backup-plan',
    'CloudNativePG Barman',
    'Velero is optional and disabled',
    'UrBackup',
    'restic',
    'Kopia',
    'Borg',
    'RKE2 etcd snapshots',
    'Restore Drills',
]:
    if backup_docs_token not in backup_docs_text:
        errors.append(f'Backup/restore docs missing token: {backup_docs_token}')

backup_plan_text = (ROOT / 'scripts/backup_plan.py').read_text(encoding='utf-8')
for backup_plan_token in [
    'public_safe_backup_plan',
    'Global backup switch',
    'CloudNativePG backup rendering',
    'Velero operator install',
    'External Backup Providers',
    'urbackup',
    'restic',
    'kopia',
    'borg',
    'Backups are disabled by default',
]:
    if backup_plan_token not in backup_plan_text:
        errors.append(f'Backup plan script missing public-safe token: {backup_plan_token}')

observability_plan_text = (ROOT / 'scripts/observability_plan.py').read_text(encoding='utf-8')
for observability_plan_token in [
    'Observability And SLO Readiness Plan',
    'Lab-safe default',
    'Prometheus Operator CRD gate',
    'SLO Objective Coverage',
    'ServiceMonitor template',
    'Production Enablement Sequence',
]:
    if observability_plan_token not in observability_plan_text:
        errors.append(f'Observability plan script missing public-safe token: {observability_plan_token}')

cluster_doctor_text = (ROOT / 'scripts/cluster_doctor.py').read_text(encoding='utf-8')
for cluster_doctor_token in [
    'Cluster Doctor Report',
    'public-safe',
    'redact',
    'local binary `kubectl`',
    'operator Kubernetes `/readyz`',
    'passwordless sudo',
    'haproxy-config',
    'keepalived-config',
    'make cluster-repair',
    'MIGRATION_AUTO_REPAIR_CLUSTER',
]:
    if cluster_doctor_token not in cluster_doctor_text:
        errors.append(f'Cluster doctor script missing diagnostic token: {cluster_doctor_token}')

lab_deploy_plan_text = (ROOT / 'scripts/lab_deploy_plan.py').read_text(encoding='utf-8')
for lab_deploy_plan_token in [
    'Lab Capacity And Progressive Deploy Plan',
    'public-safe',
    'progressive_waves',
    'lab-deploy-values.yaml',
    'global.replicaOverride',
    'global.skipPlaceholderWorkloads',
    'MIGRATION_IMPORT_BATCH=1',
]:
    if lab_deploy_plan_token not in lab_deploy_plan_text:
        errors.append(f'Lab deploy plan script missing capacity token: {lab_deploy_plan_token}')

capacity_preflight_text = (ROOT / 'scripts/capacity_preflight.py').read_text(encoding='utf-8')
for capacity_preflight_token in [
    'Cluster Capacity Preflight',
    'public-safe',
    'capacity-evidence',
    'MIGRATION_IMPORT_BATCH=all',
    'global.replicaOverride=1',
    'global.skipPlaceholderWorkloads=true',
    'Use the generated lab values overlay',
]:
    if capacity_preflight_token not in capacity_preflight_text:
        errors.append(f'Capacity preflight script missing guardrail token: {capacity_preflight_token}')

lab_capacity_text = (ROOT / 'config/lab-capacity.yaml').read_text(encoding='utf-8')
for lab_capacity_token in [
    'defaultProfile: three-node-4g',
    'memoryPerNode: 4Gi',
    'capacityUtilizationLimit: 0.70',
    'maxDatabases: 3',
    'importedBatchSize: 40',
    'progressiveWaves:',
]:
    if lab_capacity_token not in lab_capacity_text:
        errors.append(f'Lab capacity config missing guardrail token: {lab_capacity_token}')

image_cache_plan_text = (ROOT / 'scripts/image_cache_plan.py').read_text(encoding='utf-8')
for image_cache_plan_token in [
    'Image Cache, Preload, And Cleanup Plan',
    'public-safe',
    'MIGRATION_CLEANUP_OPERATOR_IMAGES',
    'MIGRATION_PRUNE_OPERATOR_CACHE',
    'MIGRATION_RKE2_IMPORT_IMAGES',
    'RKE2 containerd import',
    'operator cache cleanup',
    'make image-cache-plan',
]:
    if image_cache_plan_token not in image_cache_plan_text:
        errors.append(f'Image cache plan script missing preload/cleanup token: {image_cache_plan_token}')

image_cache_config_text = (ROOT / 'config/image-cache.yaml').read_text(encoding='utf-8')
for image_cache_config_token in [
    'defaultProfile: lab-preload',
    'production-registry:',
    'disconnected-preload:',
    'cleanupOperatorImages: true',
    'pruneOperatorCache: true',
    'rke2ImportImages: true',
    'staleArchiveAction:',
    'nodeArchiveRetention:',
]:
    if image_cache_config_token not in image_cache_config_text:
        errors.append(f'Image cache config missing preload/cleanup token: {image_cache_config_token}')

image_cache_docs_text = (ROOT / 'docs/image-cache-preload.md').read_text(encoding='utf-8')
for image_cache_docs_token in [
    'Image Cache, Preload, And Cleanup',
    'make image-cache-plan',
    'MIGRATION_IMAGE_MODE=preload',
    'MIGRATION_RKE2_NODES',
    'MIGRATION_CLEANUP_OPERATOR_IMAGES=true',
    'MIGRATION_PRUNE_OPERATOR_CACHE=true',
    'MIGRATION_RKE2_IMPORT_IMAGES=true',
    'containerd',
]:
    if image_cache_docs_token not in image_cache_docs_text:
        errors.append(f'Image cache docs missing preload/cleanup token: {image_cache_docs_token}')

registry_promotion_script_text = (ROOT / 'scripts/images/registry_promotion_controller.py').read_text(encoding='utf-8')
for registry_promotion_script_token in [
    'Image Registry Promotion Controller',
    'public-safe',
    'global.imageRegistry',
    'imagePullSecrets',
    'requireSignatureOrAttestation',
    'Registry promotion override template',
]:
    if registry_promotion_script_token not in registry_promotion_script_text:
        errors.append(f'Registry promotion controller script missing token: {registry_promotion_script_token}')

registry_promotion_config_text = (ROOT / 'config/registry-promotion.yaml').read_text(encoding='utf-8')
for registry_promotion_config_token in [
    'defaultProfile: disabled',
    'production-registry:',
    'enterprise-signed:',
    'credentialSources:',
    'controller:',
    'oneCommandTargets:',
]:
    if registry_promotion_config_token not in registry_promotion_config_text:
        errors.append(f'Registry promotion config missing token: {registry_promotion_config_token}')

registry_promotion_docs_text = (ROOT / 'docs/registry-promotion-controller.md').read_text(encoding='utf-8')
for registry_promotion_docs_token in [
    'Article 16 Baseline',
    'make registry-promotion-plan',
    'REGISTRY_PROMOTION_PROFILE=production-registry',
    'reports/registry-promotion-controller.md',
    'reports/registry-promotion-values.yaml',
    'MIGRATION_IMAGE_MODE=registry',
]:
    if registry_promotion_docs_token not in registry_promotion_docs_text:
        errors.append(f'Registry promotion docs missing token: {registry_promotion_docs_token}')

runtime_hardening_plan_text = (ROOT / 'scripts/runtime_hardening_plan.py').read_text(encoding='utf-8')
for runtime_hardening_plan_token in [
    'Runtime Hardening And Admission Policy Plan',
    'public-safe',
    'requireReadOnlyRootFilesystem',
    'requireSignedImages',
    'runtime-hardening-values.yaml',
    'make runtime-hardening-plan',
]:
    if runtime_hardening_plan_token not in runtime_hardening_plan_text:
        errors.append(f'Runtime hardening plan script missing token: {runtime_hardening_plan_token}')

runtime_hardening_config_text = (ROOT / 'config/runtime-hardening.yaml').read_text(encoding='utf-8')
for runtime_hardening_config_token in [
    'defaultProfile: disabled',
    'lab-audit:',
    'production-restricted:',
    'enterprise-signed:',
    'policyEngine: kyverno',
    'requireSignedImages: true',
    'admissionChecks:',
]:
    if runtime_hardening_config_token not in runtime_hardening_config_text:
        errors.append(f'Runtime hardening config missing token: {runtime_hardening_config_token}')

runtime_hardening_docs_text = (ROOT / 'docs/runtime-hardening-admission.md').read_text(encoding='utf-8')
for runtime_hardening_docs_token in [
    'Article 17 Baseline',
    'make runtime-hardening-plan',
    'RUNTIME_HARDENING_PROFILE=production-restricted',
    'reports/runtime-hardening-plan.md',
    'reports/runtime-hardening-values.yaml',
    'signed-image admission',
]:
    if runtime_hardening_docs_token not in runtime_hardening_docs_text:
        errors.append(f'Runtime hardening docs missing token: {runtime_hardening_docs_token}')

gitops_delivery_plan_text = (ROOT / 'scripts/gitops_delivery_plan.py').read_text(encoding='utf-8')
for gitops_delivery_plan_token in [
    'GitOps Delivery And Drift Control Plan',
    'public-safe',
    'driftDetection',
    'gitops-delivery-values.yaml',
    'make gitops-delivery-plan',
    'Helmfile break-glass',
]:
    if gitops_delivery_plan_token not in gitops_delivery_plan_text:
        errors.append(f'GitOps delivery plan script missing token: {gitops_delivery_plan_token}')

gitops_delivery_config_text = (ROOT / 'config/gitops-delivery.yaml').read_text(encoding='utf-8')
for gitops_delivery_config_token in [
    'defaultProfile: operator-managed',
    'lab-argocd:',
    'production-argocd:',
    'production-flux:',
    'supportedControllers:',
    'requiredChecks:',
]:
    if gitops_delivery_config_token not in gitops_delivery_config_text:
        errors.append(f'GitOps delivery config missing token: {gitops_delivery_config_token}')

gitops_delivery_docs_text = (ROOT / 'docs/gitops-delivery.md').read_text(encoding='utf-8')
for gitops_delivery_docs_token in [
    'Article 18 Baseline',
    'make gitops-delivery-plan',
    'GITOPS_DELIVERY_PROFILE=production-argocd',
    'reports/gitops-delivery-plan.md',
    'reports/gitops-delivery-values.yaml',
    'Argo CD',
    'Flux',
]:
    if gitops_delivery_docs_token not in gitops_delivery_docs_text:
        errors.append(f'GitOps delivery docs missing token: {gitops_delivery_docs_token}')

progressive_delivery_plan_text = (ROOT / 'scripts/progressive_delivery_plan.py').read_text(encoding='utf-8')
for progressive_delivery_plan_token in [
    'Progressive Delivery And Rollback Plan',
    'public-safe',
    'canarySteps',
    'rollback-drill',
    'progressive-delivery-values.yaml',
    'make progressive-delivery-plan',
    'helm rollback',
]:
    if progressive_delivery_plan_token not in progressive_delivery_plan_text:
        errors.append(f'Progressive delivery plan script missing token: {progressive_delivery_plan_token}')

progressive_delivery_config_text = (ROOT / 'config/progressive-delivery.yaml').read_text(encoding='utf-8')
for progressive_delivery_config_token in [
    'defaultProfile: disabled',
    'lab-canary:',
    'production-canary:',
    'production-blue-green:',
    'supportedControllers:',
    'supportedTrafficProviders:',
    'requiredChecks:',
]:
    if progressive_delivery_config_token not in progressive_delivery_config_text:
        errors.append(f'Progressive delivery config missing token: {progressive_delivery_config_token}')

progressive_delivery_docs_text = (ROOT / 'docs/progressive-delivery.md').read_text(encoding='utf-8')
for progressive_delivery_docs_token in [
    'Article 19 Baseline',
    'make progressive-delivery-plan',
    'PROGRESSIVE_DELIVERY_PROFILE=production-canary',
    'reports/progressive-delivery-plan.md',
    'reports/progressive-delivery-values.yaml',
    'Argo Rollouts',
    'blue-green',
]:
    if progressive_delivery_docs_token not in progressive_delivery_docs_text:
        errors.append(f'Progressive delivery docs missing token: {progressive_delivery_docs_token}')

scaling_policy_plan_text = (ROOT / 'scripts/scaling_policy_plan.py').read_text(encoding='utf-8')
for scaling_policy_plan_token in [
    'Scaling Policy And Capacity Automation Plan',
    'public-safe',
    'load-test-evidence',
    'scaling-policy-values.yaml',
    'make scaling-policy-plan',
    'KEDA triggers',
]:
    if scaling_policy_plan_token not in scaling_policy_plan_text:
        errors.append(f'Scaling policy plan script missing token: {scaling_policy_plan_token}')

scaling_policy_config_text = (ROOT / 'config/scaling-policy.yaml').read_text(encoding='utf-8')
for scaling_policy_config_token in [
    'defaultProfile: disabled',
    'lab-rightsize:',
    'production-hpa:',
    'event-driven-keda:',
    'enterprise-autoscaling:',
    'supportedAutoscalers:',
    'requiredChecks:',
]:
    if scaling_policy_config_token not in scaling_policy_config_text:
        errors.append(f'Scaling policy config missing token: {scaling_policy_config_token}')

scaling_policy_docs_text = (ROOT / 'docs/scaling-policy.md').read_text(encoding='utf-8')
for scaling_policy_docs_token in [
    'Article 20 Baseline',
    'make scaling-policy-plan',
    'SCALING_POLICY_PROFILE=production-hpa',
    'reports/scaling-policy-plan.md',
    'reports/scaling-policy-values.yaml',
    'HPA',
    'KEDA',
]:
    if scaling_policy_docs_token not in scaling_policy_docs_text:
        errors.append(f'Scaling policy docs missing token: {scaling_policy_docs_token}')

network_connectivity_plan_text = (ROOT / 'scripts/network_connectivity_plan.py').read_text(encoding='utf-8')
for network_connectivity_plan_token in [
    'Network Connectivity And Service Mesh Plan',
    'public-safe',
    'dns-tls-evidence',
    'network-connectivity-values.yaml',
    'make network-connectivity-plan',
    'Service mesh',
]:
    if network_connectivity_plan_token not in network_connectivity_plan_text:
        errors.append(f'Network connectivity plan script missing token: {network_connectivity_plan_token}')

network_connectivity_config_text = (ROOT / 'config/network-connectivity.yaml').read_text(encoding='utf-8')
for network_connectivity_config_token in [
    'defaultProfile: disabled',
    'lab-baseline:',
    'production-restricted:',
    'mesh-linkerd:',
    'mesh-istio:',
    'supportedServiceMeshes:',
    'requiredChecks:',
]:
    if network_connectivity_config_token not in network_connectivity_config_text:
        errors.append(f'Network connectivity config missing token: {network_connectivity_config_token}')

network_connectivity_docs_text = (ROOT / 'docs/network-connectivity.md').read_text(encoding='utf-8')
for network_connectivity_docs_token in [
    'Article 21 Baseline',
    'make network-connectivity-plan',
    'NETWORK_CONNECTIVITY_PROFILE=production-restricted',
    'reports/network-connectivity-plan.md',
    'reports/network-connectivity-values.yaml',
    'Linkerd',
    'Istio',
]:
    if network_connectivity_docs_token not in network_connectivity_docs_text:
        errors.append(f'Network connectivity docs missing token: {network_connectivity_docs_token}')

access_governance_plan_text = (ROOT / 'scripts/access_governance_plan.py').read_text(encoding='utf-8')
for access_governance_plan_token in [
    'Access Governance And Tenant Isolation Plan',
    'public-safe',
    'break-glass-review',
    'access-governance-values.yaml',
    'make access-governance-plan',
    'tenant isolation',
]:
    if access_governance_plan_token not in access_governance_plan_text:
        errors.append(f'Access governance plan script missing token: {access_governance_plan_token}')

access_governance_config_text = (ROOT / 'config/access-governance.yaml').read_text(encoding='utf-8')
for access_governance_config_token in [
    'defaultProfile: disabled',
    'lab-audit:',
    'production-rbac:',
    'oidc-sso:',
    'multi-tenant:',
    'supportedIdentityProviders:',
    'requiredChecks:',
]:
    if access_governance_config_token not in access_governance_config_text:
        errors.append(f'Access governance config missing token: {access_governance_config_token}')

access_governance_docs_text = (ROOT / 'docs/access-governance.md').read_text(encoding='utf-8')
for access_governance_docs_token in [
    'Article 22 Baseline',
    'make access-governance-plan',
    'ACCESS_GOVERNANCE_PROFILE=production-rbac',
    'reports/access-governance-plan.md',
    'reports/access-governance-values.yaml',
    'OIDC',
    'tenant isolation',
]:
    if access_governance_docs_token not in access_governance_docs_text:
        errors.append(f'Access governance docs missing token: {access_governance_docs_token}')

compliance_evidence_plan_text = (ROOT / 'scripts/compliance_evidence_plan.py').read_text(encoding='utf-8')
for compliance_evidence_plan_token in [
    'Compliance Evidence And Audit Pack Plan',
    'public-safe',
    'restore-drill-evidence',
    'access-review-evidence',
    'incident-drill-evidence',
    'compliance-evidence-values.yaml',
    'make compliance-evidence-plan',
    'certification',
]:
    if compliance_evidence_plan_token not in compliance_evidence_plan_text:
        errors.append(f'Compliance evidence plan script missing token: {compliance_evidence_plan_token}')

compliance_evidence_config_text = (ROOT / 'config/compliance-evidence.yaml').read_text(encoding='utf-8')
for compliance_evidence_config_token in [
    'defaultProfile: disabled',
    'lab-evidence:',
    'staging-control-review:',
    'production-audit-pack:',
    'regulated-retention:',
    'evidenceSources:',
    'requiredChecks:',
]:
    if compliance_evidence_config_token not in compliance_evidence_config_text:
        errors.append(f'Compliance evidence config missing token: {compliance_evidence_config_token}')

compliance_evidence_docs_text = (ROOT / 'docs/compliance-evidence.md').read_text(encoding='utf-8')
for compliance_evidence_docs_token in [
    'Article 23 Baseline',
    'make compliance-evidence-plan',
    'COMPLIANCE_EVIDENCE_PROFILE=production-audit-pack',
    'reports/compliance-evidence-plan.md',
    'reports/compliance-evidence-values.yaml',
    'audit pack',
    'certification',
]:
    if compliance_evidence_docs_token not in compliance_evidence_docs_text:
        errors.append(f'Compliance evidence docs missing token: {compliance_evidence_docs_token}')

incident_response_plan_text = (ROOT / 'scripts/incident_response_plan.py').read_text(encoding='utf-8')
for incident_response_plan_token in [
    'Incident Response And Operational Readiness Plan',
    'public-safe',
    'incident-drill',
    'post-incident-review',
    'incident-response-values.yaml',
    'make incident-response-plan',
    'pager',
]:
    if incident_response_plan_token not in incident_response_plan_text:
        errors.append(f'Incident response plan script missing token: {incident_response_plan_token}')

incident_response_config_text = (ROOT / 'config/incident-response.yaml').read_text(encoding='utf-8')
for incident_response_config_token in [
    'defaultProfile: disabled',
    'lab-readiness:',
    'staging-drill:',
    'production-oncall:',
    'regulated-incident:',
    'supportedIntegrations:',
    'requiredChecks:',
]:
    if incident_response_config_token not in incident_response_config_text:
        errors.append(f'Incident response config missing token: {incident_response_config_token}')

incident_response_docs_text = (ROOT / 'docs/incident-response.md').read_text(encoding='utf-8')
for incident_response_docs_token in [
    'Article 24 Baseline',
    'make incident-response-plan',
    'INCIDENT_RESPONSE_PROFILE=production-oncall',
    'reports/incident-response-plan.md',
    'reports/incident-response-values.yaml',
    'post-incident review',
    'pager',
]:
    if incident_response_docs_token not in incident_response_docs_text:
        errors.append(f'Incident response docs missing token: {incident_response_docs_token}')

change_management_plan_text = (ROOT / 'scripts/change_management_plan.py').read_text(encoding='utf-8')
for change_management_plan_token in [
    'Change Management And Maintenance Window Plan',
    'public-safe',
    'freeze-check',
    'stakeholder-notice',
    'post-change-review',
    'change-management-values.yaml',
    'make change-management-plan',
    'maintenance window',
]:
    if change_management_plan_token not in change_management_plan_text:
        errors.append(f'Change management plan script missing token: {change_management_plan_token}')

change_management_config_text = (ROOT / 'config/change-management.yaml').read_text(encoding='utf-8')
for change_management_config_token in [
    'defaultProfile: disabled',
    'lab-change:',
    'staging-approval:',
    'production-cab:',
    'regulated-change:',
    'supportedSystems:',
    'requiredChecks:',
]:
    if change_management_config_token not in change_management_config_text:
        errors.append(f'Change management config missing token: {change_management_config_token}')

change_management_docs_text = (ROOT / 'docs/change-management.md').read_text(encoding='utf-8')
for change_management_docs_token in [
    'Article 25 Baseline',
    'make change-management-plan',
    'CHANGE_MANAGEMENT_PROFILE=production-cab',
    'reports/change-management-plan.md',
    'reports/change-management-values.yaml',
    'post-change review',
    'maintenance windows',
]:
    if change_management_docs_token not in change_management_docs_text:
        errors.append(f'Change management docs missing token: {change_management_docs_token}')

cutover_gate_plan_text = (ROOT / 'scripts/cutover_gate_plan.py').read_text(encoding='utf-8')
for cutover_gate_plan_token in [
    'Production Cutover And Smoke-Test Gate Plan',
    'public-safe',
    'cutover-gate-values.yaml',
    'make cutover-gate-plan',
    'dns-tls-evidence',
    'owner-handoff',
    'traffic switch',
]:
    if cutover_gate_plan_token not in cutover_gate_plan_text:
        errors.append(f'Cutover gate plan script missing token: {cutover_gate_plan_token}')

cutover_gates_config_text = (ROOT / 'config/cutover-gates.yaml').read_text(encoding='utf-8')
for cutover_gates_config_token in [
    'defaultProfile: disabled',
    'lab-smoke:',
    'staging-cutover:',
    'production-cutover:',
    'publicArtifacts:',
    'requiredChecks:',
    'guardrails:',
]:
    if cutover_gates_config_token not in cutover_gates_config_text:
        errors.append(f'Cutover gates config missing token: {cutover_gates_config_token}')

cutover_gates_docs_text = (ROOT / 'docs/cutover-gates.md').read_text(encoding='utf-8')
for cutover_gates_docs_token in [
    'Production Cutover And Smoke-Test Gates',
    'make cutover-gate-plan',
    'CUTOVER_GATES_PROFILE=production-cutover',
    'reports/cutover-gate-plan.md',
    'reports/cutover-gate-values.yaml',
    'DNS/TLS',
    'smoke-test',
    'rollback',
]:
    if cutover_gates_docs_token not in cutover_gates_docs_text:
        errors.append(f'Cutover gates docs missing token: {cutover_gates_docs_token}')

smoke_test_plan_text = (ROOT / 'scripts/smoke_test_plan.py').read_text(encoding='utf-8')
for smoke_test_plan_token in [
    'Post-Migration Smoke-Test And Health-Probe Plan',
    'public-safe',
    'smoke-test-values.yaml',
    'make smoke-test-plan',
    'kubernetes rollout',
    'database connection',
    'messaging connection',
    'private runner',
]:
    if smoke_test_plan_token not in smoke_test_plan_text:
        errors.append(f'Smoke-test plan script missing token: {smoke_test_plan_token}')

smoke_tests_config_text = (ROOT / 'config/smoke-tests.yaml').read_text(encoding='utf-8')
for smoke_tests_config_token in [
    'defaultProfile: disabled',
    'lab-smoke:',
    'staging-smoke:',
    'production-smoke:',
    'checkCatalog:',
    'guardrails:',
]:
    if smoke_tests_config_token not in smoke_tests_config_text:
        errors.append(f'Smoke-test config missing token: {smoke_tests_config_token}')

smoke_tests_docs_text = (ROOT / 'docs/smoke-tests.md').read_text(encoding='utf-8')
for smoke_tests_docs_token in [
    'Post-Migration Smoke Tests And Health Probes',
    'make smoke-test-plan',
    'SMOKE_TEST_PROFILE=production-smoke',
    'reports/smoke-test-plan.md',
    'reports/smoke-test-values.yaml',
    'Kubernetes rollout',
    'database',
    'messaging',
]:
    if smoke_tests_docs_token not in smoke_tests_docs_text:
        errors.append(f'Smoke-test docs missing token: {smoke_tests_docs_token}')

release_runbook_plan_text = (ROOT / 'scripts/release_runbook_plan.py').read_text(encoding='utf-8')
for release_runbook_plan_token in [
    'Release Runbook And Evidence Gate Plan',
    'public-safe',
    'release-runbook-values.yaml',
    'make release-runbook-plan',
    'release artifact evidence',
    'change approval',
    'rollback',
    'private approval index',
]:
    if release_runbook_plan_token not in release_runbook_plan_text:
        errors.append(f'Release runbook plan script missing token: {release_runbook_plan_token}')

release_runbook_config_text = (ROOT / 'config/release-runbook.yaml').read_text(encoding='utf-8')
for release_runbook_config_token in [
    'defaultProfile: disabled',
    'lab-release:',
    'staging-release:',
    'production-release:',
    'runbookSections:',
    'guardrails:',
]:
    if release_runbook_config_token not in release_runbook_config_text:
        errors.append(f'Release runbook config missing token: {release_runbook_config_token}')

release_runbook_docs_text = (ROOT / 'docs/release-runbook.md').read_text(encoding='utf-8')
for release_runbook_docs_token in [
    'Release Runbook And Evidence Gates',
    'make release-runbook-plan',
    'RELEASE_RUNBOOK_PROFILE=production-release',
    'reports/release-runbook-plan.md',
    'reports/release-runbook-values.yaml',
    'change approval',
    'rollback',
]:
    if release_runbook_docs_token not in release_runbook_docs_text:
        errors.append(f'Release runbook docs missing token: {release_runbook_docs_token}')

cluster_upgrade_plan_text = (ROOT / 'scripts/cluster_upgrade_plan.py').read_text(encoding='utf-8')
for cluster_upgrade_plan_token in [
    'Cluster Upgrade And Version-Skew Guardrail Plan',
    'public-safe',
    'cluster-upgrade-values.yaml',
    'make cluster-upgrade-plan',
    'version skew',
    'RKE2 version',
    'etcd snapshot',
    'maintenance window',
    'rollback plan',
]:
    if cluster_upgrade_plan_token not in cluster_upgrade_plan_text:
        errors.append(f'Cluster upgrade plan script missing token: {cluster_upgrade_plan_token}')

cluster_upgrade_config_text = (ROOT / 'config/cluster-upgrade.yaml').read_text(encoding='utf-8')
for cluster_upgrade_config_token in [
    'defaultProfile: disabled',
    'lab-upgrade:',
    'staging-upgrade:',
    'production-upgrade:',
    'versionSkewPolicy:',
    'rke2VersionFormat: vMAJOR.MINOR.PATCH+rke2rN',
    'guardrails:',
]:
    if cluster_upgrade_config_token not in cluster_upgrade_config_text:
        errors.append(f'Cluster upgrade config missing token: {cluster_upgrade_config_token}')

cluster_upgrade_docs_text = (ROOT / 'docs/cluster-upgrade.md').read_text(encoding='utf-8')
for cluster_upgrade_docs_token in [
    'Cluster Upgrade And Version-Skew Guardrails',
    'make cluster-upgrade-plan',
    'CLUSTER_UPGRADE_PROFILE=production-upgrade',
    'reports/cluster-upgrade-plan.md',
    'reports/cluster-upgrade-values.yaml',
    'RKE2',
    'version skew',
    'etcd snapshot',
    'rollback',
]:
    if cluster_upgrade_docs_token not in cluster_upgrade_docs_text:
        errors.append(f'Cluster upgrade docs missing token: {cluster_upgrade_docs_token}')

disaster_recovery_plan_text = (ROOT / 'scripts/disaster_recovery_plan.py').read_text(encoding='utf-8')
for disaster_recovery_plan_token in [
    'Disaster Recovery And Business Continuity Plan',
    'public-safe',
    'post-drill-review',
    'disaster-recovery-values.yaml',
    'make disaster-recovery-plan',
    'RTO/RPO',
    'restore drill',
]:
    if disaster_recovery_plan_token not in disaster_recovery_plan_text:
        errors.append(f'Disaster recovery plan script missing token: {disaster_recovery_plan_token}')

disaster_recovery_config_text = (ROOT / 'config/disaster-recovery.yaml').read_text(encoding='utf-8')
for disaster_recovery_config_token in [
    'defaultProfile: disabled',
    'lab-dr:',
    'staging-rehearsal:',
    'production-dr:',
    'regulated-bcp:',
    'supportedStrategies:',
    'requiredChecks:',
]:
    if disaster_recovery_config_token not in disaster_recovery_config_text:
        errors.append(f'Disaster recovery config missing token: {disaster_recovery_config_token}')

disaster_recovery_docs_text = (ROOT / 'docs/disaster-recovery.md').read_text(encoding='utf-8')
for disaster_recovery_docs_token in [
    'Article 26 Baseline',
    'make disaster-recovery-plan',
    'DISASTER_RECOVERY_PROFILE=production-dr',
    'reports/disaster-recovery-plan.md',
    'reports/disaster-recovery-values.yaml',
    'business continuity',
    'post-drill review',
]:
    if disaster_recovery_docs_token not in disaster_recovery_docs_text:
        errors.append(f'Disaster recovery docs missing token: {disaster_recovery_docs_token}')

database_migration_controller_text = (ROOT / 'scripts/database_migration_controller.py').read_text(encoding='utf-8')
for database_migration_controller_token in [
    'Database Migration Controller Plan',
    'public-safe',
    'MIGRATION_ALLOW_SECRET_MATERIAL',
    'MIGRATION_SKIP_UNAVAILABLE_DATABASES',
    'MIGRATION_POSTGRES_CLIENT_IMAGE',
    'pg_dump --format=custom',
    'pg_restore --clean --if-exists --no-owner',
    'make database-migration-plan',
]:
    if database_migration_controller_token not in database_migration_controller_text:
        errors.append(f'Database migration controller script missing token: {database_migration_controller_token}')

database_migration_config_text = (ROOT / 'config/database-migration.yaml').read_text(encoding='utf-8')
for database_migration_config_token in [
    'defaultProfile: lab',
    'production:',
    'skipUnavailableSources: true',
    'skipUnavailableSources: false',
    'requireAllowSecretMaterial: true',
    'postgresql:',
    'postgis:',
    'timescaledb:',
    'status: automated',
    'status: scaffolded',
    'phases:',
]:
    if database_migration_config_token not in database_migration_config_text:
        errors.append(f'Database migration config missing controller token: {database_migration_config_token}')

database_migration_docs_text = (ROOT / 'docs/database-migration-controller.md').read_text(encoding='utf-8')
for database_migration_docs_token in [
    'Database Migration Controller',
    'make database-migration-plan',
    'MIGRATION_STAGE=databases',
    'MIGRATION_ALLOW_SECRET_MATERIAL=true',
    'MIGRATION_SKIP_UNAVAILABLE_DATABASES=false',
    'PostgreSQL, PostGIS, and TimescaleDB',
    'Optional engines',
]:
    if database_migration_docs_token not in database_migration_docs_text:
        errors.append(f'Database migration controller docs missing token: {database_migration_docs_token}')

edge_migration_plan_text = (ROOT / 'scripts/edge_migration_plan.py').read_text(encoding='utf-8')
for edge_migration_plan_token in [
    'Ingress And Edge Migration Plan',
    'public-safe',
    'MIGRATION_INGRESS_HOST',
    'MIGRATION_TLS_CERT_FILE',
    'MIGRATION_TLS_KEY_FILE',
    'MIGRATION_TLS_PFX_FILE',
    'MIGRATION_TLS_MODE=letsencrypt',
    'source allowlist',
    'backend Services already exist',
    'make edge-migration-plan',
]:
    if edge_migration_plan_token not in edge_migration_plan_text:
        errors.append(f'Edge migration plan script missing token: {edge_migration_plan_token}')

edge_migration_config_text = (ROOT / 'config/edge-migration.yaml').read_text(encoding='utf-8')
for edge_migration_config_token in [
    'defaultProfile: traefik-public',
    'ingressClassName: traefik',
    'preserveBackendNginx: internal-only',
    'requireBackendServiceBeforeApply: true',
    'defaultTlsMode: cert-manager-self-signed',
    'sourceAllowListRecommended: true',
    'ingress-nginx:',
    'internal-only:',
]:
    if edge_migration_config_token not in edge_migration_config_text:
        errors.append(f'Edge migration config missing ingress/edge token: {edge_migration_config_token}')

edge_migration_docs_text = (ROOT / 'docs/edge-migration.md').read_text(encoding='utf-8')
for edge_migration_docs_token in [
    'Ingress And Edge Migration',
    'make edge-migration-plan',
    'MIGRATION_STAGE=manifests',
    'MIGRATION_INGRESS_HOST',
    'DEPLOY_ALLOWED_CIDRS',
    'Compose nginx edge gateways',
    'RKE2-bundled Traefik',
    'backend Kubernetes Service already exists',
    'MIGRATION_TLS_MODE=lab-ca',
    'MIGRATION_TLS_MODE=pfx',
    'MIGRATION_TLS_EXTRA_HOSTS',
    'tls-trust/',
    'NET::ERR_CERT_AUTHORITY_INVALID',
]:
    if edge_migration_docs_token not in edge_migration_docs_text:
        errors.append(f'Edge migration docs missing ingress/edge token: {edge_migration_docs_token}')

environment_profile_plan_text = (ROOT / 'scripts/environment_profile_plan.py').read_text(encoding='utf-8')
for environment_profile_plan_token in [
    'Environment Profile Plan',
    'public-safe',
    'environment-profile-values.yaml',
    'environment-profile-evidence-bundle.md',
    'MIGRATION_PROFILE=lab',
    'MIGRATION_IMAGE_MODE=preload',
    'make environment-profile-plan',
    'Strict database migration',
    'Secret provider profile',
    'Registry promotion profile',
    'Runtime hardening profile',
    'GitOps delivery profile',
    'Progressive delivery profile',
    'Scaling policy profile',
    'Network connectivity profile',
    'Access governance profile',
    'Compliance evidence profile',
    'Incident response profile',
    'Change management profile',
    'Cutover gate profile',
    'Smoke-test profile',
    'Release runbook profile',
    'Cluster upgrade profile',
    'Evidence Bundle',
    'publicReports',
    'Disaster recovery profile',
    'smokeTesting.profile',
    'releaseRunbook.profile',
    'clusterUpgrade.profile',
]:
    if environment_profile_plan_token not in environment_profile_plan_text:
        errors.append(f'Environment profile plan script missing token: {environment_profile_plan_token}')

environment_profiles_config_text = (ROOT / 'config/environment-profiles.yaml').read_text(encoding='utf-8')
for environment_profiles_config_token in [
    'defaultProfile: lab',
    'staging:',
    'production:',
    'migrationProfile: production',
    'secretProviderProfile: vault',
    'registryPromotionProfile: enterprise-signed',
    'runtimeHardeningProfile: production-restricted',
    'gitOpsProfile: production-argocd',
    'progressiveDeliveryProfile: production-canary',
    'scalingPolicyProfile: production-hpa',
    'networkConnectivityProfile: production-restricted',
    'accessGovernanceProfile: oidc-sso',
    'complianceEvidenceProfile: production-audit-pack',
    'incidentResponseProfile: production-oncall',
    'changeManagementProfile: production-cab',
    'cutoverGateProfile: production-cutover',
    'smokeTestProfile: production-smoke',
    'releaseRunbookProfile: production-release',
    'clusterUpgradeProfile: production-upgrade',
    'disasterRecoveryProfile: production-dr',
    'reports/smoke-test-plan.md',
    'reports/release-runbook-plan.md',
    'reports/cluster-upgrade-plan.md',
    'evidenceBundle:',
    'publicReports:',
    'privateEvidence:',
    'imageMode: preload',
    'imageMode: registry',
    'strictDatabaseMigration: true',
    'requireReleaseEvidence: true',
    'helmValues:',
]:
    if environment_profiles_config_token not in environment_profiles_config_text:
        errors.append(f'Environment profile config missing token: {environment_profiles_config_token}')

environment_profiles_docs_text = (ROOT / 'docs/environment-profiles.md').read_text(encoding='utf-8')
for environment_profiles_docs_token in [
    'Environment Profiles',
    'make environment-profile-plan',
    'reports/environment-profile-values.yaml',
    'reports/environment-profile-evidence-bundle.md',
    'MIGRATION_PROFILE=lab',
    'MIGRATION_IMAGE_MODE=preload',
    'GitOps delivery',
    'progressive delivery',
    'scaling policy',
    'network connectivity',
    'access governance',
    'compliance evidence',
    'incident response',
    'change management',
    'cutover gates',
    'smoke tests',
    'release runbook',
    'cluster upgrade',
    'evidence bundle',
    'disaster recovery',
    'production',
    'restore drills',
]:
    if environment_profiles_docs_token not in environment_profiles_docs_text:
        errors.append(f'Environment profile docs missing token: {environment_profiles_docs_token}')

secret_management_values_text = (ROOT / 'helm/urban-platform-infra/values.yaml').read_text(encoding='utf-8')
for secret_management_values_token in [
    'providerAdapters:',
    'kubernetesDirect:',
    'externalSecrets:',
    'sealedSecrets:',
    'rendersPlainKubernetesSecrets: false',
    'requiredOperator: external-secrets-operator',
    'requiredOperator: sealed-secrets-controller',
]:
    if secret_management_values_token not in secret_management_values_text:
        errors.append(f'Helm values missing secret provider adapter token: {secret_management_values_token}')

for runtime_hardening_values_token in [
    'runtimeHardening:',
    'profile: disabled',
    'policyEngine: none',
    'requireReadOnlyRootFilesystem: false',
    'requireSignatureVerification: false',
    'reports/runtime-hardening-plan.md',
]:
    if runtime_hardening_values_token not in secret_management_values_text:
        errors.append(f'Helm values missing runtime hardening token: {runtime_hardening_values_token}')

for gitops_delivery_values_token in [
    'gitOpsDelivery:',
    'profile: operator-managed',
    'controller: none',
    'driftDetection: report-only',
    'reports/gitops-delivery-plan.md',
]:
    if gitops_delivery_values_token not in secret_management_values_text:
        errors.append(f'Helm values missing GitOps delivery token: {gitops_delivery_values_token}')

for progressive_delivery_values_token in [
    'progressiveDelivery:',
    'profile: disabled',
    'strategy: rolling-update',
    'controller: none',
    'reports/progressive-delivery-plan.md',
]:
    if progressive_delivery_values_token not in secret_management_values_text:
        errors.append(f'Helm values missing progressive delivery token: {progressive_delivery_values_token}')

for scaling_policy_values_token in [
    'scalingPolicy:',
    'profile: disabled',
    'mode: disabled',
    'metricsSource: none',
    'reports/scaling-policy-plan.md',
]:
    if scaling_policy_values_token not in secret_management_values_text:
        errors.append(f'Helm values missing scaling policy token: {scaling_policy_values_token}')

for network_connectivity_values_token in [
    'networkConnectivity:',
    'profile: disabled',
    'mode: baseline',
    'ingressClassName: traefik',
    'serviceMesh:',
    'provider: none',
    'reports/network-connectivity-plan.md',
]:
    if network_connectivity_values_token not in secret_management_values_text:
        errors.append(f'Helm values missing network connectivity token: {network_connectivity_values_token}')

for access_governance_values_token in [
    'accessGovernance:',
    'profile: disabled',
    'mode: baseline',
    'serviceAccountTokenAutomount: false',
    'identity:',
    'provider: none',
    'tenantIsolation:',
    'reports/access-governance-plan.md',
]:
    if access_governance_values_token not in secret_management_values_text:
        errors.append(f'Helm values missing access governance token: {access_governance_values_token}')

for compliance_evidence_values_token in [
    'complianceEvidence:',
    'profile: disabled',
    'mode: baseline',
    'collectReports: false',
    'requirePrivateIndex: false',
    'packaging:',
    'format: report-only',
    'reports/compliance-evidence-plan.md',
]:
    if compliance_evidence_values_token not in secret_management_values_text:
        errors.append(f'Helm values missing compliance evidence token: {compliance_evidence_values_token}')

for incident_response_values_token in [
    'incidentResponse:',
    'profile: disabled',
    'mode: baseline',
    'severityModel: none',
    'requirePaging: false',
    'runbooks:',
    'requirePostIncidentReview: false',
    'reports/incident-response-plan.md',
]:
    if incident_response_values_token not in secret_management_values_text:
        errors.append(f'Helm values missing incident response token: {incident_response_values_token}')

for change_management_values_token in [
    'changeManagement:',
    'profile: disabled',
    'mode: baseline',
    'approvalModel: none',
    'requireChangeTicket: false',
    'maintenanceWindow:',
    'requirePostChangeReview: false',
    'reports/change-management-plan.md',
]:
    if change_management_values_token not in secret_management_values_text:
        errors.append(f'Helm values missing change management token: {change_management_values_token}')

for cutover_gates_values_token in [
    'cutoverGates:',
    'profile: disabled',
    'mode: baseline',
    'trafficSwitch:',
    'method: none',
    'requireDnsTlsEvidence: false',
    'preCutover:',
    'requireImportPreflight: false',
    'smokeTests:',
    'requirePostMigrationCheck: false',
    'rollback:',
    'requireRecoveryPlan: false',
    'postCutover:',
    'requireOwnerHandoff: false',
    'reports/cutover-gate-plan.md',
]:
    if cutover_gates_values_token not in secret_management_values_text:
        errors.append(f'Helm values missing cutover gates token: {cutover_gates_values_token}')

for smoke_testing_values_token in [
    'smokeTesting:',
    'profile: disabled',
    'mode: baseline',
    'runner: none',
    'kubernetesRollout: false',
    'databaseConnections: false',
    'messagingConnections: false',
    'reports/smoke-test-plan.md',
]:
    if smoke_testing_values_token not in secret_management_values_text:
        errors.append(f'Helm values missing smoke testing token: {smoke_testing_values_token}')

for release_runbook_values_token in [
    'releaseRunbook:',
    'profile: disabled',
    'mode: baseline',
    'publisher: none',
    'deployer: none',
    'requireArtifactEvidence: false',
    'requireAttestation: false',
    'requireChangeApproval: false',
    'requirePrivateApprovalIndex: false',
    'reports/release-runbook-plan.md',
]:
    if release_runbook_values_token not in secret_management_values_text:
        errors.append(f'Helm values missing release runbook token: {release_runbook_values_token}')

for cluster_upgrade_values_token in [
    'clusterUpgrade:',
    'profile: disabled',
    'mode: baseline',
    'engine: rke2',
    'strategy: none',
    'drainNodes: false',
    'restartServices: false',
    'maxMinorSkew: 0',
    'requirePinnedVersion: false',
    'requireSupportedSkew: false',
    'requireEtcdSnapshot: false',
    'requireAddOnCompatibility: false',
    'requirePostUpgradeSmokeTest: false',
    'reports/cluster-upgrade-plan.md',
]:
    if cluster_upgrade_values_token not in secret_management_values_text:
        errors.append(f'Helm values missing cluster upgrade token: {cluster_upgrade_values_token}')

for disaster_recovery_values_token in [
    'disasterRecovery:',
    'profile: disabled',
    'mode: baseline',
    'failoverModel: none',
    'recoveryObjectives:',
    'requireRtoRpo: false',
    'restoreDrills:',
    'requirePostDrillReview: false',
    'reports/disaster-recovery-plan.md',
]:
    if disaster_recovery_values_token not in secret_management_values_text:
        errors.append(f'Helm values missing disaster recovery token: {disaster_recovery_values_token}')

backup_values_text = (ROOT / 'helm/urban-platform-infra/values.yaml').read_text(encoding='utf-8')
for backup_values_token in [
    'backup:',
    'profile: disabled',
    'installOperator: false',
    'rke2Etcd:',
    'imageArchives:',
    'externalProviders:',
    'urbackup:',
    'restic:',
    'kopia:',
    'borg:',
    'installInCluster: false',
]:
    if backup_values_token not in backup_values_text:
        errors.append(f'Helm values missing disabled backup token: {backup_values_token}')

for platform_capability_values_token in [
    'platformCapabilities:',
    'objectStorage:',
    'minio:',
    'messaging:',
    'mqtt:',
    'provider: emqx',
    'rabbitmq:',
    'nats:',
    'kafkaEcosystem:',
    'schemaRegistry:',
    'kafkaConnect:',
    'debezium:',
    'identity:',
    'keycloak:',
    'secrets:',
    'vault:',
    'policy:',
    'kyverno:',
    'workflows:',
    'temporal:',
    'argoWorkflows:',
    'serviceMesh:',
    'provider: none',
    'linkerd:',
    'istio:',
]:
    if platform_capability_values_token not in backup_values_text:
        errors.append(f'Helm values missing disabled platform capability token: {platform_capability_values_token}')

platform_capabilities_config_text = (ROOT / 'config/platform-capabilities.yaml').read_text(encoding='utf-8')
for platform_capabilities_config_token in [
    'defaultProfile: lab',
    'enabledByDefault: false',
    'recommendedOrder:',
    'category: object-storage',
    'minio:',
    'category: messaging',
    'mqtt:',
    'rabbitmq:',
    'nats:',
    'category: kafka-ecosystem',
    'schema-registry:',
    'kafka-connect:',
    'debezium:',
    'category: identity',
    'keycloak:',
    'category: secrets',
    'vault:',
    'category: policy',
    'kyverno:',
    'category: workflows',
    'temporal:',
    'argo-workflows:',
    'service-mesh:',
    'linkerd:',
    'istio:',
]:
    if platform_capabilities_config_token not in platform_capabilities_config_text:
        errors.append(f'Platform capabilities catalog missing token: {platform_capabilities_config_token}')

platform_capabilities_docs_text = (ROOT / 'docs/platform-capabilities.md').read_text(encoding='utf-8')
for platform_capabilities_docs_token in [
    'Optional Platform Capabilities',
    'disabled by default',
    'Recommended Enablement Order',
    'MinIO',
    'MQTT',
    'RabbitMQ',
    'NATS',
    'Keycloak',
    'Schema Registry',
    'Kafka Connect',
    'Debezium',
    'Vault',
    'Kyverno',
    'Temporal',
    'Argo Workflows',
    'Service mesh',
    'DEPLOY_ENABLE_MINIO=true',
]:
    if platform_capabilities_docs_token not in platform_capabilities_docs_text:
        errors.append(f'Platform capabilities docs missing token: {platform_capabilities_docs_token}')

import_profiles_text = (ROOT / 'config/import-profiles.yaml').read_text(encoding='utf-8')
for import_profile_token in [
    'defaultProfile: lab',
    'enabledByDefault: true',
    'minimumMemoryPerNode: 4Gi',
    'importedWorkloads:',
    'requests:',
    'cpu: 25m',
    'memory: 64Mi',
    'limits:',
    'cpu: 250m',
    'memory: 256Mi',
    'observability: disabled',
    'optionalCapabilities: disabled',
    'databaseInstances: 1',
    'kafkaReplicas: 1',
    'kafkaUi: disabled',
    'redisSentinel: disabled',
    'skipDockerSocketServices: true',
    'skipUnavailableDatabases: true',
    'preflight:',
    'minimumNodeMemory: 3500Mi',
    'minimumNodeDiskFree: 2048Mi',
    'maxImportedWorkloads: 40',
    'capacityUtilizationLimit: 0.70',
    'batchSize: 40',
    'importBatch: auto',
    'resume: true',
    'requireIngressEndpoint: false',
    'reports/import-migration/import-recovery-plan.md',
    'production:',
    'capacityUtilizationLimit: 0.85',
    'importBatch: all',
    'requireIngressEndpoint: true',
    'strictDatabaseMigration: true',
]:
    if import_profile_token not in import_profiles_text:
        errors.append(f'Import profiles catalog missing lab-safe token: {import_profile_token}')

values_schema_text = (ROOT / 'helm/urban-platform-infra/values.schema.json').read_text(encoding='utf-8')
for values_schema_capability_token in [
    '"platformCapabilities"',
    '"Optional platform capability catalog"',
    '"enabled"',
    '"secretProviderAdapter"',
    '"providerAdapters"',
    '"imagePromotionController"',
    '"requireSignatureOrAttestation"',
    '"runtimeHardening"',
    '"requireReadOnlyRootFilesystem"',
    '"requireSignatureVerification"',
    '"gitOpsDelivery"',
    '"driftDetection"',
    '"progressiveDelivery"',
    '"blue-green"',
    '"argo-rollouts"',
    '"scalingPolicy"',
    '"event-driven-keda"',
    '"clusterAutoscaler"',
    '"networkConnectivity"',
    '"mesh-linkerd"',
    '"mesh-istio"',
    '"requireExplicitCidrs"',
    '"accessGovernance"',
    '"oidc-sso"',
    '"multi-tenant"',
    '"requireGroupMapping"',
    '"complianceEvidence"',
    '"production-audit-pack"',
    '"regulated-retention"',
    '"requirePrivateIndex"',
    '"incidentResponse"',
    '"production-oncall"',
    '"regulated-incident"',
    '"requirePaging"',
    '"changeManagement"',
    '"production-cab"',
    '"regulated-change"',
    '"requireFreezeCheck"',
    '"cutoverGates"',
    '"Production cutover and smoke-test gate intent"',
    '"production-cutover"',
    '"requireDnsTlsEvidence"',
    '"requirePostMigrationCheck"',
    '"smokeTesting"',
    '"Post-migration smoke-test and health-probe intent"',
    '"production-smoke"',
    '"databaseConnections"',
    '"messagingConnections"',
    '"releaseRunbook"',
    '"Release runbook and evidence gate intent"',
    '"production-release"',
    '"requireArtifactEvidence"',
    '"requirePrivateApprovalIndex"',
    '"clusterUpgrade"',
    '"Cluster upgrade and version-skew guardrail intent"',
    '"production-upgrade"',
    '"requireSupportedSkew"',
    '"requireEtcdSnapshot"',
    '"requireAddOnCompatibility"',
    '"disasterRecovery"',
    '"production-dr"',
    '"regulated-bcp"',
    '"requireRtoRpo"',
]:
    if values_schema_capability_token not in values_schema_text:
        errors.append(f'Values schema missing platform capability token: {values_schema_capability_token}')

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

helmfile_sync_retry_text = (ROOT / 'scripts/tools/helmfile-sync-retry.sh').read_text(encoding='utf-8')
for helmfile_sync_retry_token in [
    'HELMFILE_SYNC_RETRIES',
    'HELMFILE_SYNC_RETRY_DELAY',
    'HELMFILE_API_WAIT_TIMEOUT',
    'HELMFILE_API_STABLE_SUCCESSES',
    'wait_for_stable_api',
    '/openapi/v2',
    'HELMFILE_PENDING_WAIT_TIMEOUT',
    'recover_pending_release',
    'last_deployed_revision',
    'latest_pending_release_secret',
    'another operation',
    'OPERATOR_KUBECONFIG_FORCE_REPAIR=true',
    'Refreshing operator kubeconfig before Helmfile retry',
    '"${helmfile_bin}" -f "${helmfile_config}" sync',
]:
    if helmfile_sync_retry_token not in helmfile_sync_retry_text:
        errors.append(f'Helmfile retry script missing token: {helmfile_sync_retry_token}')

local_path_installer_text = (ROOT / 'scripts/tools/install-local-path-storage.sh').read_text(encoding='utf-8')
for local_path_installer_token in [
    'LOCAL_PATH_PROVISIONER_VERSION',
    'KUBECTL_RETRIES',
    'kubectl_retry',
    'rancher/local-path-provisioner',
    'local-path-storage',
    'storageclass.kubernetes.io/is-default-class',
    'LOCAL_PATH_STORAGE_PATH',
    'LOCAL_PATH_PREPARE_HOST_PATHS',
    'container_file_t',
    'Recovered MIGRATION_RKE2_NODES',
    'rollout restart deployment/local-path-provisioner',
]:
    if local_path_installer_token not in local_path_installer_text:
        errors.append(f'Local-path installer script missing token: {local_path_installer_token}')
if 'Recovered MIGRATION_RKE2_NODES from ${fallback_inventory_path}: ${MIGRATION_RKE2_NODES}' in local_path_installer_text:
    errors.append('Local-path installer must not print recovered RKE2 node addresses')

helm_recovery_text = (ROOT / 'scripts/tools/recover-helm-release.sh').read_text(encoding='utf-8')
for helm_recovery_token in [
    'DEPLOY_RECOVER_FAILED_RELEASE',
    'DEPLOY_RECOVER_PENDING_PVCS',
    'DEPLOY_RECOVER_DELETE_PVCS',
    'missing-PVC CNPG initdb bootstraps',
    'persistentvolumeclaim',
    '"${helm_bin}" get manifest',
    'owner=helm,name=${release}',
    'app.kubernetes.io/part-of=urban-platform-infra',
]:
    if helm_recovery_token not in helm_recovery_text:
        errors.append(f'Helm recovery script missing token: {helm_recovery_token}')

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

secret_contract = safe_load((ROOT / 'config/secrets.contract.yaml').read_text(encoding='utf-8'))
if secret_contract.get('policy', {}).get('plaintextKubernetesSecretsAllowed') is not False:
    errors.append('Secret contract must disallow plaintext Kubernetes Secrets')

deployment_topologies = safe_load((ROOT / 'config/deployment-topologies.yaml').read_text(encoding='utf-8'))
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
    helm_values = safe_load((ROOT / topology['helmValues']).read_text(encoding='utf-8'))
    if helm_values.get('global', {}).get('cluster', {}).get('nodes', 0) < topology.get('minimumNodes'):
        errors.append(f'Deployment topology {topology_name} Helm override must be >= minimumNodes')
    inventory = safe_load((ROOT / topology['inventory']).read_text(encoding='utf-8'))
    groups = inventory.get('all', {}).get('children', {})
    if 'cluster_nodes' not in groups or 'rke2_servers' not in groups:
        errors.append(f'Deployment topology {topology_name} inventory must define cluster_nodes and rke2_servers')

platforms = safe_load((ROOT / 'config/platforms.yaml').read_text(encoding='utf-8'))
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

cluster_profiles = safe_load((ROOT / 'config/cluster-profiles.yaml').read_text(encoding='utf-8'))
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

supply_chain_policy = safe_load((ROOT / 'config/supply-chain-policy.yaml').read_text(encoding='utf-8'))
policy = supply_chain_policy.get('policy', {})
if policy.get('nodeLtsMajor') != 24:
    errors.append('Supply-chain policy must require Node 24 LTS for Node-based workflow tooling')
release_integrity = policy.get('releaseIntegrity', {})
for control in [
    'requireChartVersionMatchesTag',
    'requireChecksums',
    'requireSbom',
    'requireReleaseManifest',
    'requireGithubArtifactAttestations',
    'requireOidcForSigning',
]:
    if release_integrity.get(control) is not True:
        errors.append(f'Supply-chain policy must enable release control: {control}')
release_verification = policy.get('releaseVerification', {})
for verification_control in [
    'verifyTagMatchesChartVersion',
    'verifyChecksumContents',
    'verifySbomJson',
    'verifyReleaseManifestJson',
    'publicSafetyScan',
]:
    if release_verification.get(verification_control) is not True:
        errors.append(f'Supply-chain policy must enable release verification control: {verification_control}')
if release_verification.get('offlineVerifier') != 'scripts/release/verify_release_evidence.py':
    errors.append('Supply-chain policy must point at the offline release evidence verifier')
if release_verification.get('report') != 'reports/release-evidence-verification.md':
    errors.append('Supply-chain policy must write the public-safe release verification report')
release_artifacts = policy.get('releaseArtifacts', {})
if release_artifacts.get('releaseManifest') != 'dist/release-evidence.json':
    errors.append('Supply-chain policy must require the public-safe release evidence manifest')
if 'master' not in policy.get('githubActions', {}).get('disallowFloatingRefs', []):
    errors.append('Supply-chain policy must disallow floating @master action refs')
if 'main' not in policy.get('githubActions', {}).get('disallowFloatingRefs', []):
    errors.append('Supply-chain policy must disallow floating @main action refs')
if policy.get('dependencyReview', {}).get('enabledForPullRequests') is not True:
    errors.append('Supply-chain policy must enable pull-request dependency review')

image_policy = safe_load((ROOT / 'config/image-policy.yaml').read_text(encoding='utf-8'))
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
image_promotion_controls = image_policy_controls.get('imagePromotion', {})
for promotion_control in [
    'requirePrivateRegistry',
    'requireDigestPins',
    'requireVulnerabilityScan',
    'requireSbom',
    'requireSignatureOrAttestation',
    'requirePromotionRecord',
    'publicSafeReport',
]:
    if image_promotion_controls.get(promotion_control) is not True:
        errors.append(f'Image policy must enable promotion evidence control: {promotion_control}')
if image_promotion_controls.get('planGenerator') != 'scripts/images/promotion_plan.py':
    errors.append('Image policy must point at the public-safe image promotion planner')
if image_promotion_controls.get('report') != 'reports/image-promotion-plan.md':
    errors.append('Image policy must write the public-safe image promotion report')
if image_promotion_controls.get('controllerConfig') != 'config/registry-promotion.yaml':
    errors.append('Image policy must point at the registry promotion controller config')
if image_promotion_controls.get('controllerGenerator') != 'scripts/images/registry_promotion_controller.py':
    errors.append('Image policy must point at the registry promotion controller script')
if image_promotion_controls.get('controllerReport') != 'reports/registry-promotion-controller.md':
    errors.append('Image policy must write the registry promotion controller report')
if image_promotion_controls.get('controllerOverrides') != 'reports/registry-promotion-values.yaml':
    errors.append('Image policy must write the registry promotion values overlay')
if image_promotion_controls.get('defaultControllerProfile') != 'disabled':
    errors.append('Image policy registry promotion controller must default to disabled')
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
    'nginxinc/nginx-unprivileged:1.30.2',
    'traefik:v3.7.1',
    'confluentinc/cp-kafka:7.9.6',
    'confluentinc/cp-zookeeper:7.9.6',
    'redis:8.6.2',
    'postgres:18.3',
    'postgis/postgis:18-3.6',
    'timescale/timescaledb:2.26.4-pg18',
    'docker.elastic.co/elasticsearch/elasticsearch:9.4.1',
    'docker.elastic.co/kibana/kibana:9.4.1',
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

standalone_docker_surface_text = '\n'.join(
    (ROOT / standalone_file).read_text(encoding='utf-8')
    for standalone_file in [
        '.env.standalone.example',
        'Makefile',
        'compose/README.md',
        'compose/docker-compose.ha.yml',
        'compose/docker-compose.standalone.yml',
        'scripts/tools/standalone-docker-config.sh',
    ]
)
for standalone_token in [
    'docker-standalone-up',
    'compose/docker-compose.standalone.yml',
    'STANDALONE_ENV_FILE',
    'STANDALONE_BIND_IP',
    'STANDALONE_DOMAIN',
    'STANDALONE_TLS_MODE',
    'STANDALONE_AUTO_INSTALL_OPENSSL',
    'STANDALONE_NGINX_IMAGE',
    'STANDALONE_POSTGRES_IMAGE',
    'STANDALONE_POSTGIS_IMAGE',
    'STANDALONE_TIMESCALE_IMAGE',
    'STANDALONE_KAFKA_EXTERNAL_HOST',
    '${STANDALONE_BIND_IP:-0.0.0.0}',
    '${STANDALONE_HTTP_PORT:-80}',
    '${STANDALONE_HTTPS_PORT:-443}',
    'standalone-ca.crt',
    'proxy_pass',
    'self-signed',
    'provided',
    'pfx',
]:
    if standalone_token not in standalone_docker_surface_text:
        errors.append(f'Standalone Docker profile missing token: {standalone_token}')

slo_contract = safe_load((ROOT / 'config/slo.yaml').read_text(encoding='utf-8'))
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

database_template_text = (ROOT / 'helm/urban-platform-infra/templates/databases-cnpg.yaml').read_text(
    encoding='utf-8'
)
for database_token in [
    'storageOverride',
    'enableDeprecatedPodMonitor',
    'storageClass:',
    'postgresUID:',
    'postgresGID:',
    '$resources',
    '.Values.databases.resources',
]:
    if database_token not in database_template_text:
        errors.append(f'Database template missing required token: {database_token}')
monitoring_services_text = (ROOT / 'helm/urban-platform-infra/templates/monitoring-servicemonitors.yaml').read_text(encoding='utf-8')
if 'ServiceMonitor' not in monitoring_services_text or 'namespaceSelector' not in monitoring_services_text:
    errors.append('Monitoring ServiceMonitor template must define namespace-scoped generic targets')
kafka_template_text = (ROOT / 'helm/urban-platform-infra/templates/messaging-kafka.yaml').read_text(encoding='utf-8')
for kafka_template_token in [
    '$zookeeperReplicas',
    '$kafkaReplicas',
    '$zookeeperServers',
    '$zookeeperConnect',
    '$kafkaReplicationFactor',
    '$kafkaMinIsr',
    '.Values.messaging.kafka.zookeeper.resources',
    '.Values.messaging.kafka.resources',
    '.Values.messaging.kafka.ui.resources',
    'cip.podSecurityContext',
    'cip.securityContext',
]:
    if kafka_template_token not in kafka_template_text:
        errors.append(f'Kafka template missing lab replica/security token: {kafka_template_token}')
redis_template_text = (ROOT / 'helm/urban-platform-infra/templates/redis.yaml').read_text(encoding='utf-8')
for redis_template_token in [
    '$redisReplicas',
    '$sentinelQuorum',
    'sentinel monitor mymaster',
    '.Values.messaging.redis.resources',
    '.Values.messaging.redis.sentinel.resources',
    'cip.podSecurityContext',
    'cip.securityContext',
]:
    if redis_template_token not in redis_template_text:
        errors.append(f'Redis template missing lab replica/security token: {redis_template_token}')
namespace_resource_template = (ROOT / 'helm/urban-platform-infra/templates/namespace-resource-controls.yaml').read_text(encoding='utf-8')
for namespace_resource_token in ['kind: LimitRange', 'kind: ResourceQuota', '.Values.namespace.limitRange', '.Values.namespace.resourceQuota']:
    if namespace_resource_token not in namespace_resource_template:
        errors.append(f'Namespace resource guardrail template missing token: {namespace_resource_token}')
eck_template_text = (ROOT / 'helm/urban-platform-infra/templates/observability-eck.yaml').read_text(encoding='utf-8')
for eck_template_token in [
    'podTemplate:',
    'name: elasticsearch',
    '.Values.observability.elasticsearch.resources',
    '$elasticsearchService',
    'nodePort: {{ . }}',
]:
    if eck_template_token not in eck_template_text:
        errors.append(f'ECK template missing Elasticsearch resources token: {eck_template_token}')
for kibana_ingress_token in [
    'server.publicBaseUrl',
    'selfSignedCertificate:',
    'disabled: true',
    'kind: Ingress',
    'name: {{ $kibanaName }}',
    'include "cip.ingressAnnotations"',
    'include "cip.traefikHttpRedirectAnnotations"',
    'printf "%s-kb-http" $kibanaName',
]:
    if kibana_ingress_token not in eck_template_text:
        errors.append(f'ECK template missing Kibana public ingress token: {kibana_ingress_token}')
status_script = (ROOT / 'scripts/health/status.sh').read_text(encoding='utf-8')
for status_token in ['prometheusrules.monitoring.coreos.com', 'servicemonitors.monitoring.coreos.com', 'observability']:
    if status_token not in status_script:
        errors.append(f'status script missing observability check: {status_token}')
observability_contract = safe_load((ROOT / 'config/observability.yaml').read_text(encoding='utf-8'))
if observability_contract.get('default') != 'disabled' or observability_contract.get('defaultStack') != 'disabled':
    errors.append('Observability contract must default to the disabled low-resource profile')
for observability_profile in ['elasticsearch', 'grafana', 'prometheus', 'opentelemetry', 'loki', 'clickhouse']:
    if observability_contract.get('profiles', {}).get(observability_profile, {}).get('enabled') is not False:
        errors.append(f'Observability contract must disable default profile: {observability_profile}')
helmfile_text = (ROOT / 'deploy/helmfile.yaml.gotmpl').read_text(encoding='utf-8')
for helmfile_token in [
    'open-telemetry.github.io/opentelemetry-helm-charts',
    'opentelemetry-collector',
    'INSTALL_ECK',
    'INSTALL_PROMETHEUS',
    'GRAFANA_ENABLED',
    'INSTALL_OPENTELEMETRY',
    'kube-prometheus-stack',
    'GRAFANA_NODE_PORT',
    'INSTALL_LOKI',
    'LOKI_NODE_PORT',
    'INSTALL_CLICKHOUSE',
    'CLICKHOUSE_HTTP_NODE_PORT',
    'CLICKHOUSE_TCP_NODE_PORT',
    'eck-operator',
    'version: 0.28.0',
    'version: 3.4.0',
    'memory: 256Mi',
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
