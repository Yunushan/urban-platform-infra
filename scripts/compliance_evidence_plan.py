#!/usr/bin/env python3
"""Generate a public-safe compliance evidence and audit-pack plan."""
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
        raise SystemExit("Compliance evidence config must contain a profiles mapping.")
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown compliance evidence profile `{profile_name}`. Available profiles: {choices}")
    profile = profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Compliance evidence profile `{profile_name}` must be a mapping.")
    return profile


def display_private(value: str, replacement: str, redact: bool) -> str:
    if not value:
        return "-"
    if value in {"-", "none"}:
        return value
    return replacement if redact else value


def profile_findings(profile_name: str, profile: dict[str, Any], args: argparse.Namespace) -> list[str]:
    findings: list[str] = []
    evidence = as_mapping(profile.get("evidence"))
    retention = as_mapping(profile.get("retention"))
    packaging = as_mapping(profile.get("packaging"))

    if not bool_value(profile.get("enabled"), False):
        findings.append(f"INFO: Profile `{profile_name}` is plan-only; committed values keep evidence packaging disabled.")
    if bool_value(profile.get("requirePrivateIndex"), False) or bool_value(evidence.get("requirePrivateIndex"), False):
        if not args.private_evidence_index:
            findings.append("WARN: Production evidence planning requires a private evidence index outside Git.")
    if bool_value(profile.get("requireControlMap"), False) or bool_value(evidence.get("requireControlMap"), False):
        if not args.control_map:
            findings.append("WARN: Control-family mapping must be reviewed before relying on an audit pack.")
    if bool_value(profile.get("requireReleaseTag"), False) or bool_value(evidence.get("requireReleaseTag"), False):
        if not args.release_tag:
            findings.append("WARN: Production evidence requires a release tag or immutable release identifier.")
    if bool_value(profile.get("requireRestoreDrill"), False) or bool_value(evidence.get("requireRestoreDrill"), False):
        if not args.restore_drill_evidence:
            findings.append("WARN: Restore drill evidence is required before production audit-pack readiness.")
    if bool_value(profile.get("requireAccessReview"), False) or bool_value(evidence.get("requireAccessReview"), False):
        if not args.access_review_evidence:
            findings.append("WARN: Access review evidence is required before production audit-pack readiness.")
    if bool_value(profile.get("requireIncidentDrill"), False) or bool_value(evidence.get("requireIncidentDrill"), False):
        if not args.incident_drill_evidence:
            findings.append("WARN: Incident response drill evidence is required before production audit-pack readiness.")
    if bool_value(packaging.get("includeAttestations"), False) and not args.attestation_source:
        findings.append("WARN: Attestation source should be identified before including attestations in an audit pack.")
    if bool_value(retention.get("enabled"), False):
        findings.append("WARN: Retention automation must stay private until storage ownership, legal hold, and deletion rules are approved.")
    if as_list(profile.get("controlFamilies")):
        findings.append("INFO: Control families are mapped as readiness intent, not as a certification claim.")
    return findings or ["OK: Compliance evidence settings are internally consistent."]


def result_from_findings(findings: list[str]) -> str:
    if any(item.startswith("ERROR:") for item in findings):
        return "FAIL"
    if any(item.startswith("WARN:") for item in findings):
        return "WARN"
    return "PASS"


