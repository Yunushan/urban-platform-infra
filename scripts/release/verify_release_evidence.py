#!/usr/bin/env python3
"""Verify public-safe release evidence before publishing or promotion."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - local operator machines may be minimal.
    yaml = None

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RELEASE_ARTIFACTS = {
    "chartPackage": "dist/urban-platform-infra-<version>.tgz",
    "renderedManifest": "dist/rendered.yaml",
    "sbom": "dist/urban-platform-infra.spdx.json",
    "releaseManifest": "dist/release-evidence.json",
    "checksums": "dist/SHA256SUMS",
}
PRIVATE_TEXT_PATTERNS = [
    re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"/(?:srv|opt)/[A-Za-z0-9_.-]+"),
    re.compile(r"/var/lib/urban-platform/private"),
    re.compile(r"BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY"),
    re.compile(r"kind:\s*Config\b.*clusters:", re.IGNORECASE | re.DOTALL),
]


def relative_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def resolve_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def read_chart_metadata(chart: Path) -> dict[str, str]:
    chart_yaml = chart / "Chart.yaml"
    metadata: dict[str, str] = {}
    for raw_line in chart_yaml.read_text(encoding="utf-8").splitlines():
        if ":" not in raw_line or raw_line.startswith((" ", "-")):
            continue
        key, value = raw_line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("\"'")
    for key in ["name", "version", "appVersion"]:
        if not metadata.get(key):
            raise SystemExit(f"Missing {key} in {relative_path(chart_yaml)}")
    return metadata


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_policy(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if yaml is None:
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}


def release_artifact_contract(policy: dict[str, Any], version: str) -> dict[str, Path]:
    artifacts = dict(DEFAULT_RELEASE_ARTIFACTS)
    policy_artifacts = policy.get("policy", {}).get("releaseArtifacts", {})
    if isinstance(policy_artifacts, dict):
        artifacts.update({key: str(value) for key, value in policy_artifacts.items() if value})
    return {
        key: resolve_path(value.replace("<version>", version))
        for key, value in artifacts.items()
    }


def parse_checksums(path: Path) -> dict[Path, str]:
    entries: dict[Path, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            raise ValueError(f"Invalid checksum line {line_number}: {raw_line}")
        artifact = parts[1].lstrip("*").strip()
        entries[resolve_path(artifact)] = parts[0].lower()
    return entries


def scan_public_safe_text(path: Path) -> list[str]:
    if path.suffix in {".tgz", ".tar", ".gz", ".zip"}:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    findings: list[str] = []
    for pattern in PRIVATE_TEXT_PATTERNS:
        if pattern.search(text):
            findings.append(pattern.pattern)
    return findings


def verify_sbom(sbom_path: Path, expected_artifacts: list[Path], errors: list[str], warnings: list[str]) -> None:
    try:
        document = json.loads(sbom_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"SBOM is not valid JSON: {exc}")
        return
    if not str(document.get("spdxVersion", "")).startswith("SPDX-"):
        errors.append("SBOM missing SPDX version.")
    if document.get("SPDXID") != "SPDXRef-DOCUMENT":
        errors.append("SBOM missing SPDXRef-DOCUMENT root id.")
    packages = document.get("packages", [])
    if not isinstance(packages, list) or not packages:
        errors.append("SBOM has no packages.")
        return
    package_file_names = {
        str(package.get("packageFileName", ""))
        for package in packages
        if isinstance(package, dict)
    }
    for artifact in expected_artifacts:
        rel = relative_path(artifact)
        if rel not in package_file_names and artifact.name not in package_file_names:
            warnings.append(f"SBOM does not list artifact `{rel}` as a package file.")


def verify_release_manifest(
    manifest_path: Path,
    metadata: dict[str, str],
    expected_artifacts: dict[str, Path],
    errors: list[str],
) -> None:
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"Release manifest is not valid JSON: {exc}")
        return
    if document.get("schemaVersion") != "urban-platform.release-evidence/v1":
        errors.append("Release manifest missing schemaVersion urban-platform.release-evidence/v1.")
    if document.get("publicSafe") is not True:
        errors.append("Release manifest must declare publicSafe=true.")
    chart = document.get("chart", {})
    if not isinstance(chart, dict):
        errors.append("Release manifest missing chart metadata.")
        return
    for key in ["name", "version", "appVersion"]:
        if chart.get(key) != metadata.get(key):
            errors.append(f"Release manifest chart `{key}` does not match Chart.yaml.")
    artifacts = document.get("artifacts", [])
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("Release manifest has no artifact records.")
        return
    records_by_path = {
        str(record.get("path", "")): record
        for record in artifacts
        if isinstance(record, dict)
    }
    required_manifest_artifacts = {
        "chartPackage": expected_artifacts["chartPackage"],
        "renderedManifest": expected_artifacts["renderedManifest"],
        "spdxSbom": expected_artifacts["sbom"],
    }
    for kind, path in required_manifest_artifacts.items():
        rel = relative_path(path)
        record = records_by_path.get(rel)
        if not record:
            errors.append(f"Release manifest does not list `{rel}`.")
            continue
        if record.get("kind") != kind:
            errors.append(f"Release manifest artifact `{rel}` has kind `{record.get('kind')}`, expected `{kind}`.")
        if path.exists() and record.get("sha256") != sha256(path):
            errors.append(f"Release manifest checksum mismatch for `{rel}`.")


def write_report(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify release checksums, SBOM, tag/version, and public-safe evidence.")
    parser.add_argument("--chart", default="helm/urban-platform-infra")
    parser.add_argument("--policy", default="config/supply-chain-policy.yaml")
    parser.add_argument("--tag", default=os.environ.get("GITHUB_REF_NAME", os.environ.get("CI_COMMIT_TAG", "")))
    parser.add_argument("--report", default="reports/release-evidence-verification.md")
    parser.add_argument("--no-public-safety-scan", action="store_true")
    args = parser.parse_args()

    chart = resolve_path(args.chart)
    policy = load_policy(resolve_path(args.policy))
    metadata = read_chart_metadata(chart)
    version = metadata["version"]
    tag = args.tag.strip()
    expected = release_artifact_contract(policy, version)
    chart_package = expected["chartPackage"]
    rendered = expected["renderedManifest"]
    sbom = expected["sbom"]
    manifest = expected["releaseManifest"]
    checksums = expected["checksums"]

    errors: list[str] = []
    warnings: list[str] = []
    verification_policy = policy.get("policy", {}).get("releaseVerification", {})
    lines = [
        "# Release Evidence Verification",
        "",
        "This report is public-safe. It verifies artifact integrity without reading private inventories, kubeconfigs, or secrets.",
        "",
        f"- Chart: `{relative_path(chart)}`",
        f"- Chart version: `{version}`",
        f"- Release tag: `{tag or 'not provided'}`",
        f"- Policy: `{args.policy}`",
        "",
        "## Required Artifacts",
        "",
        "| Artifact | Path | Status |",
        "|---|---|---|",
    ]

    if verification_policy.get("verifyTagMatchesChartVersion") is True and not tag:
        errors.append("Release tag was not provided, but policy requires tag/chart version verification.")
    if tag:
        normalized_tag = tag[1:] if tag.startswith("v") else tag
        if normalized_tag != version:
            errors.append(f"Release tag `{tag}` does not match chart version `{version}`.")

    required = {
        "chart package": chart_package,
        "rendered manifest": rendered,
        "SPDX SBOM": sbom,
        "release manifest": manifest,
        "checksums": checksums,
    }
    for label, path in required.items():
        status = "ok" if path.exists() else "missing"
        lines.append(f"| `{label}` | `{relative_path(path)}` | `{status}` |")
        if not path.exists():
            errors.append(f"Missing {label}: {relative_path(path)}")

    checksum_entries: dict[Path, str] = {}
    if checksums.exists():
        try:
            checksum_entries = parse_checksums(checksums)
        except ValueError as exc:
            errors.append(str(exc))
    for label, path in required.items():
        if label == "checksums" or not path.exists():
            continue
        expected_digest = checksum_entries.get(path)
        actual_digest = sha256(path)
        if expected_digest is None:
            errors.append(f"Checksum file does not include `{relative_path(path)}`.")
        elif expected_digest != actual_digest:
            errors.append(f"Checksum mismatch for `{relative_path(path)}`.")

    if sbom.exists():
        verify_sbom(sbom, [chart_package, rendered], errors, warnings)
    if manifest.exists():
        verify_release_manifest(manifest, metadata, expected, errors)

    if not args.no_public_safety_scan:
        for label, path in required.items():
            if label == "chart package" or not path.exists():
                continue
            findings = scan_public_safe_text(path)
            if findings:
                errors.append(f"Potential private material pattern in `{relative_path(path)}`.")

    lines.extend(["", "## Result", ""])
    if errors:
        lines.append(f"- Status: `FAIL`")
        for error in errors:
            lines.append(f"- ERROR: {error}")
    else:
        lines.append("- Status: `PASS`")
    for warning in warnings:
        lines.append(f"- WARN: {warning}")

    write_report(resolve_path(args.report), lines)
    print(f"Release evidence verification report written to {args.report}")
    if errors:
        print("Release evidence verification failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
