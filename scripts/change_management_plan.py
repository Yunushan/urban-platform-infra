#!/usr/bin/env python3
"""Generate a public-safe change management and maintenance-window plan."""
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
    if value in {"{}", "{ }"}:
        return {}
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lower() in {"null", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def next_child_is_list(lines: list[str], index: int, indent: int) -> bool:
    for raw_line in lines[index + 1 :]:
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
            if isinstance(parent, list):
                parent.append(parse_scalar(stripped[2:].strip()))
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


def bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def select_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = config.get("profiles", {})
    if not isinstance(profiles, dict):
        raise SystemExit("Change management config must contain a profiles mapping.")
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown change management profile `{profile_name}`. Available profiles: {choices}")
    profile = profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Change management profile `{profile_name}` must be a mapping.")
    return profile


def display_private(value: str, replacement: str, redact: bool) -> str:
    if not value:
        return "-"
    if value in {"-", "none"}:
        return value
    return replacement if redact else value


def profile_findings(profile_name: str, profile: dict[str, Any], args: argparse.Namespace) -> list[str]:
    findings: list[str] = []
    change_control = as_mapping(profile.get("changeControl"))
    maintenance_window = as_mapping(profile.get("maintenanceWindow"))
    rollout = as_mapping(profile.get("rollout"))
    evidence = as_mapping(profile.get("evidence"))

    if not bool_value(profile.get("enabled"), False):
        findings.append(f"INFO: Profile `{profile_name}` is plan-only; committed values keep change automation disabled.")
    if bool_value(profile.get("requireChangeTicket"), False) or bool_value(change_control.get("requireChangeTicket"), False):
        if not args.change_ticket:
            findings.append("WARN: Change ticket or release record is required before production change readiness.")
    if bool_value(profile.get("requireApprovals"), False) or bool_value(change_control.get("requireApprovals"), False):
        if not args.approval_evidence:
            findings.append("WARN: Approval evidence must be reviewed before production change execution.")
    if bool_value(profile.get("requireRiskAssessment"), False) or bool_value(change_control.get("requireRiskAssessment"), False):
        if not args.risk_assessment:
            findings.append("WARN: Risk assessment must be completed before production change execution.")
    if bool_value(profile.get("requireImpactAssessment"), False) or bool_value(change_control.get("requireImpactAssessment"), False):
        if not args.impact_assessment:
            findings.append("WARN: Impact assessment must be completed before production change execution.")
    if bool_value(profile.get("requireMaintenanceWindow"), False) or bool_value(maintenance_window.get("requireWindow"), False):
        if not args.maintenance_window:
            findings.append("WARN: Maintenance window must be selected before production change execution.")
    if bool_value(profile.get("requireFreezeCheck"), False) or bool_value(maintenance_window.get("requireFreezeCheck"), False):
        if not args.freeze_check:
            findings.append("WARN: Freeze calendar check is required before production change execution.")
    if bool_value(profile.get("requireStakeholderNotice"), False) or bool_value(maintenance_window.get("requireStakeholderNotice"), False):
        if not args.stakeholder_notice:
            findings.append("WARN: Stakeholder notice evidence is required before production change execution.")
    if bool_value(profile.get("requireRollbackPlan"), False) or bool_value(rollout.get("requireRollbackPlan"), False):
        if not args.rollback_plan:
            findings.append("WARN: Rollback plan is required before executing this change.")
    if bool_value(profile.get("requireSmokeTests"), False) or bool_value(rollout.get("requireSmokeTests"), False):
        if not args.smoke_test_plan:
            findings.append("WARN: Smoke-test plan is required before executing this change.")
    if bool_value(profile.get("requirePostChangeReview"), False) or bool_value(rollout.get("requirePostChangeReview"), False):
        if not args.post_change_review:
            findings.append("WARN: Post-change review owner or process must be identified.")
    if bool_value(evidence.get("requireDeploymentEvidence"), False):
        findings.append("INFO: Deployment evidence should link release, rollout, validation, and rollback decision records.")
    if bool_value(profile.get("requireRegulatoryEvidence"), False) and not args.regulatory_evidence:
        findings.append("WARN: Regulated change mode requires private regulatory evidence ownership.")
    return findings or ["OK: Change management settings are internally consistent."]


def result_from_findings(findings: list[str]) -> str:
    if any(item.startswith("ERROR:") for item in findings):
        return "FAIL"
    if any(item.startswith("WARN:") for item in findings):
        return "WARN"
    return "PASS"


def write_overrides(path: Path, profile_name: str, profile: dict[str, Any], args: argparse.Namespace) -> None:
    change_control = as_mapping(profile.get("changeControl"))
    maintenance_window = as_mapping(profile.get("maintenanceWindow"))
    rollout = as_mapping(profile.get("rollout"))
    evidence = as_mapping(profile.get("evidence"))
    lines = [
        "changeManagement:",
        "  enabled: false",
        f"  profile: {profile_name}",
        f"  mode: {profile.get('mode', 'baseline')}",
        f"  approvalModel: {profile.get('approvalModel', 'none')}",
        "  changeControl:",
        f"    enabled: {str(bool_value(change_control.get('enabled'), False)).lower()}",
        f"    requireChangeTicket: {str(bool_value(change_control.get('requireChangeTicket'), False)).lower()}",
        f"    requireApprovals: {str(bool_value(change_control.get('requireApprovals'), False)).lower()}",
        f"    requireRiskAssessment: {str(bool_value(change_control.get('requireRiskAssessment'), False)).lower()}",
        f"    requireImpactAssessment: {str(bool_value(change_control.get('requireImpactAssessment'), False)).lower()}",
        "  maintenanceWindow:",
        f"    enabled: {str(bool_value(maintenance_window.get('enabled'), False)).lower()}",
        f"    requireWindow: {str(bool_value(maintenance_window.get('requireWindow'), False)).lower()}",
        f"    requireFreezeCheck: {str(bool_value(maintenance_window.get('requireFreezeCheck'), False)).lower()}",
        f"    requireStakeholderNotice: {str(bool_value(maintenance_window.get('requireStakeholderNotice'), False)).lower()}",
        "  rollout:",
        f"    enabled: {str(bool_value(rollout.get('enabled'), False)).lower()}",
        f"    requireRollbackPlan: {str(bool_value(rollout.get('requireRollbackPlan'), False)).lower()}",
        f"    requireSmokeTests: {str(bool_value(rollout.get('requireSmokeTests'), False)).lower()}",
        f"    requirePostChangeReview: {str(bool_value(rollout.get('requirePostChangeReview'), False)).lower()}",
        "  evidence:",
        f"    enabled: {str(bool_value(evidence.get('enabled'), False)).lower()}",
        f"    requireChangeRecord: {str(bool_value(evidence.get('requireChangeRecord'), False)).lower()}",
        f"    requireDeploymentEvidence: {str(bool_value(evidence.get('requireDeploymentEvidence'), False)).lower()}",
        f"    requireApprovalEvidence: {str(bool_value(evidence.get('requireApprovalEvidence'), False)).lower()}",
        "  reports:",
        "    plan: reports/change-management-plan.md",
        "    overrides: reports/change-management-values.yaml",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_report(args: argparse.Namespace, config: dict[str, Any], profile: dict[str, Any], findings: list[str]) -> str:
    controller = as_mapping(config.get("controller"))
    change_control = as_mapping(profile.get("changeControl"))
    maintenance_window = as_mapping(profile.get("maintenanceWindow"))
    rollout = as_mapping(profile.get("rollout"))
    evidence = as_mapping(profile.get("evidence"))
    checks = as_list(config.get("requiredChecks"))
    guardrails = as_list(config.get("guardrails"))
    systems = as_list(config.get("supportedSystems"))
    result = result_from_findings(findings)

    change_ticket = display_private(args.change_ticket, "<private-change-ticket>", args.redact_sensitive)
    approval_evidence = display_private(args.approval_evidence, "<private-approval-evidence>", args.redact_sensitive)
    risk_assessment = display_private(args.risk_assessment, "<private-risk-assessment>", args.redact_sensitive)
    impact_assessment = display_private(args.impact_assessment, "<private-impact-assessment>", args.redact_sensitive)
    maintenance_window_display = display_private(args.maintenance_window, "<private-maintenance-window>", args.redact_sensitive)
    rollback_plan = display_private(args.rollback_plan, "<private-rollback-plan>", args.redact_sensitive)
    smoke_test_plan = display_private(args.smoke_test_plan, "<private-smoke-test-plan>", args.redact_sensitive)

    lines = [
        "# Change Management And Maintenance Window Plan",
        "",
        "This report is public-safe. It does not open tickets, approve changes, update calendars, print approver names, expose maintenance windows, list customer impact notes, or include private ticket URLs.",
        "",
        f"- Profile: `{args.profile}`",
        f"- Enabled: `{str(bool_value(profile.get('enabled'), False)).lower()}`",
        f"- Mode: `{profile.get('mode', 'baseline')}`",
        f"- Approval model: `{profile.get('approvalModel', 'none')}`",
        f"- Change ticket: `{change_ticket}`",
        f"- Approval evidence: `{approval_evidence}`",
        f"- Risk assessment: `{risk_assessment}`",
        f"- Impact assessment: `{impact_assessment}`",
        f"- Maintenance window: `{maintenance_window_display}`",
        f"- Freeze check: `{str(args.freeze_check).lower()}`",
        f"- Stakeholder notice: `{str(args.stakeholder_notice).lower()}`",
        f"- Rollback plan: `{rollback_plan}`",
        f"- Smoke-test plan: `{smoke_test_plan}`",
        f"- Post-change review: `{str(args.post_change_review).lower()}`",
        f"- Regulatory evidence: `{str(args.regulatory_evidence).lower()}`",
        f"- Change control enabled: `{str(bool_value(change_control.get('enabled'), False)).lower()}`",
        f"- Require change ticket: `{str(bool_value(change_control.get('requireChangeTicket'), False)).lower()}`",
        f"- Require approvals: `{str(bool_value(change_control.get('requireApprovals'), False)).lower()}`",
        f"- Require risk assessment: `{str(bool_value(change_control.get('requireRiskAssessment'), False)).lower()}`",
        f"- Require impact assessment: `{str(bool_value(change_control.get('requireImpactAssessment'), False)).lower()}`",
        f"- Require window: `{str(bool_value(maintenance_window.get('requireWindow'), False)).lower()}`",
        f"- Require freeze check: `{str(bool_value(maintenance_window.get('requireFreezeCheck'), False)).lower()}`",
        f"- Require rollback plan: `{str(bool_value(rollout.get('requireRollbackPlan'), False)).lower()}`",
        f"- Require smoke tests: `{str(bool_value(rollout.get('requireSmokeTests'), False)).lower()}`",
        f"- Require post-change review: `{str(bool_value(rollout.get('requirePostChangeReview'), False)).lower()}`",
        f"- Evidence enabled: `{str(bool_value(evidence.get('enabled'), False)).lower()}`",
        f"- Report: `{args.output or controller.get('report', '-')}`",
        f"- Values overlay: `{args.overrides or controller.get('overrides', '-')}`",
        f"- Result: `{result}`",
        "",
        "## Supported Systems",
        "",
    ]
    lines.extend([f"- `{item}`" for item in systems] or ["- `none`"])
    lines.extend(["", "## Required Checks", ""])
    lines.extend([f"- {item}" for item in checks] or ["- No required checks configured."])
    lines.extend(["", "## Findings", ""])
    lines.extend([f"- {item}" for item in findings])
    lines.extend(["", "## Guardrails", ""])
    lines.extend([f"- {item}" for item in guardrails] or ["- Keep private change data outside Git."])
    lines.extend(
        [
            "",
            "## Next Actions",
            "",
            "- Re-run `make change-management-plan` after release scope, approvals, or maintenance windows change.",
            "- Keep the generated values overlay disabled until private change owners approve the workflow.",
            "- Store approval records, ticket URLs, calendar entries, and customer impact notes only in approved private systems.",
            "- Link private change evidence into the compliance evidence plan after each production change.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/change-management.yaml")
    parser.add_argument("--profile", default="")
    parser.add_argument("--change-ticket", default="")
    parser.add_argument("--approval-evidence", default="")
    parser.add_argument("--risk-assessment", default="")
    parser.add_argument("--impact-assessment", default="")
    parser.add_argument("--maintenance-window", default="")
    parser.add_argument("--rollback-plan", default="")
    parser.add_argument("--smoke-test-plan", default="")
    parser.add_argument("--freeze-check", action="store_true")
    parser.add_argument("--stakeholder-notice", action="store_true")
    parser.add_argument("--post-change-review", action="store_true")
    parser.add_argument("--regulatory-evidence", action="store_true")
    parser.add_argument("--output", default="")
    parser.add_argument("--overrides", default="")
    parser.add_argument("--redact-sensitive", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = (ROOT / args.config).resolve() if not Path(args.config).is_absolute() else Path(args.config)
    config = load_yaml_file(config_path)
    if not args.profile:
        args.profile = str(config.get("defaultProfile", "disabled"))
    profile = select_profile(config, args.profile)
    findings = profile_findings(args.profile, profile, args)
    controller = as_mapping(config.get("controller"))
    output_path = Path(args.output or controller.get("report", "reports/change-management-plan.md"))
    overrides_path = Path(args.overrides or controller.get("overrides", "reports/change-management-values.yaml"))
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    if not overrides_path.is_absolute():
        overrides_path = ROOT / overrides_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generate_report(args, config, profile, findings), encoding="utf-8")
    write_overrides(overrides_path, args.profile, profile, args)
    print(f"Change management plan written to {output_path.relative_to(ROOT)}")
    print(f"Change management values written to {overrides_path.relative_to(ROOT)}")
    print(f"Result: {result_from_findings(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
