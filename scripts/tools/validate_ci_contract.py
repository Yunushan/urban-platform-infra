#!/usr/bin/env python3
"""Validate the public CI workflow contract without external dependencies."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GITHUB_CI = ROOT / ".github/workflows/ci.yml"
GITLAB_CI = ROOT / ".gitlab-ci.yml"
VERSION_UPDATE_WORKFLOW = ROOT / ".github/workflows/version-update.yml"


@dataclass(frozen=True)
class Finding:
    status: str
    scope: str
    detail: str


STATIC_LANES = {
    "ansible-2.14-py311": {
        "python-version: '3.11'",
        "requirements-file: requirements-ci.txt",
        "ansible-requirements-file: ansible/requirements.yml",
    },
    "ansible-2.20-py312": {
        "python-version: '3.12'",
        "requirements-file: requirements-ci-modern.txt",
        "ansible-requirements-file: ansible/requirements-modern.yml",
    },
    "ansible-2.20-py313": {
        "python-version: '3.13'",
        "requirements-file: requirements-ci-modern.txt",
        "ansible-requirements-file: ansible/requirements-modern.yml",
    },
    "ansible-2.20-py314": {
        "python-version: '3.14'",
        "requirements-file: requirements-ci-modern.txt",
        "ansible-requirements-file: ansible/requirements-modern.yml",
    },
}

VALIDATE_LANES = {
    "python-3.11": {
        "python-version: '3.11'",
        "requirements-file: requirements-ci.txt",
    },
    "python-3.12": {
        "python-version: '3.12'",
        "requirements-file: requirements-ci-modern.txt",
    },
    "python-3.13": {
        "python-version: '3.13'",
        "requirements-file: requirements-ci-modern.txt",
    },
    "python-3.14": {
        "python-version: '3.14'",
        "requirements-file: requirements-ci-modern.txt",
    },
}

GITHUB_REQUIRED_TOKENS = {
    "permissions:": "Workflow must declare explicit permissions.",
    "contents: read": "Workflow permissions must stay least-privilege by default.",
    "fail-fast: false": "Matrix jobs must keep running after one lane fails.",
    "cache: pip": "Python dependency caching must stay enabled.",
    "cache-dependency-path: ${{ matrix.requirements-file }}": "Matrix lanes must cache by their selected requirements file.",
    "ansible-galaxy collection install -r \"${{ matrix.ansible-requirements-file }}\"": "Static lanes must install their matching Ansible collection pins.",
    "python3 scripts/tools/validate_ci_contract.py": "Validate jobs must run the CI contract gate before the broader validator.",
    "python3 scripts/validate.py": "Validate jobs must run repository validation.",
    "python3 scripts/images/validate-images.py": "Validate jobs must run image policy validation.",
    "python3 scripts/version_policy.py check --config config/version-policy.yaml": "Validate jobs must enforce the approval-only version policy.",
    "actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294": "Pull requests must keep blocking dependency review coverage.",
    "python3 scripts/validate_production_profile.py": "CI must validate the production profile contract.",
    "python3 scripts/production_readiness_score.py": "CI must enforce the repository production readiness score.",
    "python3 tests/policy/kafka_clickhouse_readiness_test.py": "CI must exercise Kafka-to-ClickHouse readiness scoring without live traffic.",
    "python3 tests/policy/kafka_clickhouse_reconcile_test.py": "CI must exercise fail-closed Kafka-to-ClickHouse reconciliation without a live cluster.",
    "--api-versions kafka.strimzi.io/v1/Kafka": "Production rendering must model the Strimzi Kafka CRD API.",
    "--api-versions kafka.strimzi.io/v1/KafkaConnect": "Production rendering must model the Strimzi Kafka Connect CRD API.",
    "--api-versions kafka.strimzi.io/v1/KafkaConnector": "Production rendering must model the Strimzi KafkaConnector CRD API.",
    "--api-versions kafka.strimzi.io/v1/KafkaTopic": "Production rendering must model the Strimzi managed-topic CRD API.",
    "--api-versions kafka.strimzi.io/v1/KafkaUser": "Production rendering must model the Strimzi user and ACL CRD API.",
    "--api-versions monitoring.coreos.com/v1/PodMonitor": "Production rendering must model Prometheus discovery for Kafka and Connect.",
    "exit-code: '1'": "High and critical filesystem findings must fail CI.",
    "needs: static": "Downstream jobs must depend on static checks.",
    "needs: validate": "Render must wait for validate checks.",
    "aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25": "Security scan action must stay pinned to a full commit SHA.",
}

GITLAB_REQUIRED_TOKENS = {
    "pip install -r requirements-ci-modern.txt": "GitLab validation must use the modern pinned requirements file.",
    "python3 scripts/tools/validate_ci_contract.py": "GitLab validation must run the CI contract gate.",
    "python3 scripts/validate.py": "GitLab validation must run repository validation.",
    "python3 scripts/images/validate-images.py": "GitLab validation must run image policy validation.",
    "python3 scripts/version_policy.py check --config config/version-policy.yaml": "GitLab validation must enforce the approval-only version policy.",
    "python3 tests/policy/kafka_clickhouse_reconcile_test.py": "GitLab validation must exercise fail-closed Kafka-to-ClickHouse reconciliation.",
    "alpine/helm:3.19.0": "GitLab render and release jobs must use a pinned Helm image.",
    "aquasec/trivy:0.70.0": "GitLab security job must use a pinned Trivy image.",
}

VERSION_UPDATE_REQUIRED_TOKENS = {
    "workflow_dispatch:": "Version updates must require an explicit manual workflow request.",
    "python3 scripts/version_policy.py check --config config/version-policy.yaml": "Version workflow must validate the committed policy.",
    "python3 scripts/version_policy.py request": "Version workflow must generate a request instead of deploying directly.",
    "contents: read": "Version workflow must not receive repository write access.",
}


def read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def lane_block(text: str, lane: str) -> str:
    pattern = re.compile(
        rf"(?ms)^\s*-\s+lane:\s+{re.escape(lane)}\s*$"
        r"(?P<body>.*?)(?=^\s*-\s+lane:|\n\s*steps:|\n\s*[a-zA-Z_-]+:\s*$|\Z)"
    )
    match = pattern.search(text)
    if not match:
        return ""
    return match.group(0)


def check_tokens(scope: str, text: str, tokens: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []
    for token, detail in sorted(tokens.items()):
        if token not in text:
            findings.append(Finding("ERROR", scope, f"{detail} Missing token: `{token}`"))
        else:
            findings.append(Finding("OK", scope, detail))
    return findings


def check_lanes(scope: str, text: str, lanes: dict[str, set[str]]) -> list[Finding]:
    findings: list[Finding] = []
    for lane, required_tokens in lanes.items():
        block = lane_block(text, lane)
        if not block:
            findings.append(Finding("ERROR", scope, f"Missing matrix lane: `{lane}`"))
            continue
        for token in sorted(required_tokens):
            if token not in block:
                findings.append(Finding("ERROR", scope, f"Lane `{lane}` missing token: `{token}`"))
            else:
                findings.append(Finding("OK", scope, f"Lane `{lane}` contains `{token}`"))
    return findings


def check_action_refs(text: str) -> list[Finding]:
    findings: list[Finding] = []
    action_refs = re.findall(r"uses:\s+([^@\s]+)@([^\s#]+)", text)
    for action, ref in action_refs:
        if ref in {"main", "master"}:
            findings.append(Finding("ERROR", "GitHub Actions", f"Action `{action}` uses floating ref `{ref}`."))
        elif not re.fullmatch(r"[0-9a-f]{40}", ref):
            findings.append(Finding("ERROR", "GitHub Actions", f"Action `{action}` must use a full commit SHA, got `{ref}`."))
        else:
            findings.append(Finding("OK", "GitHub Actions", f"Action `{action}` is pinned to commit `{ref}`."))
    return findings


def collect_findings() -> list[Finding]:
    github_text = read_text(GITHUB_CI)
    gitlab_text = read_text(GITLAB_CI)
    version_update_text = read_text(VERSION_UPDATE_WORKFLOW)
    findings: list[Finding] = []
    findings.extend(check_tokens("GitHub CI", github_text, GITHUB_REQUIRED_TOKENS))
    findings.extend(check_lanes("GitHub static matrix", github_text, STATIC_LANES))
    findings.extend(check_lanes("GitHub validate matrix", github_text, VALIDATE_LANES))
    findings.extend(check_action_refs(github_text))
    findings.extend(check_tokens("Version update workflow", version_update_text, VERSION_UPDATE_REQUIRED_TOKENS))
    findings.extend(check_action_refs(version_update_text))
    if "helm upgrade" in version_update_text or "kubectl apply" in version_update_text:
        findings.append(Finding("ERROR", "Version update workflow", "Version request workflow must not deploy to a cluster."))
    else:
        findings.append(Finding("OK", "Version update workflow", "Manual workflow only generates review evidence."))
    findings.extend(check_tokens("GitLab CI", gitlab_text, GITLAB_REQUIRED_TOKENS))
    if "pip install pyyaml" in gitlab_text.lower():
        findings.append(
            Finding(
                "ERROR",
                "GitLab CI",
                "GitLab CI must not install ad hoc PyYAML only; use pinned requirements instead.",
            )
        )
    return findings


def render_markdown(findings: list[Finding]) -> str:
    lines = [
        "# CI Contract Report",
        "",
        "This report is public-safe. It validates workflow structure, lane pins, and required gate commands only.",
        "",
        "| Status | Scope | Detail |",
        "|---|---|---|",
    ]
    for finding in findings:
        detail = finding.detail.replace("|", "\\|")
        lines.append(f"| `{finding.status}` | {finding.scope} | {detail} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the CI workflow contract.")
    parser.add_argument("--report", default="", help="Optional Markdown report path.")
    args = parser.parse_args(argv)

    findings = collect_findings()
    for finding in findings:
        if finding.status != "OK":
            print(f"{finding.status}: {finding.scope}: {finding.detail}")

    if args.report:
        report = Path(args.report)
        if not report.is_absolute():
            report = ROOT / report
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(render_markdown(findings), encoding="utf-8")
        print(f"Wrote CI contract report: {report}")

    errors = [finding for finding in findings if finding.status == "ERROR"]
    if errors:
        print(f"CI contract failed with {len(errors)} error(s).")
        return 1
    print("CI contract checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
