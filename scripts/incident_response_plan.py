#!/usr/bin/env python3
"""Generate a public-safe incident response and operational readiness plan."""
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
        raise SystemExit("Incident response config must contain a profiles mapping.")
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown incident response profile `{profile_name}`. Available profiles: {choices}")
    profile = profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Incident response profile `{profile_name}` must be a mapping.")
    return profile


def display_private(value: str, replacement: str, redact: bool) -> str:
    if not value:
        return "-"
    if value in {"-", "none"}:
        return value
    return replacement if redact else value


def profile_findings(profile_name: str, profile: dict[str, Any], args: argparse.Namespace) -> list[str]:
    findings: list[str] = []
    alerting = as_mapping(profile.get("alerting"))
    runbooks = as_mapping(profile.get("runbooks"))
    communications = as_mapping(profile.get("communications"))
    drills = as_mapping(profile.get("drills"))
    evidence = as_mapping(profile.get("evidence"))

    if not bool_value(profile.get("enabled"), False):
        findings.append(f"INFO: Profile `{profile_name}` is plan-only; committed values keep incident automation disabled.")
    if bool_value(profile.get("requireAlertRoutes"), False) or bool_value(alerting.get("requireAlertRoutes"), False):
        if not args.alert_route_source:
            findings.append("WARN: Alert route ownership must be documented before production incident readiness.")
    if bool_value(profile.get("requireEscalationRota"), False) and not args.escalation_rota:
        findings.append("WARN: Escalation rota must be reviewed privately before production paging.")
    if bool_value(profile.get("requirePagerService"), False) or bool_value(alerting.get("requirePaging"), False):
        if not args.pager_service:
            findings.append("WARN: Paging service ownership is required before enabling production on-call workflows.")
    if bool_value(runbooks.get("requireRunbookIndex"), False) or bool_value(profile.get("requireRunbookIndex"), False):
        if not args.runbook_source:
            findings.append("WARN: Runbook index or source must be reviewed before incident response readiness.")
    if bool_value(runbooks.get("requireServiceOwnership"), False) and not args.service_owner_map:
        findings.append("WARN: Service ownership map is required before production incident routing.")
    if bool_value(runbooks.get("requireRollbackSteps"), False):
        findings.append("INFO: Rollback and restore steps should be linked from each service runbook.")
    if bool_value(communications.get("requireCommsTemplate"), False) or bool_value(profile.get("requireCommsTemplate"), False):
        if not args.comms_template:
            findings.append("WARN: Incident communication template must be reviewed before production use.")
    if bool_value(communications.get("requireStakeholderMap"), False) and not args.stakeholder_map:
        findings.append("WARN: Stakeholder map is required before broad incident communication.")
    if bool_value(drills.get("requireIncidentDrill"), False) or bool_value(profile.get("requireIncidentDrill"), False):
        if not args.incident_drill:
            findings.append("WARN: Incident drill evidence is required before production on-call readiness.")
    if bool_value(drills.get("requirePostIncidentReview"), False) or bool_value(profile.get("requirePostIncidentReview"), False):
        if not args.post_incident_review:
            findings.append("WARN: Post-incident review process must be proven before production readiness.")
    if bool_value(evidence.get("requireTimeline"), False):
        findings.append("INFO: Incident timelines should be stored in the private incident system, not public reports.")
    if bool_value(profile.get("requireRegulatoryOwner"), False) and not args.regulatory_owner:
        findings.append("WARN: Regulated incident mode requires a private regulatory reporting owner.")
    return findings or ["OK: Incident response settings are internally consistent."]


def result_from_findings(findings: list[str]) -> str:
    if any(item.startswith("ERROR:") for item in findings):
        return "FAIL"
    if any(item.startswith("WARN:") for item in findings):
        return "WARN"
    return "PASS"


