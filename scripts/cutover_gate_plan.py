#!/usr/bin/env python3
"""Generate a public-safe production cutover and smoke-test gate plan."""
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


def as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def select_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = as_mapping(config.get("profiles"))
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown cutover gate profile `{profile_name}`. Available profiles: {choices}")
    profile = profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Cutover gate profile `{profile_name}` must be a mapping.")
    return profile


def display_private(value: str, replacement: str, redact: bool) -> str:
    if not value:
        return "-"
    if value in {"-", "none"}:
        return value
    return replacement if redact else value


def relative_artifact_path(path: str, import_output: Path) -> Path:
    artifact = Path(path)
    if artifact.is_absolute():
        return artifact
    if path.startswith("reports/import-migration/"):
        suffix = Path(path).relative_to("reports/import-migration")
        return import_output / suffix
    return ROOT / artifact


def artifact_rows(config: dict[str, Any], import_output: Path) -> list[tuple[str, bool]]:
    rows: list[tuple[str, bool]] = []
    for item in as_list(config.get("publicArtifacts")):
        text = str(item)
        rows.append((text, relative_artifact_path(text, import_output).exists()))
    return rows


def profile_findings(args: argparse.Namespace, profile: dict[str, Any], artifact_status: list[tuple[str, bool]]) -> list[str]:
    findings: list[str] = []
    traffic = as_mapping(profile.get("trafficSwitch"))
    pre_cutover = as_mapping(profile.get("preCutover"))
    smoke_tests = as_mapping(profile.get("smokeTests"))
    rollback = as_mapping(profile.get("rollback"))
    post_cutover = as_mapping(profile.get("postCutover"))

    if not bool_value(profile.get("enabled"), False):
        findings.append(f"INFO: Profile `{args.profile}` is plan-only; committed values keep cutover automation disabled.")
    if bool_value(traffic.get("requireIngressHost"), False) and not args.ingress_host:
        findings.append("WARN: Ingress host or cutover DNS target is required before traffic switch.")
    if bool_value(traffic.get("requireDnsTlsEvidence"), False) and not args.dns_tls_evidence:
        findings.append("WARN: DNS and TLS cutover evidence is required before production traffic switch.")
    if bool_value(pre_cutover.get("requireChangeTicket"), False) and not args.change_ticket:
        findings.append("WARN: Change ticket or release record is required before cutover approval.")
    if bool_value(pre_cutover.get("requireApprovalEvidence"), False) and not args.approval_evidence:
        findings.append("WARN: Approval evidence is required before production cutover.")
    if bool_value(pre_cutover.get("requireReleaseEvidence"), False) and not args.release_evidence:
        findings.append("WARN: Release evidence verification must be attached before cutover.")
    if bool_value(pre_cutover.get("requireRegistryEvidence"), False) and not args.registry_evidence:
        findings.append("WARN: Registry promotion or preload evidence must be reviewed before cutover.")
    if bool_value(pre_cutover.get("requireBackupRestoreEvidence"), False) and not args.backup_restore_evidence:
        findings.append("WARN: Backup and restore evidence must be reviewed before cutover.")
    if bool_value(pre_cutover.get("requireDatabaseRestoreEvidence"), False) and not args.database_restore_evidence:
        findings.append("WARN: Database restore validation evidence is required before cutover.")
    if bool_value(smoke_tests.get("requireSmokeTestPlan"), False) and not args.smoke_test_plan:
        findings.append("WARN: Smoke-test plan is required before cutover.")
    if bool_value(rollback.get("requireRollbackPlan"), False) and not args.rollback_plan:
        findings.append("WARN: Rollback plan is required before cutover.")
    if bool_value(rollback.get("requireRestorePoint"), False) and not args.restore_point_evidence:
        findings.append("WARN: Restore point or snapshot evidence is required before cutover.")
    if bool_value(post_cutover.get("requireObservationWindow"), False) and not args.post_cutover_window:
        findings.append("WARN: Post-cutover observation window is required before traffic switch.")
    if bool_value(post_cutover.get("requireOwnerHandoff"), False) and not args.owner_handoff:
        findings.append("WARN: Post-cutover owner handoff must be identified.")

    required_artifacts = {
        "requireImportPreflight": "reports/import-migration/import-preflight.md",
        "requireCapacityReport": "reports/import-migration/import-capacity.md",
        "requireRecoveryPlan": "reports/import-migration/import-recovery-plan.md",
        "requirePostMigrationCheck": "reports/import-migration/post-migration-check.md",
    }
    present = {path: exists for path, exists in artifact_status}
    for key, artifact in required_artifacts.items():
        if bool_value(pre_cutover.get(key), False) or bool_value(rollback.get(key), False) or bool_value(smoke_tests.get(key), False):
            if not present.get(artifact, False):
                findings.append(f"WARN: Required public artifact is missing: `{artifact}`.")

    return findings or ["OK: Cutover gate settings are internally consistent."]


