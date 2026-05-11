#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_chart_metadata(chart: Path) -> dict[str, str]:
    chart_yaml = chart / 'Chart.yaml'
    metadata: dict[str, str] = {}
    for raw_line in chart_yaml.read_text(encoding='utf-8').splitlines():
        if ':' not in raw_line or raw_line.startswith((' ', '-')):
            continue
        key, value = raw_line.split(':', 1)
        metadata[key.strip()] = value.strip().strip('"\'')
    for key in ['name', 'version', 'appVersion']:
        if not metadata.get(key):
            raise SystemExit(f'Missing {key} in {chart_yaml.relative_to(ROOT).as_posix()}')
    return metadata


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def spdx_id(value: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9.-]+', '-', value).strip('-')
    return f'SPDXRef-{cleaned or "artifact"}'


def relative_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def package_for(path: Path, chart_name: str, chart_version: str) -> dict[str, object]:
    checksum = sha256(path)
    return {
        'name': path.name,
        'SPDXID': spdx_id(path.name),
        'versionInfo': chart_version,
        'supplier': 'Organization: city-intersection-project contributors',
        'downloadLocation': 'NOASSERTION',
        'filesAnalyzed': False,
        'packageFileName': relative_path(path),
        'checksums': [
            {
                'algorithm': 'SHA256',
                'checksumValue': checksum,
            }
        ],
        'licenseConcluded': 'NOASSERTION',
        'licenseDeclared': 'NOASSERTION',
        'copyrightText': 'NOASSERTION',
        'summary': f'Release artifact for {chart_name} {chart_version}.',
    }


def release_artifacts(dist: Path, rendered: Path | None, sbom: Path | None, checksums: Path | None) -> list[Path]:
    excluded = {path.resolve() for path in [sbom, checksums] if path is not None}
    artifacts = sorted(dist.glob('*.tgz'))
    if rendered is not None and rendered.exists():
        artifacts.append(rendered)
    if not artifacts:
        raise SystemExit(f'No release artifacts found in {relative_path(dist)}')
    return [path for path in artifacts if path.resolve() not in excluded]


def write_checksums(paths: list[Path], sbom: Path | None, checksums: Path) -> None:
    checksum_targets = [*paths]
    if sbom is not None and sbom.exists():
        checksum_targets.append(sbom)
    lines = [
        f'{sha256(path)}  {relative_path(path)}'
        for path in sorted(checksum_targets, key=lambda item: relative_path(item))
    ]
    checksums.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def build_sbom(chart: Path, dist: Path, rendered: Path | None, sbom: Path, checksums: Path | None) -> None:
    metadata = read_chart_metadata(chart)
    artifacts = release_artifacts(dist, rendered, sbom, checksums)
    packages = [
        {
            'name': metadata['name'],
            'SPDXID': spdx_id(metadata['name']),
            'versionInfo': metadata['version'],
            'supplier': 'Organization: city-intersection-project contributors',
            'downloadLocation': 'NOASSERTION',
            'filesAnalyzed': False,
            'licenseConcluded': 'NOASSERTION',
            'licenseDeclared': 'MIT',
            'copyrightText': 'NOASSERTION',
            'summary': 'Helm chart source package.',
        }
    ]
    packages.extend(package_for(path, metadata['name'], metadata['version']) for path in artifacts)

    relationships = [
        {
            'spdxElementId': 'SPDXRef-DOCUMENT',
            'relationshipType': 'DESCRIBES',
            'relatedSpdxElement': package['SPDXID'],
        }
        for package in packages
    ]
    combined_digest = hashlib.sha256(''.join(sha256(path) for path in artifacts).encode('utf-8')).hexdigest()
    document = {
        'spdxVersion': 'SPDX-2.3',
        'dataLicense': 'CC0-1.0',
        'SPDXID': 'SPDXRef-DOCUMENT',
        'name': f'{metadata["name"]}-{metadata["version"]}-release',
        'documentNamespace': (
            f'https://example.com/spdx/{metadata["name"]}/{metadata["version"]}/{combined_digest}'
        ),
        'creationInfo': {
            'created': dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
            'creators': [
                'Tool: city-intersection-release-metadata/1.0',
                'Organization: city-intersection-project contributors',
            ],
        },
        'packages': packages,
        'relationships': relationships,
    }
    sbom.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate release SBOM and checksum evidence.')
    parser.add_argument('--chart', default='helm/city-intersection-platform')
    parser.add_argument('--dist', default='dist')
    parser.add_argument('--rendered')
    parser.add_argument('--sbom')
    parser.add_argument('--checksums')
    parser.add_argument('--print-chart-version', action='store_true')
    args = parser.parse_args()

    chart = (ROOT / args.chart).resolve()
    metadata = read_chart_metadata(chart)
    if args.print_chart_version:
        print(metadata['version'])
        return 0

    if not args.sbom or not args.checksums:
        parser.error('--sbom and --checksums are required unless --print-chart-version is used')

    dist = (ROOT / args.dist).resolve()
    rendered = (ROOT / args.rendered).resolve() if args.rendered else None
    sbom = (ROOT / args.sbom).resolve()
    checksums = (ROOT / args.checksums).resolve()
    sbom.parent.mkdir(parents=True, exist_ok=True)
    checksums.parent.mkdir(parents=True, exist_ok=True)

    build_sbom(chart, dist, rendered, sbom, checksums)
    artifacts = release_artifacts(dist, rendered, sbom, checksums)
    write_checksums(artifacts, sbom, checksums)
    return 0


if __name__ == '__main__':
    sys.exit(main())
