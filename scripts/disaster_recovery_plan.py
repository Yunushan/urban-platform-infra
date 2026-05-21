#!/usr/bin/env python3
"""Generate a public-safe disaster recovery and business continuity plan."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - CI installs PyYAML; fallback keeps planner portable.
    yaml = None


def parse_scalar(value: str) -> Any:
    stripped = value.strip()
    if stripped in {"true", "false"}:
        return stripped == "true"
    if stripped in {"null", "None", "~"}:
        return None
    if stripped.startswith('"') and stripped.endswith('"'):
        return stripped[1:-1]
    if stripped.startswith("'") and stripped.endswith("'"):
        return stripped[1:-1]
    try:
        return int(stripped)
    except ValueError:
        return stripped


def load_simple_yaml(path: Path) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    pending_key: dict[int, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            item = parse_scalar(line[2:])
            if isinstance(parent, list):
                parent.append(item)
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if value:
            if isinstance(parent, dict):
                parent[key] = parse_scalar(value)
            continue
        next_container: Any = {}
        pending_key[indent] = key
        if isinstance(parent, dict):
            parent[key] = next_container
        stack.append((indent, next_container))
        pending_key[indent] = key
        next_index = path.read_text(encoding="utf-8").splitlines().index(raw_line) + 1
        for future in path.read_text(encoding="utf-8").splitlines()[next_index:]:
            if not future.strip() or future.lstrip().startswith("#"):
                continue
            future_indent = len(future) - len(future.lstrip(" "))
            if future_indent <= indent:
                break
            if future.strip().startswith("- "):
                if isinstance(parent, dict):
                    parent[key] = []
                    stack[-1] = (indent, parent[key])
                break
            break
    return root


def load_yaml(path: Path) -> dict[str, Any]:
    if yaml is not None:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return data if isinstance(data, dict) else {}
    return load_simple_yaml(path)


def as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def bool_value(value: Any, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def display_private(value: str | None, redacted: str, redact: bool) -> str:
    if not value:
        return "-"
    return redacted if redact else value


def result_from_findings(findings: list[str]) -> str:
    if any(item.startswith("ERROR:") for item in findings):
        return "FAIL"
    if any(item.startswith("WARN:") for item in findings):
        return "WARN"
    return "PASS"


def build_findings(args: argparse.Namespace, profile: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    recovery = as_mapping(profile.get("recoveryObjectives"))
    replication = as_mapping(profile.get("replication"))
    drills = as_mapping(profile.get("restoreDrills"))
    continuity = as_mapping(profile.get("continuity"))
    evidence = as_mapping(profile.get("evidence"))

    if not bool_value(profile.get("enabled"), False):
        findings.append("INFO: Disaster recovery automation remains disabled by default.")
    if bool_value(recovery.get("requireRtoRpo"), False) and not args.rto_rpo:
        findings.append("WARN: RTO/RPO objectives must be reviewed before production recovery readiness.")
    if bool_value(recovery.get("requireDependencyMap"), False) and not args.dependency_map:
        findings.append("WARN: Dependency map is required before recovery orchestration is approved.")
    if bool_value(recovery.get("requireCriticalityMap"), False) and not args.criticality_map:
        findings.append("WARN: Service criticality map is required before recovery prioritization is approved.")
    if bool_value(replication.get("requireBackupReplication"), False) and not args.backup_replication:
        findings.append("WARN: Backup replication evidence is required for this profile.")
    if bool_value(replication.get("requireDataReplication"), False) and not args.data_replication:
        findings.append("WARN: Data replication or accepted data-loss decision must be reviewed privately.")
    if bool_value(replication.get("requireCrossZonePlacement"), False) and not args.cross_zone_evidence:
        findings.append("WARN: Cross-zone or recovery-site placement evidence is required.")
    if bool_value(drills.get("requireDatabaseRestore"), False) and not args.database_restore_evidence:
        findings.append("WARN: Database restore drill evidence is required.")
    if bool_value(drills.get("requireEtcdRestore"), False) and not args.etcd_restore_evidence:
        findings.append("WARN: RKE2 etcd restore drill evidence is required.")
    if bool_value(drills.get("requireNamespaceRestore"), False) and not args.namespace_restore_evidence:
        findings.append("WARN: Namespace or platform restore evidence is required.")
    if bool_value(drills.get("requireApplicationSmokeTest"), False) and not args.application_smoke_test:
        findings.append("WARN: Application smoke-test evidence is required after restore.")
    if bool_value(continuity.get("requireRunbook"), False) and not args.runbook_source:
        findings.append("WARN: Failover and recovery runbook source is required.")
    if bool_value(continuity.get("requireCommsPlan"), False) and not args.comms_plan:
        findings.append("WARN: Business continuity communication plan is required.")
    if bool_value(continuity.get("requireManualWorkaround"), False) and not args.manual_workaround:
        findings.append("WARN: Manual workaround or degraded-mode decision is required.")
    if bool_value(continuity.get("requireSupplierContacts"), False) and not args.supplier_contacts:
        findings.append("WARN: Supplier or external dependency contact ownership is required.")
    if bool_value(evidence.get("requireDrillEvidence"), False) and not args.drill_evidence:
        findings.append("WARN: Restore or failover drill evidence is required.")
    if bool_value(evidence.get("requireRtoEvidence"), False) and not args.rto_evidence:
        findings.append("WARN: RTO measurement evidence is required.")
    if bool_value(evidence.get("requirePostDrillReview"), False) and not args.post_drill_review:
        findings.append("WARN: Post-drill review must be recorded before production approval.")
    return findings or ["OK: Disaster recovery settings are internally consistent."]


def write_overrides(path: Path, profile_name: str, profile: dict[str, Any]) -> None:
    recovery = as_mapping(profile.get("recoveryObjectives"))
    replication = as_mapping(profile.get("replication"))
    drills = as_mapping(profile.get("restoreDrills"))
    continuity = as_mapping(profile.get("continuity"))
    evidence = as_mapping(profile.get("evidence"))
    lines = [
        "disasterRecovery:",
        "  enabled: false",
        f"  profile: {profile_name}",
        f"  mode: {profile.get('mode', 'baseline')}",
        f"  tier: {profile.get('tier', 'none')}",
        f"  failoverModel: {profile.get('failoverModel', 'none')}",
        "  recoveryObjectives:",
        f"    enabled: {str(bool_value(recovery.get('enabled'), False)).lower()}",
        f"    requireRtoRpo: {str(bool_value(recovery.get('requireRtoRpo'), False)).lower()}",
        f"    requireDependencyMap: {str(bool_value(recovery.get('requireDependencyMap'), False)).lower()}",
        f"    requireCriticalityMap: {str(bool_value(recovery.get('requireCriticalityMap'), False)).lower()}",
        "  replication:",
        f"    enabled: {str(bool_value(replication.get('enabled'), False)).lower()}",
        f"    requireBackupReplication: {str(bool_value(replication.get('requireBackupReplication'), False)).lower()}",
        f"    requireDataReplication: {str(bool_value(replication.get('requireDataReplication'), False)).lower()}",
        f"    requireCrossZonePlacement: {str(bool_value(replication.get('requireCrossZonePlacement'), False)).lower()}",
        "  restoreDrills:",
        f"    enabled: {str(bool_value(drills.get('enabled'), False)).lower()}",
        f"    requireDatabaseRestore: {str(bool_value(drills.get('requireDatabaseRestore'), False)).lower()}",
        f"    requireEtcdRestore: {str(bool_value(drills.get('requireEtcdRestore'), False)).lower()}",
        f"    requireNamespaceRestore: {str(bool_value(drills.get('requireNamespaceRestore'), False)).lower()}",
        f"    requireApplicationSmokeTest: {str(bool_value(drills.get('requireApplicationSmokeTest'), False)).lower()}",
        "  continuity:",
        f"    enabled: {str(bool_value(continuity.get('enabled'), False)).lower()}",
        f"    requireRunbook: {str(bool_value(continuity.get('requireRunbook'), False)).lower()}",
        f"    requireCommsPlan: {str(bool_value(continuity.get('requireCommsPlan'), False)).lower()}",
        f"    requireManualWorkaround: {str(bool_value(continuity.get('requireManualWorkaround'), False)).lower()}",
        f"    requireSupplierContacts: {str(bool_value(continuity.get('requireSupplierContacts'), False)).lower()}",
        "  evidence:",
        f"    enabled: {str(bool_value(evidence.get('enabled'), False)).lower()}",
        f"    requireDrillEvidence: {str(bool_value(evidence.get('requireDrillEvidence'), False)).lower()}",
        f"    requireRtoEvidence: {str(bool_value(evidence.get('requireRtoEvidence'), False)).lower()}",
        f"    requirePostDrillReview: {str(bool_value(evidence.get('requirePostDrillReview'), False)).lower()}",
        "  reports:",
        "    plan: reports/disaster-recovery-plan.md",
        "    overrides: reports/disaster-recovery-values.yaml",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_report(args: argparse.Namespace, config: dict[str, Any], profile: dict[str, Any], findings: list[str]) -> str:
    controller = as_mapping(config.get("controller"))
    recovery = as_mapping(profile.get("recoveryObjectives"))
    replication = as_mapping(profile.get("replication"))
    drills = as_mapping(profile.get("restoreDrills"))
    continuity = as_mapping(profile.get("continuity"))
    evidence = as_mapping(profile.get("evidence"))
    result = result_from_findings(findings)
    supported = as_list(config.get("supportedStrategies"))
    checks = as_list(config.get("requiredChecks"))
    guardrails = as_list(config.get("guardrails"))

    lines = [
        "# Disaster Recovery And Business Continuity Plan",
        "",
        "This report is public-safe. It does not print real recovery site names, DNS names, node addresses, supplier contacts, customer impact notes, outage timelines, backup bucket names, or private restore evidence.",
        "",
        f"- Profile: `{args.profile}`",
        f"- Enabled: `{str(bool_value(profile.get('enabled'), False)).lower()}`",
        f"- Mode: `{profile.get('mode', 'baseline')}`",
        f"- Tier: `{profile.get('tier', 'none')}`",
        f"- Failover model: `{profile.get('failoverModel', 'none')}`",
        f"- RTO/RPO objectives: `{display_private(args.rto_rpo, '<private-rto-rpo>', args.redact_sensitive)}`",
        f"- Dependency map: `{display_private(args.dependency_map, '<private-dependency-map>', args.redact_sensitive)}`",
        f"- Criticality map: `{display_private(args.criticality_map, '<private-criticality-map>', args.redact_sensitive)}`",
        f"- Backup replication: `{display_private(args.backup_replication, '<private-backup-replication>', args.redact_sensitive)}`",
        f"- Data replication: `{display_private(args.data_replication, '<private-data-replication>', args.redact_sensitive)}`",
        f"- Cross-zone evidence: `{display_private(args.cross_zone_evidence, '<private-cross-zone-evidence>', args.redact_sensitive)}`",
        f"- Database restore evidence: `{display_private(args.database_restore_evidence, '<private-database-restore-evidence>', args.redact_sensitive)}`",
        f"- RKE2 etcd restore evidence: `{display_private(args.etcd_restore_evidence, '<private-etcd-restore-evidence>', args.redact_sensitive)}`",
        f"- Namespace restore evidence: `{display_private(args.namespace_restore_evidence, '<private-namespace-restore-evidence>', args.redact_sensitive)}`",
        f"- Application smoke test: `{display_private(args.application_smoke_test, '<private-application-smoke-test>', args.redact_sensitive)}`",
        f"- Runbook source: `{display_private(args.runbook_source, '<private-runbook-source>', args.redact_sensitive)}`",
        f"- Communications plan: `{display_private(args.comms_plan, '<private-comms-plan>', args.redact_sensitive)}`",
        f"- Manual workaround: `{display_private(args.manual_workaround, '<private-manual-workaround>', args.redact_sensitive)}`",
        f"- Supplier contacts: `{display_private(args.supplier_contacts, '<private-supplier-contacts>', args.redact_sensitive)}`",
        f"- Drill evidence: `{display_private(args.drill_evidence, '<private-drill-evidence>', args.redact_sensitive)}`",
        f"- RTO evidence: `{display_private(args.rto_evidence, '<private-rto-evidence>', args.redact_sensitive)}`",
        f"- Post-drill review: `{str(args.post_drill_review).lower()}`",
        f"- Require RTO/RPO: `{str(bool_value(recovery.get('requireRtoRpo'), False)).lower()}`",
        f"- Require backup replication: `{str(bool_value(replication.get('requireBackupReplication'), False)).lower()}`",
        f"- Require database restore: `{str(bool_value(drills.get('requireDatabaseRestore'), False)).lower()}`",
        f"- Require application smoke test: `{str(bool_value(drills.get('requireApplicationSmokeTest'), False)).lower()}`",
        f"- Require continuity runbook: `{str(bool_value(continuity.get('requireRunbook'), False)).lower()}`",
        f"- Evidence enabled: `{str(bool_value(evidence.get('enabled'), False)).lower()}`",
        f"- Report: `{args.output or controller.get('report', '-')}`",
        f"- Values overlay: `{args.overrides or controller.get('overrides', '-')}`",
        f"- Result: `{result}`",
        "",
        "## Supported Strategies",
        "",
    ]
    lines.extend([f"- `{item}`" for item in supported] or ["- `none`"])
    lines.extend(["", "## Required Checks", ""])
    lines.extend([f"- {item}" for item in checks] or ["- No required checks configured."])
    lines.extend(["", "## Findings", ""])
    lines.extend([f"- {item}" for item in findings])
    lines.extend(["", "## Guardrails", ""])
    lines.extend([f"- {item}" for item in guardrails] or ["- Keep private recovery data outside Git."])
    lines.extend(
        [
            "",
            "## Next Actions",
            "",
            "- Re-run `make disaster-recovery-plan` after backup policy, recovery topology, or critical workload scope changes.",
            "- Keep the generated values overlay disabled until private DR owners approve the workflow.",
            "- Store recovery site names, DNS changes, supplier contacts, drill logs, and outage timelines only in approved private systems.",
            "- Link private restore drill and RTO evidence into the compliance evidence plan before production continuity claims.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a public-safe disaster recovery and business continuity plan.")
    parser.add_argument("--config", default="config/disaster-recovery.yaml")
    parser.add_argument("--profile", default="")
    parser.add_argument("--rto-rpo", default="")
    parser.add_argument("--dependency-map", default="")
    parser.add_argument("--criticality-map", default="")
    parser.add_argument("--backup-replication", default="")
    parser.add_argument("--data-replication", default="")
    parser.add_argument("--cross-zone-evidence", default="")
    parser.add_argument("--database-restore-evidence", default="")
    parser.add_argument("--etcd-restore-evidence", default="")
    parser.add_argument("--namespace-restore-evidence", default="")
    parser.add_argument("--application-smoke-test", default="")
    parser.add_argument("--runbook-source", default="")
    parser.add_argument("--comms-plan", default="")
    parser.add_argument("--manual-workaround", default="")
    parser.add_argument("--supplier-contacts", default="")
    parser.add_argument("--drill-evidence", default="")
    parser.add_argument("--rto-evidence", default="")
    parser.add_argument("--post-drill-review", action="store_true")
    parser.add_argument("--output", default="")
    parser.add_argument("--overrides", default="")
    parser.add_argument("--redact-sensitive", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    config = load_yaml(config_path)
    profiles = as_mapping(config.get("profiles"))
    profile_name = args.profile or str(config.get("defaultProfile", "disabled"))
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown disaster recovery profile `{profile_name}`. Available profiles: {choices}")
    args.profile = profile_name
    profile = as_mapping(profiles[profile_name])
    controller = as_mapping(config.get("controller"))
    output_path = Path(args.output or controller.get("report", "reports/disaster-recovery-plan.md"))
    overrides_path = Path(args.overrides or controller.get("overrides", "reports/disaster-recovery-values.yaml"))
    findings = build_findings(args, profile)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generate_report(args, config, profile, findings), encoding="utf-8")
    write_overrides(overrides_path, profile_name, profile)
    print(f"Disaster recovery plan written to {output_path}")
    print(f"Disaster recovery values written to {overrides_path}")
    print(f"Result: {result_from_findings(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