def write_overrides(path: Path, profile_name: str, profile: dict[str, Any], args: argparse.Namespace) -> None:
    evidence = as_mapping(profile.get("evidence"))
    retention = as_mapping(profile.get("retention"))
    packaging = as_mapping(profile.get("packaging"))
    lines = [
        "complianceEvidence:",
        "  enabled: false",
        f"  profile: {profile_name}",
        f"  mode: {profile.get('mode', 'baseline')}",
        "  evidence:",
        f"    collectReports: {str(bool_value(evidence.get('collectReports'), False)).lower()}",
        f"    requirePrivateIndex: {str(bool_value(evidence.get('requirePrivateIndex'), False)).lower()}",
        f"    requireReleaseTag: {str(bool_value(evidence.get('requireReleaseTag'), False)).lower()}",
        f"    requireControlMap: {str(bool_value(evidence.get('requireControlMap'), False)).lower()}",
        f"    requireRestoreDrill: {str(bool_value(evidence.get('requireRestoreDrill'), False)).lower()}",
        f"    requireAccessReview: {str(bool_value(evidence.get('requireAccessReview'), False)).lower()}",
        f"    requireIncidentDrill: {str(bool_value(evidence.get('requireIncidentDrill'), False)).lower()}",
        "  retention:",
        f"    enabled: {str(bool_value(retention.get('enabled'), False)).lower()}",
        f"    days: {retention.get('days', 0)}",
        f"    storageTier: {retention.get('storageTier', 'none')}",
        "  packaging:",
        f"    enabled: {str(bool_value(packaging.get('enabled'), False)).lower()}",
        f"    format: {packaging.get('format', 'report-only')}",
        f"    includeChecksums: {str(bool_value(packaging.get('includeChecksums'), False)).lower()}",
        f"    includeAttestations: {str(bool_value(packaging.get('includeAttestations'), False)).lower()}",
        "  reports:",
        "    plan: reports/compliance-evidence-plan.md",
        "    overrides: reports/compliance-evidence-values.yaml",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_report(args: argparse.Namespace, config: dict[str, Any], profile: dict[str, Any], findings: list[str]) -> str:
    controller = as_mapping(config.get("controller"))
    evidence = as_mapping(profile.get("evidence"))
    retention = as_mapping(profile.get("retention"))
    packaging = as_mapping(profile.get("packaging"))
    sources = as_list(config.get("evidenceSources"))
    checks = as_list(config.get("requiredChecks"))
    guardrails = as_list(config.get("guardrails"))
    control_families = as_list(profile.get("controlFamilies"))
    result = result_from_findings(findings)

    release_tag = display_private(args.release_tag, "<private-release-tag>", args.redact_sensitive)
    evidence_root = display_private(args.evidence_root, "<private-evidence-root>", args.redact_sensitive)
    control_map = display_private(args.control_map, "<private-control-map>", args.redact_sensitive)
    private_index = display_private(args.private_evidence_index, "<private-evidence-index>", args.redact_sensitive)
    attestation_source = display_private(args.attestation_source, "<private-attestation-source>", args.redact_sensitive)

    lines = [
        "# Compliance Evidence And Audit Pack Plan",
        "",
        "This report is public-safe. It does not collect private evidence, archive logs, print node names, expose user names, list tenant names, include private report paths, or claim regulatory certification.",
        "",
        f"- Profile: `{args.profile}`",
        f"- Enabled: `{str(bool_value(profile.get('enabled'), False)).lower()}`",
        f"- Mode: `{profile.get('mode', 'baseline')}`",
        f"- Release tag: `{release_tag}`",
        f"- Evidence root: `{evidence_root}`",
        f"- Control map: `{control_map}`",
        f"- Private evidence index: `{private_index}`",
        f"- Attestation source: `{attestation_source}`",
        f"- Collect reports: `{str(bool_value(evidence.get('collectReports'), False)).lower()}`",
        f"- Require private index: `{str(bool_value(evidence.get('requirePrivateIndex'), False)).lower()}`",
        f"- Require release tag: `{str(bool_value(evidence.get('requireReleaseTag'), False)).lower()}`",
        f"- Require control map: `{str(bool_value(evidence.get('requireControlMap'), False)).lower()}`",
        f"- Require restore drill: `{str(bool_value(evidence.get('requireRestoreDrill'), False)).lower()}`",
        f"- Require access review: `{str(bool_value(evidence.get('requireAccessReview'), False)).lower()}`",
        f"- Require incident drill: `{str(bool_value(evidence.get('requireIncidentDrill'), False)).lower()}`",
        f"- Restore drill evidence: `{str(args.restore_drill_evidence).lower()}`",
        f"- Access review evidence: `{str(args.access_review_evidence).lower()}`",
        f"- Incident drill evidence: `{str(args.incident_drill_evidence).lower()}`",
        f"- Retention enabled: `{str(bool_value(retention.get('enabled'), False)).lower()}`",
        f"- Retention days: `{retention.get('days', 0)}`",
        f"- Retention storage tier: `{retention.get('storageTier', 'none')}`",
        f"- Packaging enabled: `{str(bool_value(packaging.get('enabled'), False)).lower()}`",
        f"- Packaging format: `{packaging.get('format', 'report-only')}`",
        f"- Include checksums: `{str(bool_value(packaging.get('includeChecksums'), False)).lower()}`",
        f"- Include attestations: `{str(bool_value(packaging.get('includeAttestations'), False)).lower()}`",
        f"- Report: `{args.output or controller.get('report', '-')}`",
        f"- Values overlay: `{args.overrides or controller.get('overrides', '-')}`",
        f"- Result: `{result}`",
        "",
        "## Control Families",
        "",
    ]
    if control_families:
        lines.extend([f"- `{item}`" for item in control_families])
    else:
        lines.append("- None selected.")
    lines.extend(["", "## Evidence Sources", ""])
    lines.extend([f"- {item}" for item in sources] or ["- No evidence sources configured."])
    lines.extend(["", "## Required Checks", ""])
    lines.extend([f"- {item}" for item in checks] or ["- No required checks configured."])
    lines.extend(["", "## Findings", ""])
    lines.extend([f"- {item}" for item in findings])
    lines.extend(["", "## Guardrails", ""])
    lines.extend([f"- {item}" for item in guardrails] or ["- Keep private evidence outside Git."])
    lines.extend(
        [
            "",
            "## Next Actions",
            "",
            "- Re-run `make compliance-evidence-plan` after each evidence source or control-map change.",
            "- Keep the generated values overlay disabled until the private evidence owner approves collection, retention, and export rules.",
            "- Store full evidence archives only in approved private storage.",
            "- Attach redacted report summaries to public tickets; keep full private indexes on the trusted operator side.",
            "- Treat this plan as readiness evidence, not a compliance certification.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/compliance-evidence.yaml")
    parser.add_argument("--profile", default="")
    parser.add_argument("--release-tag", default="")
    parser.add_argument("--evidence-root", default="")
    parser.add_argument("--control-map", default="")
    parser.add_argument("--private-evidence-index", default="")
    parser.add_argument("--attestation-source", default="")
    parser.add_argument("--restore-drill-evidence", action="store_true")
    parser.add_argument("--access-review-evidence", action="store_true")
    parser.add_argument("--incident-drill-evidence", action="store_true")
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
    output_path = Path(args.output or controller.get("report", "reports/compliance-evidence-plan.md"))
    overrides_path = Path(args.overrides or controller.get("overrides", "reports/compliance-evidence-values.yaml"))
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    if not overrides_path.is_absolute():
        overrides_path = ROOT / overrides_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generate_report(args, config, profile, findings), encoding="utf-8")
    write_overrides(overrides_path, args.profile, profile, args)
    print(f"Compliance evidence plan written to {output_path.relative_to(ROOT)}")
    print(f"Compliance evidence values written to {overrides_path.relative_to(ROOT)}")
    print(f"Result: {result_from_findings(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