def result_from_findings(findings: list[str]) -> str:
    if any(item.startswith("ERROR:") for item in findings):
        return "FAIL"
    if any(item.startswith("WARN:") for item in findings):
        return "WARN"
    return "PASS"


def write_overrides(path: Path, profile_name: str, profile: dict[str, Any]) -> None:
    traffic = as_mapping(profile.get("trafficSwitch"))
    pre_cutover = as_mapping(profile.get("preCutover"))
    smoke_tests = as_mapping(profile.get("smokeTests"))
    rollback = as_mapping(profile.get("rollback"))
    post_cutover = as_mapping(profile.get("postCutover"))
    lines = [
        "cutoverGates:",
        "  enabled: false",
        f"  profile: {profile_name}",
        f"  mode: {profile.get('mode', 'baseline')}",
        "  trafficSwitch:",
        f"    enabled: {str(bool_value(traffic.get('enabled'), False)).lower()}",
        f"    method: {traffic.get('method', 'none')}",
        f"    requireIngressHost: {str(bool_value(traffic.get('requireIngressHost'), False)).lower()}",
        f"    requireDnsTlsEvidence: {str(bool_value(traffic.get('requireDnsTlsEvidence'), False)).lower()}",
        "  preCutover:",
        f"    requireImportPreflight: {str(bool_value(pre_cutover.get('requireImportPreflight'), False)).lower()}",
        f"    requireCapacityReport: {str(bool_value(pre_cutover.get('requireCapacityReport'), False)).lower()}",
        f"    requireReleaseEvidence: {str(bool_value(pre_cutover.get('requireReleaseEvidence'), False)).lower()}",
        f"    requireRegistryEvidence: {str(bool_value(pre_cutover.get('requireRegistryEvidence'), False)).lower()}",
        f"    requireBackupRestoreEvidence: {str(bool_value(pre_cutover.get('requireBackupRestoreEvidence'), False)).lower()}",
        f"    requireDatabaseRestoreEvidence: {str(bool_value(pre_cutover.get('requireDatabaseRestoreEvidence'), False)).lower()}",
        f"    requireChangeTicket: {str(bool_value(pre_cutover.get('requireChangeTicket'), False)).lower()}",
        f"    requireApprovalEvidence: {str(bool_value(pre_cutover.get('requireApprovalEvidence'), False)).lower()}",
        "  smokeTests:",
        f"    enabled: {str(bool_value(smoke_tests.get('enabled'), False)).lower()}",
        f"    requireSmokeTestPlan: {str(bool_value(smoke_tests.get('requireSmokeTestPlan'), False)).lower()}",
        f"    requirePostMigrationCheck: {str(bool_value(smoke_tests.get('requirePostMigrationCheck'), False)).lower()}",
        f"    requireSyntheticChecks: {str(bool_value(smoke_tests.get('requireSyntheticChecks'), False)).lower()}",
        "  rollback:",
        f"    enabled: {str(bool_value(rollback.get('enabled'), False)).lower()}",
        f"    requireRollbackPlan: {str(bool_value(rollback.get('requireRollbackPlan'), False)).lower()}",
        f"    requireRecoveryPlan: {str(bool_value(rollback.get('requireRecoveryPlan'), False)).lower()}",
        f"    requireRestorePoint: {str(bool_value(rollback.get('requireRestorePoint'), False)).lower()}",
        "  postCutover:",
        f"    enabled: {str(bool_value(post_cutover.get('enabled'), False)).lower()}",
        f"    requireObservationWindow: {str(bool_value(post_cutover.get('requireObservationWindow'), False)).lower()}",
        f"    requireOwnerHandoff: {str(bool_value(post_cutover.get('requireOwnerHandoff'), False)).lower()}",
        "  reports:",
        "    plan: reports/cutover-gate-plan.md",
        "    overrides: reports/cutover-gate-values.yaml",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_report(
    args: argparse.Namespace,
    config: dict[str, Any],
    profile: dict[str, Any],
    artifact_status: list[tuple[str, bool]],
    findings: list[str],
) -> str:
    traffic = as_mapping(profile.get("trafficSwitch"))
    pre_cutover = as_mapping(profile.get("preCutover"))
    smoke_tests = as_mapping(profile.get("smokeTests"))
    rollback = as_mapping(profile.get("rollback"))
    post_cutover = as_mapping(profile.get("postCutover"))
    result = result_from_findings(findings)
    ingress_host = display_private(args.ingress_host, "<private-ingress-host>", args.redact_sensitive)
    change_ticket = display_private(args.change_ticket, "<private-change-ticket>", args.redact_sensitive)
    approval_evidence = display_private(args.approval_evidence, "<private-approval-evidence>", args.redact_sensitive)
    rollback_plan = display_private(args.rollback_plan, "<private-rollback-plan>", args.redact_sensitive)
    smoke_test_plan = display_private(args.smoke_test_plan, "<private-smoke-test-plan>", args.redact_sensitive)
    release_evidence = display_private(args.release_evidence, "<private-release-evidence>", args.redact_sensitive)
    registry_evidence = display_private(args.registry_evidence, "<private-registry-evidence>", args.redact_sensitive)
    backup_evidence = display_private(args.backup_restore_evidence, "<private-backup-restore-evidence>", args.redact_sensitive)
    database_evidence = display_private(args.database_restore_evidence, "<private-database-restore-evidence>", args.redact_sensitive)
    restore_point = display_private(args.restore_point_evidence, "<private-restore-point-evidence>", args.redact_sensitive)

    lines = [
        "# Production Cutover And Smoke-Test Gate Plan",
        "",
        "This report is public-safe. It does not switch traffic, modify DNS, approve a change ticket, run customer-facing smoke tests, print private hosts, expose registry paths, show database DSNs, or include secret values.",
        "",
        f"- Profile: `{args.profile}`",
        f"- Enabled: `{str(bool_value(profile.get('enabled'), False)).lower()}`",
        f"- Mode: `{profile.get('mode', 'baseline')}`",
        f"- Namespace: `{args.namespace}`",
        f"- Ingress host: `{ingress_host}`",
        f"- Traffic switch method: `{traffic.get('method', 'none')}`",
        f"- DNS/TLS evidence: `{str(args.dns_tls_evidence).lower()}`",
        f"- Change ticket: `{change_ticket}`",
        f"- Approval evidence: `{approval_evidence}`",
        f"- Release evidence: `{release_evidence}`",
        f"- Registry/preload evidence: `{registry_evidence}`",
        f"- Backup/restore evidence: `{backup_evidence}`",
        f"- Database restore evidence: `{database_evidence}`",
        f"- Smoke-test plan: `{smoke_test_plan}`",
        f"- Rollback plan: `{rollback_plan}`",
        f"- Restore point evidence: `{restore_point}`",
        f"- Post-cutover observation window: `{args.post_cutover_window or '-'}`",
        f"- Owner handoff: `{str(args.owner_handoff).lower()}`",
        f"- Result: `{result}`",
        "",
        "## Public Artifacts",
        "",
        "| Artifact | Present |",
        "|---|---|",
    ]
    for artifact, present in artifact_status:
        lines.append(f"| `{artifact}` | `{str(present).lower()}` |")
    lines.extend(
        [
            "",
            "## Gate Requirements",
            "",
            f"- Require ingress host: `{str(bool_value(traffic.get('requireIngressHost'), False)).lower()}`",
            f"- Require DNS/TLS evidence: `{str(bool_value(traffic.get('requireDnsTlsEvidence'), False)).lower()}`",
            f"- Require import preflight: `{str(bool_value(pre_cutover.get('requireImportPreflight'), False)).lower()}`",
            f"- Require capacity report: `{str(bool_value(pre_cutover.get('requireCapacityReport'), False)).lower()}`",
            f"- Require release evidence: `{str(bool_value(pre_cutover.get('requireReleaseEvidence'), False)).lower()}`",
            f"- Require registry evidence: `{str(bool_value(pre_cutover.get('requireRegistryEvidence'), False)).lower()}`",
            f"- Require backup/restore evidence: `{str(bool_value(pre_cutover.get('requireBackupRestoreEvidence'), False)).lower()}`",
            f"- Require database restore evidence: `{str(bool_value(pre_cutover.get('requireDatabaseRestoreEvidence'), False)).lower()}`",
            f"- Require smoke-test plan: `{str(bool_value(smoke_tests.get('requireSmokeTestPlan'), False)).lower()}`",
            f"- Require post-migration check: `{str(bool_value(smoke_tests.get('requirePostMigrationCheck'), False)).lower()}`",
            f"- Require synthetic checks: `{str(bool_value(smoke_tests.get('requireSyntheticChecks'), False)).lower()}`",
            f"- Require rollback plan: `{str(bool_value(rollback.get('requireRollbackPlan'), False)).lower()}`",
            f"- Require recovery plan: `{str(bool_value(rollback.get('requireRecoveryPlan'), False)).lower()}`",
            f"- Require restore point: `{str(bool_value(rollback.get('requireRestorePoint'), False)).lower()}`",
            f"- Require observation window: `{str(bool_value(post_cutover.get('requireObservationWindow'), False)).lower()}`",
            f"- Require owner handoff: `{str(bool_value(post_cutover.get('requireOwnerHandoff'), False)).lower()}`",
            "",
            "## Findings",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in findings)
    lines.extend(["", "## Required Checks", ""])
    lines.extend(f"- {item}" for item in as_list(config.get("requiredChecks")))
    lines.extend(["", "## Guardrails", ""])
    lines.extend(f"- {item}" for item in as_list(config.get("guardrails")))
    lines.extend(
        [
            "",
            "## Operator Commands",
            "",
            "```bash",
            "make cutover-gate-plan CUTOVER_GATES_PROFILE=production-cutover IMPORT_REDACT=true",
            "make import-preflight PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true",
            "make import-recovery-plan IMPORT_REDACT=true",
            "make change-management-plan CHANGE_MANAGEMENT_PROFILE=production-cab IMPORT_REDACT=true",
            "make progressive-delivery-plan PROGRESSIVE_DELIVERY_PROFILE=production-canary IMPORT_REDACT=true",
            "```",
            "",
            "## Next Actions",
            "",
            "- Keep cutover gates plan-only until private evidence, DNS/TLS ownership, rollback owner, and smoke-test ownership are reviewed.",
            "- Run the gate again after every import batch, database restore rehearsal, release evidence update, or DNS/TLS change.",
            "- Store real smoke-test URLs, tickets, approvers, database restore evidence, and rollback evidence only in approved private systems.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/cutover-gates.yaml")
    parser.add_argument("--profile", default="")
    parser.add_argument("--namespace", default="urban-platform")
    parser.add_argument("--ingress-host", default="")
    parser.add_argument("--import-output", default="reports/import-migration")
    parser.add_argument("--change-ticket", default="")
    parser.add_argument("--approval-evidence", default="")
    parser.add_argument("--rollback-plan", default="")
    parser.add_argument("--smoke-test-plan", default="")
    parser.add_argument("--release-evidence", default="")
    parser.add_argument("--registry-evidence", default="")
    parser.add_argument("--backup-restore-evidence", default="")
    parser.add_argument("--database-restore-evidence", default="")
    parser.add_argument("--restore-point-evidence", default="")
    parser.add_argument("--post-cutover-window", default="")
    parser.add_argument("--dns-tls-evidence", action="store_true")
    parser.add_argument("--owner-handoff", action="store_true")
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
    controller = as_mapping(config.get("controller"))
    output_path = Path(args.output or controller.get("report", "reports/cutover-gate-plan.md"))
    overrides_path = Path(args.overrides or controller.get("overrides", "reports/cutover-gate-values.yaml"))
    import_output = Path(args.import_output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    if not overrides_path.is_absolute():
        overrides_path = ROOT / overrides_path
    if not import_output.is_absolute():
        import_output = ROOT / import_output
    artifacts = artifact_rows(config, import_output)
    findings = profile_findings(args, profile, artifacts)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generate_report(args, config, profile, artifacts, findings), encoding="utf-8")
    write_overrides(overrides_path, args.profile, profile)
    print(f"Cutover gate plan written to {output_path.relative_to(ROOT)}")
    print(f"Cutover gate values written to {overrides_path.relative_to(ROOT)}")
    print(f"Result: {result_from_findings(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
