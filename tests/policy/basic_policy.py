#!/usr/bin/env python3
import sys
from pathlib import Path
import yaml

if len(sys.argv) != 2:
    print('Usage: basic_policy.py rendered.yaml', file=sys.stderr)
    sys.exit(2)

path = Path(sys.argv[1])
if not path.exists():
    print(f'Missing rendered manifest: {path}', file=sys.stderr)
    sys.exit(2)

errors = []
network_policies = set()
namespace_seen = False
for doc in yaml.safe_load_all(path.read_text()):
    if not isinstance(doc, dict):
        continue
    kind = doc.get('kind')
    meta = doc.get('metadata', {})
    name = meta.get('name', '<unknown>')
    labels = meta.get('labels', {})
    if kind == 'Namespace':
        namespace_seen = True
        if labels.get('pod-security.kubernetes.io/enforce') not in {'baseline', 'restricted'}:
            errors.append(f'Namespace/{name}: pod security enforce must be baseline or restricted')
        if labels.get('pod-security.kubernetes.io/audit') != 'restricted':
            errors.append(f'Namespace/{name}: pod security audit should be restricted')
        if labels.get('pod-security.kubernetes.io/warn') != 'restricted':
            errors.append(f'Namespace/{name}: pod security warn should be restricted')
        for mode in ('enforce', 'audit', 'warn'):
            if f'pod-security.kubernetes.io/{mode}-version' not in labels:
                errors.append(f'Namespace/{name}: pod security {mode} version label is missing')
    if kind == 'NetworkPolicy':
        network_policies.add(name)
    if kind == 'Secret':
        errors.append(f'Secret/{name}: plain Kubernetes Secret manifests must not be rendered by this chart')
    if kind in {'Deployment', 'StatefulSet'}:
        spec = doc.get('spec', {})
        tmpl = spec.get('template', {})
        podspec = tmpl.get('spec', {})
        containers = podspec.get('containers', [])
        if podspec.get('hostNetwork'):
            errors.append(f'{kind}/{name}: hostNetwork must not be enabled')
        if podspec.get('hostPID'):
            errors.append(f'{kind}/{name}: hostPID must not be enabled')
        if podspec.get('hostIPC'):
            errors.append(f'{kind}/{name}: hostIPC must not be enabled')
        if podspec.get('automountServiceAccountToken') is not False:
            errors.append(f'{kind}/{name}: service account token automount must be false')
        if podspec.get('serviceAccountName') in {None, '', 'default'}:
            errors.append(f'{kind}/{name}: must use a dedicated service account')
        if podspec.get('enableServiceLinks') is not False:
            errors.append(f'{kind}/{name}: enableServiceLinks must be false')
        if not containers:
            errors.append(f'{kind}/{name}: no containers')
        for c in containers:
            image = c.get('image', '')
            if image.endswith(':latest') or ':latest-' in image or '-latest' in image.rsplit(':', 1)[-1]:
                errors.append(f'{kind}/{name}: mutable image tag is not allowed: {image}')
            security_context = c.get('securityContext', {})
            if security_context.get('privileged'):
                errors.append(f'{kind}/{name}: privileged container is not allowed')
            if security_context.get('allowPrivilegeEscalation'):
                errors.append(f'{kind}/{name}: allowPrivilegeEscalation must not be true')
            if security_context.get('capabilities', {}).get('add'):
                errors.append(f'{kind}/{name}: added Linux capabilities are not allowed')
            if not c.get('ports'):
                # worker services may have no ports, but this stack expects them from docker ps.
                pass
        if name.startswith('app-'):
            pod_security_context = podspec.get('securityContext', {})
            seccomp = pod_security_context.get('seccompProfile', {})
            if seccomp.get('type') != 'RuntimeDefault':
                errors.append(f'{kind}/{name}: application pods must use RuntimeDefault seccomp')
            for c in containers:
                security_context = c.get('securityContext', {})
                dropped = set(security_context.get('capabilities', {}).get('drop', []))
                if security_context.get('allowPrivilegeEscalation') is not False:
                    errors.append(f'{kind}/{name}: application containers must disable privilege escalation')
                if security_context.get('runAsNonRoot') is not True:
                    errors.append(f'{kind}/{name}: application containers must run as non-root')
                if 'ALL' not in dropped:
                    errors.append(f'{kind}/{name}: application containers must drop ALL capabilities')
        if kind == 'Deployment' and spec.get('replicas', 0) < 2:
            errors.append(f'{kind}/{name}: replicas should be >= 2 for HA')

expected_network_policies = {
    'urban-platform-default-deny',
    'urban-platform-same-namespace',
    'urban-platform-dns-egress',
    'urban-platform-kubernetes-api-egress',
}
missing_network_policies = sorted(expected_network_policies - network_policies)
if missing_network_policies:
    errors.append(f'missing required NetworkPolicies: {", ".join(missing_network_policies)}')
if not namespace_seen:
    errors.append('rendered manifest does not include a Namespace with Pod Security Admission labels')

if errors:
    for e in errors:
        print('POLICY:', e, file=sys.stderr)
    sys.exit(1)
print('Basic policy checks passed')
