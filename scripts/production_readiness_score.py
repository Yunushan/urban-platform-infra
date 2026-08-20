#!/usr/bin/env python3
"""Score repository-level production readiness without pretending to test a live cluster."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
CHART = ROOT / "helm/urban-platform-infra"
BASE_VALUES = CHART / "values.yaml"
PRODUCTION_VALUES = CHART / "values-production.yaml"


@dataclass(frozen=True)
class Check:
    name: str
    weight: int
    passed: bool
    detail: str


def command_result(command: list[str], *, cwd: Path = ROOT) -> tuple[bool, str]:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    output = (completed.stdout + completed.stderr).strip().splitlines()
    detail = output[-1] if output else f"exit code {completed.returncode}"
    return completed.returncode == 0, detail


def run_check(name: str, weight: int, command: list[str]) -> Check:
    passed, detail = command_result(command)
    return Check(name, weight, passed, detail)


def helm_render_check() -> Check:
    helm = shutil.which("helm")
    if not helm:
        return Check("Strict Helm render and workload policy", 20, False, "helm is not installed")
    with tempfile.TemporaryDirectory(prefix="urban-production-") as directory:
        rendered = Path(directory) / "production-rendered.yaml"
        render_command = [
            helm,
            "template",
            "urban-platform-infra",
            str(CHART),
            "--namespace",
            "urban-platform",
            "-f",
            str(BASE_VALUES),
            "-f",
            str(PRODUCTION_VALUES),
            "--api-versions",
            "kafka.strimzi.io/v1/Kafka",
            "--api-versions",
            "kafka.strimzi.io/v1/KafkaNodePool",
            "--api-versions",
            "cert-manager.io/v1/Certificate",
            "--api-versions",
            "cert-manager.io/v1/ClusterIssuer",
        ]
        with rendered.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(render_command, cwd=ROOT, stdout=handle, stderr=subprocess.PIPE, text=True, check=False)
        if completed.returncode != 0:
            detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "helm template failed"
            return Check("Strict Helm render and workload policy", 20, False, detail)
        passed, detail = command_result([PYTHON, "tests/policy/basic_policy.py", str(rendered)])
        if not passed:
            return Check("Strict Helm render and workload policy", 20, False, detail)
        rendered_passed, rendered_detail = command_result([PYTHON, "tests/policy/production_render.py", str(rendered)])
        if not rendered_passed:
            return Check("Strict Helm render and workload policy", 20, False, rendered_detail)
        return Check("Strict Helm render and workload policy", 20, True, rendered_detail)


def documentation_check() -> Check:
    required = [
        "docs/ci-validation.md",
        "docs/backup-restore.md",
        "docs/disaster-recovery.md",
        "docs/release-runbook.md",
        "docs/kafka-profiles.md",
        "docs/database-topologies.md",
        "docs/tool-inventory.md",
        "docs/load-testing.md",
        "docs/version-management.md",
        "docs/production-readiness.md",
        ".github/workflows/ci.yml",
        ".github/workflows/release.yml",
        ".github/workflows/version-update.yml",
        "config/image-policy.yaml",
        "config/version-policy.yaml",
        "config/production-evidence.example.yaml",
        "scripts/production_evidence_gate.py",
        "tests/policy/production_render.py",
        "tests/policy/production_evidence_gate_test.py",
    ]
    missing = [path for path in required if not (ROOT / path).is_file()]
    if missing:
        return Check("Operations and release evidence coverage", 10, False, f"missing {', '.join(missing)}")
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    if (
        "scripts/validate_production_profile.py" not in workflow
        or "tests/policy/production_render.py" not in workflow
        or "values-production.yaml" not in workflow
    ):
        return Check("Operations and release evidence coverage", 10, False, "release workflow does not enforce the production contract")
    return Check("Operations and release evidence coverage", 10, True, "runbooks and production release gates are present")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score repository-level production readiness.")
    parser.add_argument("--minimum", type=int, default=100, help="Required score; defaults to 100.")
    args = parser.parse_args(argv)

    checks = [
        run_check("Production profile contract", 20, [PYTHON, "scripts/validate_production_profile.py"]),
        helm_render_check(),
        run_check("Repository validation", 15, [PYTHON, "scripts/validate.py"]),
        run_check("CI supply-chain contract", 15, [PYTHON, "scripts/tools/validate_ci_contract.py"]),
        run_check("Approved image policy", 10, [PYTHON, "scripts/images/validate-images.py"]),
        run_check(
            "Private-data audit",
            10,
            [PYTHON, "scripts/tools/private_data_audit.py", "--report", "reports/production-readiness-private-data.md"],
        ),
        documentation_check(),
    ]
    score = sum(check.weight for check in checks if check.passed)
    print(f"Repository production readiness score: {score}/100")
    print("Scope: repository contracts, rendered manifests, CI gates, and release controls; live-cluster evidence is separate.")
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"[{status}] {check.name} ({check.weight} points): {check.detail}")
    return 0 if score >= args.minimum else 1


if __name__ == "__main__":
    raise SystemExit(main())