def write_overrides(path: Path, profile_name: str, profile: dict[str, Any], args: argparse.Namespace) -> None:
    alerting = as_mapping(profile.get("alerting"))
    runbooks = as_mapping(profile.get("runbooks"))
    communications = as_mapping(profile.get("communications"))
    drills = as_mapping(profile.get("drills"))
    evidence = as_mapping(profile.get("evidence"))
    lines = [
        "incidentResponse:",
        "  enabled: false",
        f"  profile: {profile_name}",
        f"  mode: {profile.get('mode', 'baseline')}",
        f"  severityModel: {profile.get('severityModel', 'none')}",
        "  alerting:",
        f"    enabled: {str(bool_value(alerting.get('enabled'), False)).lower()}",
        f"    requireAlertRoutes: {str(bool_value(alerting.get('requireAlertRoutes'), False)).lower()}",
        f"    requirePaging: {str(bool_value(alerting.get('requirePaging'), False)).lower()}",
        f"    requireQuietHours: {str(bool_value(alerting.get('requireQuietHours'), False)).lower()}",
        "  runbooks:",
        f"    enabled: {str(bool_value(runbooks.get('enabled'), False)).lower()}",
        f"    requireRunbookIndex: {str(bool_value(runbooks.get('requireRunbookIndex'), False)).lower()}",
        f"    requireServiceOwnership: {str(bool_value(runbooks.get('requireServiceOwnership'), False)).lower()}",
        f"    requireRollbackSteps: {str(bool_value(runbooks.get('requireRollbackSteps'), False)).lower()}",
        "  communications:",
        f"    enabled: {str(bool_value(communications.get('enabled'), False)).lower()}",
        f"    requireCommsTemplate: {str(bool_value(communications.get('requireCommsTemplate'), False)).lower()}",
        f"    requireStakeholderMap: {str(bool_value(communications.get('requireStakeholderMap'), False)).lower()}",
        "  drills:",
        f"    enabled: {str(bool_value(drills.get('enabled'), False)).lower()}",
        f"    requireIncidentDrill: {str(bool_value(drills.get('requireIncidentDrill'), False)).lower()}",
        f"    requirePostIncidentReview: {str(bool_value(drills.get('requirePostIncidentReview'), False)).lower()}",
        "  evidence:",
        f"    enabled: {str(bool_value(evidence.get('enabled'), False)).lower()}",
        f"    requireTimeline: {str(bool_value(evidence.get('requireTimeline'), False)).lower()}",
        f"    requireActionItems: {str(bool_value(evidence.get('requireActionItems'), False)).lower()}",
        "  reports:",
        "    plan: reports/incident-response-plan.md",
        "    overrides: reports/incident-response-values.yaml",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_report(args: argparse.Namespace, config: dict[str, Any], profile: dict[str, Any], findings: list[str]) -> str:
    controller = as_mapping(config.get("controller"))
    alerting = as_mapping(profile.get("alerting"))
    runbooks = as_mapping(profile.get("runbooks"))
    communications = as_mapping(profile.get("communications"))
    drills = as_mapping(profile.get("drills"))
    evidence = as_mapping(profile.get("evidence"))
    checks = as_list(config.get("requiredChecks"))
    guardrails = as_list(config.get("guardrails"))
    integrations = as_list(config.get("supportedIntegrations"))
    result = result_from_findings(findings)

    alert_route_source = display_private(args.alert_route_source, "<private-alert-route-source>", args.redact_sensitive)
    escalation_rota = display_private(args.escalation_rota, "<private-escalation-rota>", args.redact_sensitive)
    pager_service = display_private(args.pager_service, "<private-pager-service>", args.redact_sensitive)
    runbook_source = display_private(args.runbook_source, "<private-runbook-source>", args.redact_sensitive)
    service_owner_map = display_private(args.service_owner_map, "<private-service-owner-map>", args.redact_sensitive)
    comms_template = display_private(args.comms_template, "<private-comms-template>", args.redact_sensitive)
    stakeholder_map = display_private(args.stakeholder_map, "<private-stakeholder-map>", args.redact_sensitive)
    regulatory_owner = display_private(args.regulatory_owner, "<private-regulatory-owner>", args.redact_sensitive)

    lines = [
        "# Incident Response And Operational Readiness Plan",
        "",
        "This report is public-safe. It does not page anyone, create tickets, open incidents, print contact rosters, expose pager service IDs, list user names, or include private incident timelines.",
        "",
        f"- Profile: `{args.profile}`",
        f"- Enabled: `{str(bool_value(profile.get('enabled'), False)).lower()}`",
        f"- Mode: `{profile.get('mode', 'baseline')}`",
        f"- Severity model: `{profile.get('severityModel', 'none')}`",
        f"- Alert route source: `{alert_route_source}`",
        f"- Escalation rota: `{escalation_rota}`",
        f"- Pager service: `{pager_service}`",
        f"- Runbook source: `{runbook_source}`",
        f"- Service owner map: `{service_owner_map}`",
        f"- Communication template: `{comms_template}`",
        f"- Stakeholder map: `{stakeholder_map}`",
        f"- Regulatory owner: `{regulatory_owner}`",
        f"- Alerting enabled: `{str(bool_value(alerting.get('enabled'), False)).lower()}`",
        f"- Require alert routes: `{str(bool_value(alerting.get('requireAlertRoutes'), False)).lower()}`",
        f"- Require paging: `{str(bool_value(alerting.get('requirePaging'), False)).lower()}`",
        f"- Require quiet hours: `{str(bool_value(alerting.get('requireQuietHours'), False)).lower()}`",
        f"- Runbooks enabled: `{str(bool_value(runbooks.get('enabled'), False)).lower()}`",
        f"- Require runbook index: `{str(bool_value(runbooks.get('requireRunbookIndex'), False)).lower()}`",
        f"- Require service ownership: `{str(bool_value(runbooks.get('requireServiceOwnership'), False)).lower()}`",
        f"- Require rollback steps: `{str(bool_value(runbooks.get('requireRollbackSteps'), False)).lower()}`",
        f"- Communications enabled: `{str(bool_value(communications.get('enabled'), False)).lower()}`",
        f"- Require comms template: `{str(bool_value(communications.get('requireCommsTemplate'), False)).lower()}`",
        f"- Require stakeholder map: `{str(bool_value(communications.get('requireStakeholderMap'), False)).lower()}`",
        f"- Drills enabled: `{str(bool_value(drills.get('enabled'), False)).lower()}`",
        f"- Incident drill evidence: `{str(args.incident_drill).lower()}`",
        f"- Post-incident review: `{str(args.post_incident_review).lower()}`",
        f"- Evidence timeline required: `{str(bool_value(evidence.get('requireTimeline'), False)).lower()}`",
        f"- Evidence action items required: `{str(bool_value(evidence.get('requireActionItems'), False)).lower()}`",
        f"- Report: `{args.output or controller.get('report', '-')}`",
        f"- Values overlay: `{args.overrides or controller.get('overrides', '-')}`",
        f"- Result: `{result}`",
        "",
        "## Supported Integrations",
        "",
    ]
    lines.extend([f"- `{item}`" for item in integrations] or ["- `none`"])
    lines.extend(["", "## Required Checks", ""])
    lines.extend([f"- {item}" for item in checks] or ["- No required checks configured."])
    lines.extend(["", "## Findings", ""])
    lines.extend([f"- {item}" for item in findings])
    lines.extend(["", "## Guardrails", ""])
    lines.extend([f"- {item}" for item in guardrails] or ["- Keep private incident data outside Git."])
    lines.extend(
        [
            "",
            "## Next Actions",
            "",
            "- Re-run `make incident-response-plan` after alert routes, runbooks, or escalation ownership changes.",
            "- Keep the generated values overlay disabled until private on-call owners approve integrations and routing.",
            "- Store contact rosters, incident timelines, and post-incident reviews only in approved private systems.",
            "- Link incident evidence into the compliance evidence plan after each drill or real incident.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/incident-response.yaml")
    parser.add_argument("--profile", default="")
    parser.add_argument("--alert-route-source", default="")
    parser.add_argument("--escalation-rota", default="")
    parser.add_argument("--pager-service", default="")
    parser.add_argument("--runbook-source", default="")
    parser.add_argument("--service-owner-map", default="")
    parser.add_argument("--comms-template", default="")
    parser.add_argument("--stakeholder-map", default="")
    parser.add_argument("--regulatory-owner", default="")
    parser.add_argument("--incident-drill", action="store_true")
    parser.add_argument("--post-incident-review", action="store_true")
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
    output_path = Path(args.output or controller.get("report", "reports/incident-response-plan.md"))
    overrides_path = Path(args.overrides or controller.get("overrides", "reports/incident-response-values.yaml"))
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    if not overrides_path.is_absolute():
        overrides_path = ROOT / overrides_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generate_report(args, config, profile, findings), encoding="utf-8")
    write_overrides(overrides_path, args.profile, profile, args)
    print(f"Incident response plan written to {output_path.relative_to(ROOT)}")
    print(f"Incident response values written to {overrides_path.relative_to(ROOT)}")
    print(f"Result: {result_from_findings(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
