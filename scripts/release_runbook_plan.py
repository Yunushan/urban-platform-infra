#!/usr/bin/env python3
"""Generate a public-safe release runbook and evidence gate plan."""
from __future__ import annotations

import argparse
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
            if ":" in item:
                key, raw_value = item.split(":", 1)
                child: dict[str, Any] = {}
                parent.append(child)
                child[key.strip().strip("'\"")] = parse_scalar(raw_value.strip()) if raw_value.strip() else {}
                stack.append((indent, child))
            else:
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


def bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"true", "yes", "on", "1"}
    return default


def bool_text(value: Any) -> str:
    return "true" if bool_value(value) else "false"


def as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


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


def profiles(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("profiles", {})
    if not isinstance(value, dict):
        raise SystemExit("Release runbook config must contain a profiles mapping.")
    return value


def profile_config(config: dict[str, Any], requested_profile: str) -> tuple[str, dict[str, Any]]:
    profile_name = requested_profile or str(config.get("defaultProfile", "disabled"))
    all_profiles = profiles(config)
    if profile_name not in all_profiles:
        choices = ", ".join(sorted(all_profiles))
        raise SystemExit(f"Unknown release runbook profile `{profile_name}`. Available profiles: {choices}")
    profile = all_profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Release runbook profile `{profile_name}` must be a mapping.")
    return profile_name, profile


def public_artifact_rows(config: dict[str, Any]) -> list[tuple[str, bool]]:
    rows: list[tuple[str, bool]] = []
    for item in as_list(config.get("publicArtifacts")):
        text = str(item)
        rows.append((text, resolve_path(text).exists()))
    return rows


def profile_findings(args: argparse.Namespace, profile_name: str, profile: dict[str, Any], artifact_rows: list[tuple[str, bool]]) -> list[str]:
    gates = as_mapping(profile.get("gates"))
    evidence = as_mapping(profile.get("evidence"))
    findings = []
    if not bool_value(profile.get("enabled")):
        findings.append(f"INFO: Profile `{profile_name}` is plan-only; committed values keep release runbook automation disabled.")
    if args.execute:
        findings.append("WARN: Execute was requested; this planner still does not publish tags, approve changes, deploy, or switch traffic.")
    if bool_value(gates.get("requireReleaseTag")) and not args.release_tag:
        findings.append("WARN: Release tag is required before production release approval.")
    if bool_value(gates.get("requireArtifactEvidence")) and not args.release_evidence:
        findings.append("WARN: Release evidence verification report is required before promotion.")
    if bool_value(gates.get("requireChangeApproval")) and not args.approval_evidence:
        findings.append("WARN: Change approval evidence is required before production release.")
    if bool_value(gates.get("requireChangeApproval")) and not args.change_ticket:
        findings.append("WARN: Change ticket or release record is required before production release.")
    if bool_value(gates.get("requireRollbackPlan")) and not args.rollback_plan:
        findings.append("WARN: Rollback plan and owner evidence are required before release.")
    if bool_value(gates.get("requireSmokeTestPlan")) and not args.smoke_test_plan:
        findings.append("WARN: Smoke-test plan is required before release approval.")
    if bool_value(gates.get("requireCutoverGate")) and not args.cutover_gate_plan:
        findings.append("WARN: Cutover gate plan is required before release approval.")
    if bool_value(evidence.get("requirePublicBundle")) and not args.environment_evidence:
        findings.append("WARN: Environment evidence bundle should be attached to the release runbook.")
    if bool_value(evidence.get("requirePrivateApprovalIndex")) and not args.approval_evidence:
        findings.append("WARN: Private approval index is required before production release.")
    if bool_value(evidence.get("requireOwnerReview")) and not args.approval_evidence:
        findings.append("WARN: Owner-reviewed release evidence is required before production release.")
    present = {path: exists for path, exists in artifact_rows}
    if bool_value(gates.get("requireArtifactEvidence")) and not present.get("reports/release-evidence-verification.md", False):
        findings.append("WARN: Required public artifact is missing: `reports/release-evidence-verification.md`.")
    if profile_name == "production-release" and not bool_value(gates.get("requireAttestation")):
        findings.append("ERROR: Production release profile must require attestation review.")
    return findings or ["OK: Release runbook gate settings are internally consistent."]


def result_from_findings(findings: list[str]) -> str:
    if any(item.startswith("ERROR:") for item in findings):
        return "FAIL"
    if any(item.startswith("WARN:") for item in findings):
        return "WARN"
    return "PASS"


def write_overrides(path: Path, profile_name: str, profile: dict[str, Any]) -> None:
    execution = as_mapping(profile.get("execution"))
    gates = as_mapping(profile.get("gates"))
    evidence = as_mapping(profile.get("evidence"))
    values = {
        "releaseRunbook": {
            "enabled": False,
            "profile": profile_name,
            "mode": str(profile.get("mode", "baseline")),
            "execution": {
                "enabled": False,
                "publisher": str(execution.get("publisher", "none")),
                "deployer": str(execution.get("deployer", "none")),
            },
            "gates": {
                "requireReleaseTag": bool_value(gates.get("requireReleaseTag")),
                "requireCleanWorktree": bool_value(gates.get("requireCleanWorktree")),
                "requireArtifactEvidence": bool_value(gates.get("requireArtifactEvidence")),
                "requireSbom": bool_value(gates.get("requireSbom")),
                "requireChecksums": bool_value(gates.get("requireChecksums")),
                "requireAttestation": bool_value(gates.get("requireAttestation")),
                "requireChangeApproval": bool_value(gates.get("requireChangeApproval")),
                "requireSmokeTestPlan": bool_value(gates.get("requireSmokeTestPlan")),
                "requireCutoverGate": bool_value(gates.get("requireCutoverGate")),
                "requireRollbackPlan": bool_value(gates.get("requireRollbackPlan")),
            },
            "evidence": {
                "requirePublicBundle": bool_value(evidence.get("requirePublicBundle")),
                "requirePrivateApprovalIndex": bool_value(evidence.get("requirePrivateApprovalIndex")),
                "requireOwnerReview": bool_value(evidence.get("requireOwnerReview")),
            },
            "reports": {
                "plan": "reports/release-runbook-plan.md",
                "overrides": "reports/release-runbook-values.yaml",
            },
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(["# Generated by scripts/release_runbook_plan.py. Review before use.", *dump_yaml(values), ""]), encoding="utf-8")


def generate_report(args: argparse.Namespace, config: dict[str, Any], profile_name: str, profile: dict[str, Any], output_path: Path, overrides_path: Path) -> str:
    artifact_rows = public_artifact_rows(config)
    findings = profile_findings(args, profile_name, profile, artifact_rows)
    result = result_from_findings(findings)
    execution = as_mapping(profile.get("execution"))
    gates = as_mapping(profile.get("gates"))
    evidence = as_mapping(profile.get("evidence"))
    lines = [
        "# Release Runbook And Evidence Gate Plan",
        "",
        "This report is public-safe. It links release artifact evidence, change approval, rollback, smoke-test, cutover readiness, and private approval index status without printing private repository URLs, ticket URLs, approver names, registry paths, DNS names, node names, or customer identifiers.",
        "",
        f"- Profile: `{profile_name}`",
        f"- Enabled by default: `{bool_text(config.get('enabledByDefault', False))}`",
        f"- Mode: `{profile.get('mode', 'baseline')}`",
        f"- Release tag: `{display_private(args.release_tag, '<private-release-tag>', args.redact_sensitive)}`",
        f"- Release evidence: `{display_private(args.release_evidence, '<private-release-evidence>', args.redact_sensitive)}`",
        f"- Change ticket: `{display_private(args.change_ticket, '<private-change-ticket>', args.redact_sensitive)}`",
        f"- Approval evidence: `{display_private(args.approval_evidence, '<private-approval-evidence>', args.redact_sensitive)}`",
        f"- Rollback plan: `{display_private(args.rollback_plan, '<private-rollback-plan>', args.redact_sensitive)}`",
        f"- Smoke-test plan: `{display_private(args.smoke_test_plan, '<private-smoke-test-plan>', args.redact_sensitive)}`",
        f"- Cutover gate plan: `{display_private(args.cutover_gate_plan, '<private-cutover-gate-plan>', args.redact_sensitive)}`",
        f"- Environment evidence: `{display_private(args.environment_evidence, '<private-environment-evidence>', args.redact_sensitive)}`",
        f"- Execution requested: `{bool_text(args.execute)}`",
        f"- Publisher: `{execution.get('publisher', 'none')}`",
        f"- Deployer: `{execution.get('deployer', 'none')}`",
        f"- Generated values overlay: `{display_path(overrides_path)}`",
        f"- Result: `{result}`",
        "",
        "## Required Gates",
        "",
    ]
    for key in [
        "requireReleaseTag",
        "requireCleanWorktree",
        "requireArtifactEvidence",
        "requireSbom",
        "requireChecksums",
        "requireAttestation",
        "requireChangeApproval",
        "requireSmokeTestPlan",
        "requireCutoverGate",
        "requireRollbackPlan",
    ]:
        lines.append(f"- {key}: `{bool_text(gates.get(key, False))}`")
    lines.extend(["", "## Evidence Requirements", ""])
    for key in ["requirePublicBundle", "requirePrivateApprovalIndex", "requireOwnerReview"]:
        lines.append(f"- {key}: `{bool_text(evidence.get(key, False))}`")
    lines.extend(["", "## Public Artifacts", "", "| Artifact | Present |", "|---|---|"])
    for artifact, present in artifact_rows:
        lines.append(f"| `{artifact}` | `{bool_text(present)}` |")
    if not artifact_rows:
        lines.append("| `-` | `false` |")
    lines.extend(["", "## Runbook Sections", ""])
    for item in as_list(config.get("runbookSections")):
        lines.append(f"- {item}")
    if not as_list(config.get("runbookSections")):
        lines.append("- No runbook sections declared.")
    lines.extend(["", "## Guardrails", ""])
    for item in as_list(config.get("guardrails")):
        lines.append(f"- {item}")
    if not as_list(config.get("guardrails")):
        lines.append("- No guardrails declared.")
    lines.extend(
        [
            "",
            "## Operator Command",
            "",
            "```bash",
            f"make release-runbook-plan RELEASE_RUNBOOK_PROFILE={profile_name} IMPORT_REDACT=true",
            "```",
            "",
            "## Findings",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in findings)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe release runbook and evidence gate plan.")
    parser.add_argument("--config", default=str(ROOT / "config/release-runbook.yaml"))
    parser.add_argument("--profile", default="")
    parser.add_argument("--release-tag", default="")
    parser.add_argument("--release-evidence", default="")
    parser.add_argument("--change-ticket", default="")
    parser.add_argument("--approval-evidence", default="")
    parser.add_argument("--rollback-plan", default="")
    parser.add_argument("--smoke-test-plan", default="")
    parser.add_argument("--cutover-gate-plan", default="")
    parser.add_argument("--environment-evidence", default="")
    parser.add_argument("--output", default=str(ROOT / "reports/release-runbook-plan.md"))
    parser.add_argument("--overrides", default=str(ROOT / "reports/release-runbook-values.yaml"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--redact-sensitive", action="store_true")
    args = parser.parse_args(argv)

    config = load_yaml_file(resolve_path(args.config))
    profile_name, profile = profile_config(config, args.profile)
    output_path = resolve_path(args.output)
    overrides_path = resolve_path(args.overrides)
    write_overrides(overrides_path, profile_name, profile)
    report = generate_report(args, config, profile_name, profile, output_path, overrides_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Release runbook plan written to {display_path(output_path)}")
    print(f"Release runbook values overlay written to {display_path(overrides_path)}")
    if "Result: `FAIL`" in report:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
