#!/usr/bin/env python3
"""Generate a public-safe cluster upgrade and version-skew guardrail plan."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - keeps the planner usable on lean operator hosts.
    yaml = None


ROOT = Path(__file__).resolve().parents[1]


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"", "''", '""'}:
        return ""
    if value in {"[]", "[ ]"}:
        return []
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lower() in {"null", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value


def next_child_is_list(lines: list[str], index: int, indent: int) -> bool:
    for raw_line in lines[index + 1:]:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        child_indent = len(raw_line) - len(raw_line.lstrip(" "))
        if child_indent < indent:
            return False
        return raw_line.lstrip().startswith("- ")
    return False


def load_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    lines = text.splitlines()
    for index, raw_line in enumerate(lines):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        line = raw_line.split(" #", 1)[0].rstrip()
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        is_list_item = stripped.startswith("- ")
        while stack and (indent < stack[-1][0] or (indent == stack[-1][0] and not (is_list_item and isinstance(stack[-1][1], list)))):
            stack.pop()
        parent = stack[-1][1]
        if is_list_item:
            if not isinstance(parent, list):
                continue
            item = stripped[2:].strip()
            parent.append(parse_scalar(item))
            continue
        if ":" not in stripped or not isinstance(parent, dict):
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip().strip("'\"")
        raw_value = raw_value.strip()
        if raw_value == "":
            child: Any = [] if next_child_is_list(lines, index, indent) else {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = parse_scalar(raw_value)
    return root


def load_yaml_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        loaded = yaml.safe_load(text) or {}
        if not isinstance(loaded, dict):
            raise SystemExit(f"{path} must contain a mapping.")
        return loaded
    return load_simple_yaml(text)


def quote_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if text == "" or text.lower() in {"true", "false", "null"} or any(char in text for char in ":#{}[],&*?|-<>=!%@`"):
        return "'" + text.replace("'", "''") + "'"
    return text


def dump_yaml(data: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(data, dict):
        lines: list[str] = []
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(dump_yaml(value, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {quote_scalar(value)}")
        return lines
    if isinstance(data, list):
        lines = []
        for item in data:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(dump_yaml(item, indent + 2))
            else:
                lines.append(f"{prefix}- {quote_scalar(item)}")
        return lines
    return [f"{prefix}{quote_scalar(data)}"]


def as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"true", "yes", "on", "1"}
    return default


def bool_text(value: Any) -> str:
    return "true" if bool_value(value) else "false"


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (ROOT / path).resolve()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def display_private(value: str, replacement: str, redact: bool) -> str:
    if not value:
        return "-"
    if value in {"-", "none"}:
        return value
    return replacement if redact else value


def display_config(value: Any) -> str:
    if isinstance(value, bool):
        return bool_text(value)
    return str(value)


def kubernetes_minor(version: str) -> int | None:
    match = re.match(r"^v?1\.(\d+)(?:\.\d+)?(?:[+-].*)?$", version.strip())
    return int(match.group(1)) if match else None


def rke2_format_valid(version: str) -> bool:
    if not version:
        return False
    return re.match(r"^v\d+\.\d+\.\d+\+rke2r\d+$", version.strip()) is not None


def profiles(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("profiles", {})
    if not isinstance(value, dict):
        raise SystemExit("Cluster upgrade config must contain a profiles mapping.")
    return value


def profile_config(config: dict[str, Any], requested_profile: str) -> tuple[str, dict[str, Any]]:
    profile_name = requested_profile or str(config.get("defaultProfile", "disabled"))
    all_profiles = profiles(config)
    if profile_name not in all_profiles:
        choices = ", ".join(sorted(all_profiles))
        raise SystemExit(f"Unknown cluster upgrade profile `{profile_name}`. Available profiles: {choices}")
    profile = all_profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Cluster upgrade profile `{profile_name}` must be a mapping.")
    return profile_name, profile


def effective_versions(args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, str]:
    versions = as_mapping(profile.get("versions"))
    return {
        "currentKubernetes": args.current_kubernetes or str(versions.get("currentKubernetes", "")),
        "targetKubernetes": args.target_kubernetes or str(versions.get("targetKubernetes", "")),
        "currentRke2": args.current_rke2 or str(versions.get("currentRke2", "")),
        "targetRke2": args.target_rke2 or str(versions.get("targetRke2", "")),
    }


def profile_findings(args: argparse.Namespace, profile_name: str, profile: dict[str, Any], versions: dict[str, str]) -> list[str]:
    findings: list[str] = []
    gates = as_mapping(profile.get("gates"))
    evidence = as_mapping(profile.get("evidence"))
    profile_versions = as_mapping(profile.get("versions"))
    max_minor_skew = int(profile_versions.get("maxMinorSkew", 0) or 0)
    current_minor = kubernetes_minor(versions["currentKubernetes"])
    target_minor = kubernetes_minor(versions["targetKubernetes"])

    if not bool_value(profile.get("enabled")):
        findings.append(f"INFO: Profile `{profile_name}` is plan-only; committed values keep cluster upgrade automation disabled.")
    if args.execute:
        findings.append("WARN: Execute was requested; this planner still does not drain nodes, restart RKE2, patch inventories, or mutate the cluster.")
    if bool_value(gates.get("requirePinnedVersion")) and not versions["targetRke2"]:
        findings.append("WARN: Target RKE2 version must be pinned before upgrade approval.")
    if versions["targetRke2"] and not rke2_format_valid(versions["targetRke2"]):
        findings.append("WARN: Target RKE2 version should use `vMAJOR.MINOR.PATCH+rke2rN` format.")
    if bool_value(gates.get("requireSupportedSkew")) and (current_minor is None or target_minor is None):
        findings.append("WARN: Current and target Kubernetes versions are required for version skew review.")
    if current_minor is not None and target_minor is not None and abs(target_minor - current_minor) > max_minor_skew:
        findings.append(f"ERROR: Kubernetes version skew exceeds the configured {max_minor_skew} minor-version step.")
    if bool_value(gates.get("requireEtcdSnapshot")) and not args.etcd_snapshot:
        findings.append("WARN: RKE2 etcd snapshot evidence is required before upgrade.")
    if bool_value(gates.get("requireBackupRestore")) and not args.backup_restore_evidence:
        findings.append("WARN: Backup and restore evidence is required before upgrade.")
    if bool_value(gates.get("requireMaintenanceWindow")) and not args.maintenance_window:
        findings.append("WARN: Maintenance window or change freeze exception is required before upgrade.")
    if bool_value(gates.get("requireCapacityHeadroom")) and not args.capacity_evidence:
        findings.append("WARN: Capacity headroom evidence is required before upgrade.")
    if bool_value(gates.get("requireNodeHealth")) and not args.node_health_evidence:
        findings.append("WARN: Node health evidence is required before upgrade.")
    if bool_value(gates.get("requireRollbackPlan")) and not args.rollback_plan:
        findings.append("WARN: Rollback plan is required before upgrade.")
    if bool_value(gates.get("requireAddOnCompatibility")) and not args.addon_compatibility:
        findings.append("WARN: Add-on compatibility review is required before upgrade.")
    if bool_value(gates.get("requirePostUpgradeSmokeTest")) and not args.smoke_test_plan:
        findings.append("WARN: Post-upgrade smoke-test plan is required before upgrade.")
    if bool_value(evidence.get("requireClusterDoctor")) and not args.cluster_doctor:
        findings.append("WARN: Cluster doctor report is required before upgrade.")
    if bool_value(evidence.get("requireInventoryReview")) and not args.inventory_review:
        findings.append("WARN: Private inventory review evidence is required before upgrade.")
    if bool_value(evidence.get("requireReleaseNotesReview")) and not args.release_notes_review:
        findings.append("WARN: RKE2 and Kubernetes release notes review is required before upgrade.")
    if bool_value(evidence.get("requireOwnerApproval")) and not args.owner_approval:
        findings.append("WARN: Owner approval evidence is required before upgrade.")
    if profile_name == "production-upgrade" and bool_value(as_mapping(profile.get("orchestration")).get("enabled")):
        findings.append("ERROR: Production upgrade profile must remain plan-only in committed config.")
    return findings or ["OK: Cluster upgrade and version skew settings are internally consistent."]


def result_from_findings(findings: list[str]) -> str:
    if any(item.startswith("ERROR:") for item in findings):
        return "FAIL"
    if any(item.startswith("WARN:") for item in findings):
        return "WARN"
    return "PASS"


def write_overrides(path: Path, profile_name: str, profile: dict[str, Any], versions: dict[str, str]) -> None:
    orchestration = as_mapping(profile.get("orchestration"))
    profile_versions = as_mapping(profile.get("versions"))
    gates = as_mapping(profile.get("gates"))
    evidence = as_mapping(profile.get("evidence"))
    values = {
        "clusterUpgrade": {
            "enabled": False,
            "profile": profile_name,
            "mode": str(profile.get("mode", "baseline")),
            "engine": str(profile.get("engine", "rke2")),
            "orchestration": {
                "enabled": False,
                "strategy": str(orchestration.get("strategy", "none")),
                "drainNodes": False,
                "restartServices": False,
            },
            "versions": {
                "currentKubernetes": versions["currentKubernetes"],
                "targetKubernetes": versions["targetKubernetes"],
                "currentRke2": versions["currentRke2"],
                "targetRke2": versions["targetRke2"],
                "maxMinorSkew": int(profile_versions.get("maxMinorSkew", 0) or 0),
            },
            "gates": {
                "requirePinnedVersion": bool_value(gates.get("requirePinnedVersion")),
                "requireSupportedSkew": bool_value(gates.get("requireSupportedSkew")),
                "requireEtcdSnapshot": bool_value(gates.get("requireEtcdSnapshot")),
                "requireBackupRestore": bool_value(gates.get("requireBackupRestore")),
                "requireMaintenanceWindow": bool_value(gates.get("requireMaintenanceWindow")),
                "requireCapacityHeadroom": bool_value(gates.get("requireCapacityHeadroom")),
                "requireNodeHealth": bool_value(gates.get("requireNodeHealth")),
                "requireRollbackPlan": bool_value(gates.get("requireRollbackPlan")),
                "requireAddOnCompatibility": bool_value(gates.get("requireAddOnCompatibility")),
                "requirePostUpgradeSmokeTest": bool_value(gates.get("requirePostUpgradeSmokeTest")),
            },
            "evidence": {
                "requireClusterDoctor": bool_value(evidence.get("requireClusterDoctor")),
                "requireInventoryReview": bool_value(evidence.get("requireInventoryReview")),
                "requireReleaseNotesReview": bool_value(evidence.get("requireReleaseNotesReview")),
                "requireOwnerApproval": bool_value(evidence.get("requireOwnerApproval")),
            },
            "reports": {
                "plan": "reports/cluster-upgrade-plan.md",
                "overrides": "reports/cluster-upgrade-values.yaml",
            },
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(["# Generated by scripts/cluster_upgrade_plan.py. Review before use.", *dump_yaml(values), ""]), encoding="utf-8")


def generate_report(
    args: argparse.Namespace,
    config: dict[str, Any],
    profile_name: str,
    profile: dict[str, Any],
    versions: dict[str, str],
    output_path: Path,
    overrides_path: Path,
) -> str:
    findings = profile_findings(args, profile_name, profile, versions)
    result = result_from_findings(findings)
    orchestration = as_mapping(profile.get("orchestration"))
    profile_versions = as_mapping(profile.get("versions"))
    gates = as_mapping(profile.get("gates"))
    evidence = as_mapping(profile.get("evidence"))
    current_minor = kubernetes_minor(versions["currentKubernetes"])
    target_minor = kubernetes_minor(versions["targetKubernetes"])
    skew = "-" if current_minor is None or target_minor is None else str(target_minor - current_minor)
    lines = [
        "# Cluster Upgrade And Version-Skew Guardrail Plan",
        "",
        "This report is public-safe. It reviews Kubernetes and RKE2 version skew, etcd snapshot readiness, add-on compatibility, rollback plan, maintenance window, and post-upgrade smoke-test gates without printing private node names, kubeconfigs, API endpoints, tickets, approvers, or owner records.",
        "",
        f"- Profile: `{profile_name}`",
        f"- Enabled by default: `{bool_text(config.get('enabledByDefault', False))}`",
        f"- Mode: `{profile.get('mode', 'baseline')}`",
        f"- Engine: `{profile.get('engine', 'rke2')}`",
        f"- Strategy: `{orchestration.get('strategy', 'none')}`",
        f"- Orchestration enabled: `{bool_text(orchestration.get('enabled', False))}`",
        f"- Drain nodes: `{bool_text(orchestration.get('drainNodes', False))}`",
        f"- Restart services: `{bool_text(orchestration.get('restartServices', False))}`",
        f"- Current Kubernetes: `{display_private(versions['currentKubernetes'], '<private-current-kubernetes>', args.redact_sensitive)}`",
        f"- Target Kubernetes: `{display_private(versions['targetKubernetes'], '<private-target-kubernetes>', args.redact_sensitive)}`",
        f"- Current RKE2 version: `{display_private(versions['currentRke2'], '<private-current-rke2>', args.redact_sensitive)}`",
        f"- Target RKE2 version: `{display_private(versions['targetRke2'], '<private-target-rke2>', args.redact_sensitive)}`",
        f"- Kubernetes minor-version skew: `{skew}`",
        f"- Max minor-version skew: `{profile_versions.get('maxMinorSkew', 0)}`",
        f"- Cluster doctor: `{display_private(args.cluster_doctor, '<private-cluster-doctor>', args.redact_sensitive)}`",
        f"- Etcd snapshot: `{display_private(args.etcd_snapshot, '<private-etcd-snapshot>', args.redact_sensitive)}`",
        f"- Backup restore evidence: `{display_private(args.backup_restore_evidence, '<private-backup-restore-evidence>', args.redact_sensitive)}`",
        f"- Maintenance window: `{display_private(args.maintenance_window, '<private-maintenance-window>', args.redact_sensitive)}`",
        f"- Rollback plan: `{display_private(args.rollback_plan, '<private-rollback-plan>', args.redact_sensitive)}`",
        f"- Add-on compatibility: `{display_private(args.addon_compatibility, '<private-addon-compatibility>', args.redact_sensitive)}`",
        f"- Post-upgrade smoke-test plan: `{display_private(args.smoke_test_plan, '<private-smoke-test-plan>', args.redact_sensitive)}`",
        f"- Execution requested: `{bool_text(args.execute)}`",
        f"- Generated values overlay: `{display_path(overrides_path)}`",
        f"- Result: `{result}`",
        "",
        "## Upgrade Gates",
        "",
    ]
    for key in [
        "requirePinnedVersion",
        "requireSupportedSkew",
        "requireEtcdSnapshot",
        "requireBackupRestore",
        "requireMaintenanceWindow",
        "requireCapacityHeadroom",
        "requireNodeHealth",
        "requireRollbackPlan",
        "requireAddOnCompatibility",
        "requirePostUpgradeSmokeTest",
    ]:
        lines.append(f"- {key}: `{bool_text(gates.get(key, False))}`")
    lines.extend(["", "## Evidence Requirements", ""])
    for key in ["requireClusterDoctor", "requireInventoryReview", "requireReleaseNotesReview", "requireOwnerApproval"]:
        lines.append(f"- {key}: `{bool_text(evidence.get(key, False))}`")
    lines.extend(["", "## Supported Strategies", ""])
    for item in as_list(config.get("supportedStrategies")):
        lines.append(f"- `{item}`")
    lines.extend(["", "## Version Skew Policy", ""])
    for key, value in as_mapping(config.get("versionSkewPolicy")).items():
        lines.append(f"- {key}: `{display_config(value)}`")
    lines.extend(["", "## Guardrails", ""])
    for item in as_list(config.get("guardrails")):
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Operator Command",
            "",
            "```bash",
            f"make cluster-upgrade-plan CLUSTER_UPGRADE_PROFILE={profile_name} IMPORT_REDACT=true",
            "```",
            "",
            "## Findings",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in findings)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe cluster upgrade and version-skew guardrail plan.")
    parser.add_argument("--config", default=str(ROOT / "config/cluster-upgrade.yaml"))
    parser.add_argument("--profile", default="")
    parser.add_argument("--current-kubernetes", default="")
    parser.add_argument("--target-kubernetes", default="")
    parser.add_argument("--current-rke2", default="")
    parser.add_argument("--target-rke2", default="")
    parser.add_argument("--cluster-doctor", default="")
    parser.add_argument("--etcd-snapshot", default="")
    parser.add_argument("--backup-restore-evidence", default="")
    parser.add_argument("--maintenance-window", default="")
    parser.add_argument("--capacity-evidence", default="")
    parser.add_argument("--node-health-evidence", default="")
    parser.add_argument("--rollback-plan", default="")
    parser.add_argument("--addon-compatibility", default="")
    parser.add_argument("--smoke-test-plan", default="")
    parser.add_argument("--inventory-review", default="")
    parser.add_argument("--release-notes-review", default="")
    parser.add_argument("--owner-approval", default="")
    parser.add_argument("--output", default=str(ROOT / "reports/cluster-upgrade-plan.md"))
    parser.add_argument("--overrides", default=str(ROOT / "reports/cluster-upgrade-values.yaml"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--redact-sensitive", action="store_true")
    args = parser.parse_args(argv)

    config = load_yaml_file(resolve_path(args.config))
    profile_name, profile = profile_config(config, args.profile)
    output_path = resolve_path(args.output)
    overrides_path = resolve_path(args.overrides)
    versions = effective_versions(args, profile)
    write_overrides(overrides_path, profile_name, profile, versions)
    report = generate_report(args, config, profile_name, profile, versions, output_path, overrides_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Cluster upgrade plan written to {display_path(output_path)}")
    print(f"Cluster upgrade values overlay written to {display_path(overrides_path)}")
    if "Result: `FAIL`" in report:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
