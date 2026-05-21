#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:
    yaml = None


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {'', "''", '""'}:
        return ''
    if value.lower() == 'true':
        return True
    if value.lower() == 'false':
        return False
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def load_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith('#'):
            continue
        line_without_comment = raw_line.split(' #', 1)[0].rstrip()
        stripped = line_without_comment.lstrip()
        if stripped.startswith('- ') or ':' not in stripped:
            continue
        indent = len(line_without_comment) - len(stripped)
        key, raw_value = stripped.split(':', 1)
        key = key.strip().strip('"\'')
        raw_value = raw_value.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if raw_value == '':
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = parse_scalar(raw_value)

    return root


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f'{path} does not exist')
    text = path.read_text(encoding='utf-8')
    data = yaml.safe_load(text) if yaml else load_simple_yaml(text)
    data = data or {}
    if not isinstance(data, dict):
        raise ValueError(f'{path} must contain a YAML mapping')
    return data


def is_enabled(value: Any) -> bool:
    return value is True


def flag(value: Any) -> str:
    return 'enabled' if is_enabled(value) else 'disabled'


def configured(value: Any) -> str:
    return 'configured' if bool(value) else 'not configured'


def nested(mapping: dict[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def public_safe_backup_plan(values: dict[str, Any], policy: dict[str, Any]) -> str:
    backup = values.get('backup', {}) if isinstance(values.get('backup'), dict) else {}
    databases = values.get('databases', {}) if isinstance(values.get('databases'), dict) else {}
    db_backup = databases.get('backup', {}) if isinstance(databases.get('backup'), dict) else {}
    storage_tiers = values.get('storageTiers', {}) if isinstance(values.get('storageTiers'), dict) else {}
    cold_store = nested(storage_tiers, 'cold', 'objectStore') or {}
    velero = backup.get('velero', {}) if isinstance(backup.get('velero'), dict) else {}
    rke2_etcd = backup.get('rke2Etcd', {}) if isinstance(backup.get('rke2Etcd'), dict) else {}
    image_archives = backup.get('imageArchives', {}) if isinstance(backup.get('imageArchives'), dict) else {}
    external_providers = backup.get('externalProviders', {})
    if not isinstance(external_providers, dict):
        external_providers = {}
    policy_layers = policy.get('layers', {}) if isinstance(policy.get('layers'), dict) else {}

    db_object_store = db_backup.get('objectStore', {}) if isinstance(db_backup.get('objectStore'), dict) else {}
    db_schedule = db_backup.get('schedule', {}) if isinstance(db_backup.get('schedule'), dict) else {}
    velero_schedule = velero.get('schedule', {}) if isinstance(velero.get('schedule'), dict) else {}

    lines = [
        '# Backup And Restore Plan',
        '',
        'This report is public-safe. It intentionally reports whether backup fields are configured, not bucket names, secret names, hostnames, IP addresses, or credentials.',
        '',
        '## Current Defaults',
        '',
        f'- Global backup switch: `{flag(backup.get("enabled"))}`',
        f'- Backup profile: `{backup.get("profile", "disabled")}`',
        f'- Policy default profile: `{policy.get("defaultProfile", "disabled")}`',
        f'- Policy enabled by default: `{str(policy.get("enabledByDefault", False)).lower()}`',
        '',
        '## Kubernetes And Volume Backups',
        '',
        f'- Velero operator install: `{flag(velero.get("installOperator"))}`',
        f'- Velero backups: `{flag(velero.get("enabled"))}`',
        f'- Velero schedule: `{flag(velero_schedule.get("enabled"))}`',
        f'- Velero bucket: `{configured(velero.get("bucket"))}`',
        f'- Velero credential reference: `{configured(nested(velero, "secretRef", "name"))}`',
        f'- Velero snapshots: `{flag(velero.get("snapshotsEnabled"))}`',
        f'- Velero node agent: `{flag(velero.get("nodeAgentEnabled"))}`',
        '',
        '## Database Backups',
        '',
        f'- CloudNativePG backup rendering: `{flag(db_backup.get("enabled"))}`',
        f'- CloudNativePG schedule: `{flag(db_schedule.get("enabled"))}`',
        f'- CloudNativePG retention policy: `{db_backup.get("retentionPolicy", "30d")}`',
        f'- Database object store switch: `{flag(db_object_store.get("enabled"))}`',
        f'- Database object store target: `{configured(db_object_store.get("destinationPath") or db_object_store.get("bucket") or cold_store.get("bucket"))}`',
        f'- Database object store credential reference: `{configured(nested(db_object_store, "secretRef", "name") or nested(cold_store, "secretRef", "name"))}`',
        '',
        '## Cluster And Import Artifacts',
        '',
        f'- RKE2 etcd backup policy: `{flag(rke2_etcd.get("enabled"))}`',
        f'- Image archive retention: `{flag(image_archives.get("enabled"))}`',
        f'- Cold object-store tier: `{flag(cold_store.get("enabled"))}`',
        f'- Cold object-store bucket: `{configured(cold_store.get("bucket"))}`',
        '',
        '## External Backup Providers',
        '',
    ]

    for provider_name in ['urbackup', 'restic', 'kopia', 'borg']:
        provider = external_providers.get(provider_name, {})
        if not isinstance(provider, dict):
            provider = {}
        lines.extend([
            f'- `{provider_name}`: `{flag(provider.get("enabled"))}`',
            f'  - mode: `{provider.get("mode", "external")}`',
            f'  - in-cluster install: `{flag(provider.get("installInCluster"))}`',
            f'  - target configured: `{configured(provider.get("endpoint") or provider.get("repository"))}`',
            f'  - credential reference: `{configured(nested(provider, "secretRef", "name"))}`',
        ])

    lines.extend([
        '',
        '## Policy Layers',
        '',
    ])

    for layer_name in [
        'rke2Etcd',
        'cloudnativePg',
        'velero',
        'imageArchives',
        'urbackup',
        'restic',
        'kopia',
        'borg',
        'secrets',
    ]:
        layer = policy_layers.get(layer_name, {}) if isinstance(policy_layers.get(layer_name), dict) else {}
        lines.append(f'- `{layer_name}`: `{flag(layer.get("enabled"))}`')

    lines.extend([
        '',
        '## Enablement Notes',
        '',
        '- Backups are disabled by default and require explicit values or deploy flags.',
        '- Create object-store buckets and credentials outside the chart, then reference them through a secret manager.',
        '- Run restore drills before treating a backup profile as production-ready.',
        '- Keep full backup logs, bucket names, and credential references in private operator records.',
        '',
    ])
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate a public-safe backup/restore plan.')
    parser.add_argument('--values', default='helm/urban-platform-infra/values.yaml')
    parser.add_argument('--policy', default='config/backup-policy.yaml')
    parser.add_argument('--output', default='reports/backup-plan.md')
    args = parser.parse_args()

    values = load_yaml(Path(args.values))
    policy = load_yaml(Path(args.policy))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(public_safe_backup_plan(values, policy), encoding='utf-8')
    print(f'Backup plan written: {output_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
