#!/usr/bin/env python3
"""Fail-closed production evidence and live-cluster readiness gate.

The gate reads private evidence metadata and artifact sizes, but never reads
secrets, kubeconfig contents, image layers, or evidence bodies. It is intended
to run on the operator or a private release runner, not in public CI.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - the private gate requires PyYAML.
    yaml = None

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR / "images") not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR / "images"))

import promotion_plan  # noqa: E402


DIGEST_RE = re.compile(r"^sha256:[A-Fa-f0-9]{64}$")
RELEASE_TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")
REQUIRED_IMAGE_EVIDENCE = (
    "vulnerabilityScan",
    "sbom",
    "signatureOrAttestation",
    "promotionRecord",
)
REQUIRED_DR_ARTIFACTS = (
    "rtoRpo",
    "dependencyMap",
    "criticalityMap",
    "backupReplication",
    "dataReplication",
    "crossZonePlacement",
    "databaseRestore",
    "etcdRestore",
    "namespaceRestore",
    "applicationSmokeTest",
    "runbook",
    "commsPlan",
    "manualWorkaround",
    "supplierContacts",
    "drillEvidence",
    "rtoEvidence",
    "postDrillReview",
)


def mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise ValueError("PyYAML is required by the private production evidence gate")
    if not path.is_file():
        raise ValueError("required evidence manifest is missing")
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError("evidence manifest must contain a mapping")
    return loaded


def resolve_path(value: Any, base: Path) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    path = Path(str(value).strip()).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def nonempty_file(path: Path | None) -> bool:
    return path is not None and path.is_file() and path.stat().st_size > 0


def image_key(image: promotion_plan.ImageObject) -> str:
    return image.path


def merged_images(base_values: Path, public_values: Path, private_values: Path) -> tuple[dict[str, Any], list[promotion_plan.ImageObject]]:
    base = promotion_plan.load_yaml(base_values)
    public = promotion_plan.load_yaml(public_values)
    private = promotion_plan.load_yaml(private_values)
    merged = promotion_plan.merge_values(promotion_plan.merge_values(base, public), private)
    source = "production-values"
    images = promotion_plan.images_from_loaded_yaml(source, merged)
    unique: dict[tuple[str, str], promotion_plan.ImageObject] = {}
    for image in images:
        unique[(image.path, image.reference)] = image
    return merged, sorted(unique.values(), key=lambda item: item.path)


def validate_release(config: dict[str, Any], config_dir: Path) -> tuple[bool, str, Path | None]:
    release = mapping(config.get("release"))
    tag = str(release.get("tag", "")).strip()
    owner = str(release.get("owner", "")).strip()
    private_values = resolve_path(release.get("valuesOverlay"), config_dir)
    if not tag or not RELEASE_TAG_RE.fullmatch(tag):
        return False, "release tag is missing or not a release version", private_values
    if tag.lower() == "latest" or not owner:
        return False, "release owner or immutable release tag is missing", private_values
    if not nonempty_file(private_values):
        return False, "private production values overlay is missing", private_values
    return True, "release identity and private production overlay are present", private_values


def validate_registry(
    config: dict[str, Any],
    config_dir: Path,
    base_values: Path,
    public_values: Path,
    private_values: Path | None,
) -> tuple[bool, str, int]:
    if private_values is None or not nonempty_file(private_values):
        return False, "private production values overlay is unavailable", 0
    registry = mapping(config.get("registry"))
    private_registry = str(registry.get("privateRegistry", "")).strip().rstrip("/")
    if not private_registry or "example.invalid" in private_registry or private_registry.startswith("localhost"):
        return False, "approved private registry is missing", 0
    evidence_root = resolve_path(registry.get("evidenceRoot"), config_dir)
    index_path = resolve_path(registry.get("imageEvidenceIndex"), evidence_root or config_dir)
    if not nonempty_file(index_path):
        return False, "image evidence index is missing", 0
    try:
        merged, images = merged_images(base_values, public_values, private_values)
        index = load_yaml(index_path)
    except (OSError, ValueError, TypeError) as exc:
        return False, str(exc), 0
    global_values = mapping(merged.get("global"))
    configured_registry = str(global_values.get("imageRegistry", "")).strip().rstrip("/")
    if configured_registry != private_registry:
        return False, "private overlay registry does not match the evidence manifest", len(images)
    if not images:
        return False, "production image inventory is empty", 0
    entries = index.get("images")
    if not isinstance(entries, list):
        return False, "image evidence index has no images list", len(images)
    entry_by_path: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not str(entry.get("path", "")).strip():
            return False, "image evidence index contains an invalid image entry", len(images)
        path = str(entry["path"]).strip()
        if path in entry_by_path:
            return False, "image evidence index contains duplicate image paths", len(images)
        entry_by_path[path] = entry
    image_paths = {image_key(image) for image in images}
    if image_paths != set(entry_by_path):
        return False, "image evidence index does not cover the complete production image inventory", len(images)
    for image in images:
        entry = entry_by_path[image_key(image)]
        digest = str(entry.get("digest", "")).strip()
        reference = str(entry.get("reference", "")).strip()
        if not image.digest or not DIGEST_RE.fullmatch(image.digest):
            return False, "a production image is not digest pinned", len(images)
        if digest != image.digest or f"@{digest}" not in reference or not reference.startswith(f"{private_registry}/"):
            return False, "an image evidence digest or private reference does not match the overlay", len(images)
        for evidence_name in REQUIRED_IMAGE_EVIDENCE:
            evidence_path = resolve_path(entry.get(evidence_name), evidence_root or config_dir)
            if not nonempty_file(evidence_path):
                return False, "an image is missing required scan, SBOM, signature, or promotion evidence", len(images)
    return True, "all production images are privately promoted, digest pinned, and evidenced", len(images)


def validate_dr(config: dict[str, Any], config_dir: Path) -> tuple[bool, str, int]:
    disaster_recovery = mapping(config.get("disasterRecovery"))
    evidence_root = resolve_path(disaster_recovery.get("evidenceRoot"), config_dir)
    artifacts = mapping(disaster_recovery.get("artifacts"))
    missing = [name for name in REQUIRED_DR_ARTIFACTS if not nonempty_file(resolve_path(artifacts.get(name), evidence_root or config_dir))]
    if missing:
        return False, "required backup, restore, continuity, or drill evidence is missing", len(REQUIRED_DR_ARTIFACTS) - len(missing)
    return True, "backup, restore, continuity, and post-drill evidence is present", len(REQUIRED_DR_ARTIFACTS)


def kubectl_json(kubectl: str, kubeconfig: Path, namespace: str | None, resource: str) -> tuple[dict[str, Any] | None, str]:
    command = [kubectl, "--kubeconfig", str(kubeconfig)]
    if namespace:
        command.extend(["-n", namespace])
    command.extend(["get", resource, "-o", "json", "--request-timeout=15s"])
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    if completed.returncode != 0:
        return None, "Kubernetes API query failed"
    try:
        loaded = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None, "Kubernetes API returned invalid JSON"
    return loaded if isinstance(loaded, dict) else None, "ok"


def ready_condition(status: dict[str, Any]) -> bool:
    return any(
        isinstance(condition, dict)
        and condition.get("type") == "Ready"
        and str(condition.get("status", "")).lower() == "true"
        for condition in status.get("conditions", [])
    )


def validate_live(config: dict[str, Any], run_live: bool) -> tuple[bool, str]:
    live = mapping(config.get("liveCluster"))
    if not bool(live.get("required", True)):
        return True, "live-cluster evidence is explicitly disabled for this gate"
    if not run_live:
        return False, "live-cluster verification was not requested"
    kubeconfig = resolve_path(live.get("kubeconfig"), ROOT)
    namespace = str(live.get("namespace", "urban-platform")).strip() or "urban-platform"
    if not nonempty_file(kubeconfig):
        return False, "private kubeconfig is missing"
    kubectl = shutil.which("kubectl")
    if not kubectl:
        return False, "kubectl is unavailable on the evidence runner"
    nodes, detail = kubectl_json(kubectl, kubeconfig, None, "nodes")
    if nodes is None:
        return False, detail
    node_items = nodes.get("items", [])
    if not node_items or any(not ready_condition(mapping(item.get("status"))) for item in node_items):
        return False, "one or more Kubernetes nodes are not Ready"
    workloads, detail = kubectl_json(kubectl, kubeconfig, namespace, "deployments,statefulsets")
    if workloads is None:
        return False, detail
    for item in workloads.get("items", []):
        spec = mapping(item.get("spec"))
        status = mapping(item.get("status"))
        replicas = int(spec.get("replicas", 1) or 1)
        ready = int(status.get("readyReplicas", 0) or 0)
        if ready < replicas:
            return False, "one or more production workloads are not Ready"
    pods, detail = kubectl_json(kubectl, kubeconfig, namespace, "pods")
    if pods is None:
        return False, detail
    for item in pods.get("items", []):
        phase = str(mapping(item.get("status")).get("phase", ""))
        if phase not in {"Running", "Succeeded"}:
            return False, "one or more production pods are not Running or Succeeded"
        if phase == "Running" and any(not bool(status.get("ready")) for status in mapping(item.get("status")).get("containerStatuses", [])):
            return False, "one or more running production pods have an unready container"
    clusters, detail = kubectl_json(kubectl, kubeconfig, namespace, "clusters.postgresql.cnpg.io")
    if clusters is None or not clusters.get("items"):
        return False, "CloudNativePG clusters are unavailable"
    for item in clusters.get("items", []):
        spec = mapping(item.get("spec"))
        status = mapping(item.get("status"))
        if int(spec.get("instances", 0) or 0) < 3 or not ready_condition(status):
            return False, "one or more PostgreSQL clusters are not Ready with three instances"
    kafka, detail = kubectl_json(kubectl, kubeconfig, namespace, "kafka.kafka.strimzi.io/kafka")
    if kafka is None:
        return False, detail
    kafka_spec = mapping(kafka.get("spec"))
    kafka_status = mapping(kafka.get("status"))
    expected_kafka = str(live.get("expectedKafkaVersion", "4.3.0")).strip()
    observed_kafka = str(kafka_status.get("kafkaVersion", kafka_spec.get("kafka", {}).get("version", ""))).strip()
    if not ready_condition(kafka_status) or observed_kafka != expected_kafka:
        return False, "Apache Kafka is not Ready at the expected production version"
    pools, detail = kubectl_json(kubectl, kubeconfig, namespace, "kafkanodepools.kafka.strimzi.io")
    if pools is None or not pools.get("items") or any(int(mapping(item.get("spec")).get("replicas", 0) or 0) < 3 for item in pools.get("items", [])):
        return False, "Kafka node pools do not provide three production replicas"
    return True, "nodes, workloads, PostgreSQL, and Apache Kafka passed live checks"


def report(checks: list[tuple[str, int, bool, str]], image_count: int, dr_count: int) -> str:
    score = sum(weight for _, weight, passed, _ in checks if passed)
    result = "PASS" if score == 100 else "FAIL"
    lines = [
        "# Production Evidence Gate",
        "",
        "This report is public-safe. Private paths, kubeconfig contents, credentials, node addresses, and evidence bodies are intentionally omitted.",
        "",
        f"- Result: `{result}`",
        f"- Operational evidence score: `{score}/100`",
        f"- Promoted image entries checked: `{image_count}`",
        f"- DR/BCP artifacts checked: `{dr_count}`",
        "",
        "## Checks",
        "",
        "| Check | Weight | Status | Detail |",
        "|---|---:|---|---|",
    ]
    for name, weight, passed, detail in checks:
        lines.append(f"| {name} | {weight} | {'PASS' if passed else 'FAIL'} | {detail} |")
    lines.extend(
        [
            "",
            "The gate is fail-closed. A repository render or plan does not substitute for private promotion records, restore drills, or live-cluster verification.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate private production evidence and optional live Kubernetes health.")
    parser.add_argument("--config", default="/var/lib/urban-platform/private/production-evidence.yaml")
    parser.add_argument("--base-values", default="helm/urban-platform-infra/values.yaml")
    parser.add_argument("--values", default="helm/urban-platform-infra/values-production.yaml")
    parser.add_argument("--output", default="reports/production-evidence-gate.md")
    parser.add_argument("--live", action="store_true", help="Run read-only kubectl checks described by the private manifest.")
    parser.add_argument("--redact-sensitive", action="store_true", help="Accepted for compatibility; sensitive output is always redacted.")
    args = parser.parse_args(argv)

    config_path = resolve_path(args.config, ROOT)
    base_values = resolve_path(args.base_values, ROOT)
    public_values = resolve_path(args.values, ROOT)
    output = resolve_path(args.output, ROOT)
    if output is None:
        raise SystemExit("--output must not be empty")
    output.parent.mkdir(parents=True, exist_ok=True)

    checks: list[tuple[str, int, bool, str]] = []
    image_count = 0
    dr_count = 0
    config: dict[str, Any] = {}
    if config_path is None or not config_path.is_file():
        checks = [
            ("Evidence manifest and release identity", 15, False, "private evidence manifest is unavailable"),
            ("Private image promotion evidence", 25, False, "not assessed because the evidence manifest is unavailable"),
            ("Disaster recovery and restore evidence", 25, False, "not assessed because the evidence manifest is unavailable"),
            ("Live cluster verification", 25, False, "not assessed because the evidence manifest is unavailable"),
            ("Evidence contract integrity", 10, False, "not assessed because the evidence manifest is unavailable"),
        ]
    else:
        try:
            config = load_yaml(config_path)
            config_valid = int(config.get("version", 0) or 0) == 1
            checks.append(("Evidence manifest and release identity", 15, config_valid, "versioned private evidence manifest is present" if config_valid else "evidence manifest version is unsupported"))
            release_ok, release_detail, private_values = validate_release(config, config_path.parent)
            checks[-1] = ("Evidence manifest and release identity", 15, config_valid and release_ok, release_detail if config_valid else "evidence manifest version is unsupported")
            if base_values is None or public_values is None or not nonempty_file(base_values) or not nonempty_file(public_values):
                image_ok, image_detail, image_count = False, "public production values inputs are unavailable", 0
            else:
                image_ok, image_detail, image_count = validate_registry(config, config_path.parent, base_values, public_values, private_values)
            checks.append(("Private image promotion evidence", 25, image_ok, image_detail))
            dr_ok, dr_detail, dr_count = validate_dr(config, config_path.parent)
            checks.append(("Disaster recovery and restore evidence", 25, dr_ok, dr_detail))
            live_ok, live_detail = validate_live(config, args.live)
            checks.append(("Live cluster verification", 25, live_ok, live_detail))
            checks.append(("Evidence contract integrity", 10, config_valid and bool(config.get("release")) and bool(config.get("registry")) and bool(config.get("disasterRecovery")), "required evidence sections are present" if config_valid else "required evidence sections are incomplete"))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            checks = [
                ("Evidence manifest and release identity", 15, False, "private evidence manifest could not be loaded"),
                ("Private image promotion evidence", 25, False, "not assessed after manifest load failure"),
                ("Disaster recovery and restore evidence", 25, False, "not assessed after manifest load failure"),
                ("Live cluster verification", 25, False, "not assessed after manifest load failure"),
                ("Evidence contract integrity", 10, False, "evidence manifest is invalid"),
            ]
            _ = exc
    output.write_text(report(checks, image_count, dr_count), encoding="utf-8")
    score = sum(weight for _, weight, passed, _ in checks if passed)
    print(f"Production evidence gate report written: {output}")
    print(f"Operational evidence score: {score}/100")
    return 0 if score == 100 else 1


if __name__ == "__main__":
    raise SystemExit(main())
