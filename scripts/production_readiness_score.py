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
            "kafka.strimzi.io/v1/KafkaTopic",
            "--api-versions",
            "kafka.strimzi.io/v1/KafkaUser",
            "--api-versions",
            "kafka.strimzi.io/v1/KafkaConnect",
            "--api-versions",
            "kafka.strimzi.io/v1/KafkaConnector",
            "--api-versions",
            "monitoring.coreos.com/v1/PodMonitor",
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
        "Taskfile.yml",
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
        "helm/urban-platform-infra/values-kafka-clickhouse-private.example.yaml",
        ".github/workflows/ci.yml",
        ".github/workflows/load-test.yml",
        ".github/workflows/release.yml",
        ".github/workflows/version-update.yml",
        ".github/actionlint.yaml",
        "config/image-policy.yaml",
        "config/version-policy.yaml",
        "config/production-evidence.example.yaml",
        "config/production-evidence-trust.example.yaml",
        "scripts/production_evidence_gate.py",
        "scripts/validate_production_private_overlay.py",
        "scripts/kafka_clickhouse_readiness.py",
        "scripts/kafka_clickhouse_reconcile.py",
        "tests/policy/production_render.py",
        "helm/urban-platform-infra/templates/release-identity.yaml",
        "tests/policy/production_evidence_gate_test.py",
        "tests/policy/production_private_overlay_test.py",
        "tests/policy/tool_inventory_test.py",
        "tests/policy/version_policy_test.py",
        "tests/policy/release_evidence_test.py",
        "tests/policy/kafka_clickhouse_readiness_test.py",
        "tests/policy/kafka_clickhouse_reconcile_test.py",
    ]
    missing = [path for path in required if not (ROOT / path).is_file()]
    if missing:
        return Check("Operations and release evidence coverage", 10, False, f"missing {', '.join(missing)}")
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    if (
        "scripts/validate_production_profile.py" not in workflow
        or "tests/policy/production_render.py" not in workflow
        or "values-production.yaml" not in workflow
        or "python3 scripts/tools/validate_ci_contract.py" not in workflow
        or "python3 scripts/validate.py" not in workflow
    ):
        return Check("Operations and release evidence coverage", 10, False, "release workflow does not enforce source and production contracts")
    evidence_example = (ROOT / "config/production-evidence.example.yaml").read_text(encoding="utf-8")
    for token in (
        "version: 4",
        "attestation:",
        "expiresAt:",
        "sourceRevision:",
        "deploymentId:",
        "valuesOverlaySha256:",
        "imageEvidenceIndexSha256:",
        "maximumEvidenceAgeDays:",
        "required: true",
        "minimumReadyNodes: 3",
        "clusterUid:",
        "expectedPodSecurityVersion:",
        "expectedPodDisruptionBudgets:",
        "expectedAutoscalers:",
        "ingressProbe:",
        "httpsUrl:",
        "httpUrl:",
        "requireHttpRedirect: true",
        "tlsVerify: true",
    ):
        if token not in evidence_example:
            return Check("Operations and release evidence coverage", 10, False, "private evidence example does not enforce the signed version 4 live contract")
    trust_example = (ROOT / "config/production-evidence-trust.example.yaml").read_text(encoding="utf-8")
    for token in ("version: 2", "provider: cosign-key-bundle", "publicKey:", "bundle:", "trustedApprovers:"):
        if token not in trust_example:
            return Check("Operations and release evidence coverage", 10, False, "operator trust example does not enforce standardized Sigstore bundle verification")
    tooling_contract = (ROOT / "config/tooling.yaml").read_text(encoding="utf-8")
    for token in ("production-evidence:", "- cosign", "minimumVersion: 3.1.3"):
        if token not in tooling_contract:
            return Check("Operations and release evidence coverage", 10, False, "production evidence tooling does not require patched Cosign")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    if "TOOL_INVENTORY_SCOPE=production-evidence" not in makefile or "production-private-preflight:" not in makefile or "validate_production_private_overlay.py" not in makefile:
        return Check("Operations and release evidence coverage", 10, False, "production evidence target does not verify its mandatory toolchain")
    taskfile = (ROOT / "Taskfile.yml").read_text(encoding="utf-8")
    if (
        "make deploy" not in taskfile
        or "CONFIRM_PROD" not in taskfile
        or "DEPLOY_PRIVATE_VALUES" not in taskfile
        or "pod-security.kubernetes.io/enforce-version=latest" in taskfile
        or "dist/production-rendered.yaml" not in taskfile
        or "python3 tests/policy/production_render.py dist/production-rendered.yaml" not in taskfile
        or "--production-rendered dist/production-rendered.yaml" not in taskfile
        or "scripts/release/verify_release_evidence.py" not in taskfile
    ):
        return Check("Operations and release evidence coverage", 10, False, "Taskfile deploy or release evidence does not use the guarded production path")
    for test in (
        "tests/policy/production_evidence_gate_test.py",
        "tests/policy/production_private_overlay_test.py",
        "tests/policy/tool_inventory_test.py",
        "tests/policy/kafka_clickhouse_readiness_test.py",
        "tests/policy/kafka_clickhouse_reconcile_test.py",
        "tests/policy/version_policy_test.py",
        "tests/policy/release_evidence_test.py",
    ):
        passed, detail = command_result([PYTHON, test])
        if not passed:
            return Check("Operations and release evidence coverage", 10, False, detail)
    return Check("Operations and release evidence coverage", 10, True, "runbooks and fail-closed production evidence gates passed")


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
