#!/usr/bin/env python3
"""Generate a public-safe access governance, RBAC, and tenant isolation plan."""
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


def select_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = config.get("profiles", {})
    if not isinstance(profiles, dict):
        raise SystemExit("Access governance config must contain a profiles mapping.")
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown access governance profile `{profile_name}`. Available profiles: {choices}")
    profile = profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Access governance profile `{profile_name}` must be a mapping.")
    return profile


def profile_findings(profile_name: str, profile: dict[str, Any], args: argparse.Namespace) -> list[str]:
    findings: list[str] = []
    rbac = as_mapping(profile.get("rbac"))
    identity = as_mapping(profile.get("identity"))
    audit = as_mapping(profile.get("audit"))
    break_glass = as_mapping(profile.get("breakGlass"))
    tenant_isolation = as_mapping(profile.get("tenantIsolation"))

    if not bool_value(profile.get("enabled"), False):
        findings.append(f"INFO: Profile `{profile_name}` is plan-only; committed values keep additional access automation disabled.")
    if bool_value(profile.get("requireRbacInventory"), False) and not args.rbac_inventory:
        findings.append("WARN: Production access governance requires a private RBAC inventory before applying least-privilege roles.")
    if bool_value(profile.get("requireIdentityProvider"), False) and not args.identity_provider:
        findings.append("WARN: OIDC or SSO readiness requires a private identity provider reference.")
    if bool_value(profile.get("requireGroupMapping"), False) and not args.group_mapping:
        findings.append("WARN: Group-to-role mapping evidence is required before production OIDC authorization.")
    if bool_value(profile.get("requireAuditEvidence"), False) and not args.audit_evidence:
        findings.append("WARN: Kubernetes audit policy and retention evidence is required before production enforcement.")
    if bool_value(profile.get("requireBreakGlassReview"), False) and not args.break_glass_review:
        findings.append("WARN: Break-glass access must be time-boxed, reviewed, and stored outside Git.")
    if bool_value(profile.get("requireTenantModel"), False) and not args.tenant_model:
        findings.append("WARN: Multi-tenant mode requires a private tenant and namespace ownership model.")
    if bool_value(rbac.get("requireLeastPrivilege"), False):
        findings.append("INFO: Least-privilege RBAC should start from read-only inventory and targeted RoleBindings.")
    if bool_value(identity.get("requireMfa"), False) and not args.identity_provider:
        findings.append("WARN: MFA requirement needs an external identity provider or Keycloak ownership plan.")
    if bool_value(audit.get("requireAuditPolicy"), False) and not args.audit_evidence:
        findings.append("WARN: Audit policy, log retention, and sensitive-field redaction must be reviewed privately.")
    if bool_value(tenant_isolation.get("requireNamespaceContract"), False) and not args.tenant_model:
        findings.append("WARN: Namespace isolation needs quota, NetworkPolicy, secret, and GitOps ownership contracts.")
    if bool_value(break_glass.get("requireTimeBoxedAccess"), True):
        findings.append("INFO: Break-glass access should be time-boxed and followed by a post-use review.")
    return findings or ["OK: Access governance settings are internally consistent."]


def result_from_findings(findings: list[str]) -> str:
    if any(item.startswith("ERROR:") for item in findings):
        return "FAIL"
    if any(item.startswith("WARN:") for item in findings):
        return "WARN"
    return "PASS"


def write_overrides(path: Path, profile_name: str, profile: dict[str, Any], args: argparse.Namespace) -> None:
    rbac = as_mapping(profile.get("rbac"))
    identity = as_mapping(profile.get("identity"))
    audit = as_mapping(profile.get("audit"))
    break_glass = as_mapping(profile.get("breakGlass"))
    tenant_isolation = as_mapping(profile.get("tenantIsolation"))
    provider = args.identity_provider or identity.get("provider", "none")
    lines = [
        "accessGovernance:",
        "  enabled: false",
        f"  profile: {profile_name}",
        f"  mode: {profile.get('mode', 'baseline')}",
        "  rbac:",
        f"    enabled: {str(bool_value(rbac.get('enabled'), False)).lower()}",
        f"    strategy: {rbac.get('strategy', 'existing-serviceaccount')}",
        f"    requireLeastPrivilege: {str(bool_value(rbac.get('requireLeastPrivilege'), False)).lower()}",
        f"    serviceAccountTokenAutomount: {str(bool_value(rbac.get('serviceAccountTokenAutomount'), False)).lower()}",
        "  identity:",
        f"    enabled: {str(bool_value(identity.get('enabled'), False)).lower()}",
        f"    provider: {provider}",
        f"    requireMfa: {str(bool_value(identity.get('requireMfa'), False)).lower()}",
        f"    requireGroupMapping: {str(bool_value(identity.get('requireGroupMapping'), False)).lower()}",
        "  audit:",
        f"    enabled: {str(bool_value(audit.get('enabled'), False)).lower()}",
        f"    mode: {audit.get('mode', 'platform-default')}",
        f"    requireAuditPolicy: {str(bool_value(audit.get('requireAuditPolicy'), False)).lower()}",
        "  breakGlass:",
        f"    enabled: {str(bool_value(break_glass.get('enabled'), False)).lower()}",
        f"    requireTimeBoxedAccess: {str(bool_value(break_glass.get('requireTimeBoxedAccess'), True)).lower()}",
        f"    requireReview: {str(bool_value(break_glass.get('requireReview'), False)).lower()}",
        "  tenantIsolation:",
        f"    enabled: {str(bool_value(tenant_isolation.get('enabled'), False)).lower()}",
        f"    mode: {tenant_isolation.get('mode', 'single-namespace')}",
        f"    requireNamespaceContract: {str(bool_value(tenant_isolation.get('requireNamespaceContract'), False)).lower()}",
        "  reports:",
        "    plan: reports/access-governance-plan.md",
        "    overrides: reports/access-governance-values.yaml",
        "global:",
        "  serviceAccount:",
        "    automountServiceAccountToken: false",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def display_private(value: str, replacement: str, redact: bool) -> str:
    if not value:
        return "-"
    if value in {"-", "none"}:
        return value
    return replacement if redact else value


def generate_report(args: argparse.Namespace, config: dict[str, Any], profile: dict[str, Any], findings: list[str]) -> str:
    controller = as_mapping(config.get("controller"))
    checks = config.get("requiredChecks", [])
    guardrails = config.get("guardrails", [])
    if not isinstance(checks, list):
        checks = []
    if not isinstance(guardrails, list):
        guardrails = []
    rbac = as_mapping(profile.get("rbac"))
    identity = as_mapping(profile.get("identity"))
    audit = as_mapping(profile.get("audit"))
    break_glass = as_mapping(profile.get("breakGlass"))
    tenant_isolation = as_mapping(profile.get("tenantIsolation"))
    result = result_from_findings(findings)
    identity_provider = display_private(args.identity_provider or str(identity.get("provider", "none")), "<private-identity-provider>", args.redact_sensitive)
    group_mapping = display_private(args.group_mapping, "<private-group-mapping>", args.redact_sensitive)
    tenant_model = display_private(args.tenant_model, "<private-tenant-model>", args.redact_sensitive)
    rbac_inventory = display_private(args.rbac_inventory, "<private-rbac-inventory>", args.redact_sensitive)
    lines = [
        "# Access Governance And Tenant Isolation Plan",
        "",
        "This report is public-safe. It does not create RBAC resources, configure OIDC, print user names, expose group names, list tenant names, or include identity provider URLs.",
        "",
        f"- Profile: `{args.profile}`",
        f"- Enabled: `{str(bool_value(profile.get('enabled'), False)).lower()}`",
        f"- Mode: `{profile.get('mode', 'baseline')}`",
        f"- RBAC enabled: `{str(bool_value(rbac.get('enabled'), False)).lower()}`",
        f"- RBAC strategy: `{rbac.get('strategy', '-')}`",
        f"- Require least privilege: `{str(bool_value(rbac.get('requireLeastPrivilege'), False)).lower()}`",
        f"- Service account token automount: `{str(bool_value(rbac.get('serviceAccountTokenAutomount'), False)).lower()}`",
        f"- Identity enabled: `{str(bool_value(identity.get('enabled'), False)).lower()}`",
        f"- Identity provider: `{identity_provider}`",
        f"- Require MFA: `{str(bool_value(identity.get('requireMfa'), False)).lower()}`",
        f"- Require group mapping: `{str(bool_value(identity.get('requireGroupMapping'), False)).lower()}`",
        f"- Audit mode: `{audit.get('mode', '-')}`",
        f"- Require audit policy: `{str(bool_value(audit.get('requireAuditPolicy'), False)).lower()}`",
        f"- Break-glass review required: `{str(bool_value(break_glass.get('requireReview'), False)).lower()}`",
        f"- Tenant isolation mode: `{tenant_isolation.get('mode', '-')}`",
        f"- Tenant namespace contract required: `{str(bool_value(tenant_isolation.get('requireNamespaceContract'), False)).lower()}`",
        f"- RBAC inventory: `{rbac_inventory}`",
        f"- Group mapping: `{group_mapping}`",
        f"- Tenant model: `{tenant_model}`",
        f"- Audit evidence: `{str(args.audit_evidence).lower()}`",
        f"- Break-glass review: `{str(args.break_glass_review).lower()}`",
        f"- Report: `{args.output or controller.get('report', '-')}`",
        f"- Values overlay: `{args.overrides or controller.get('overrides', '-')}`",
        f"- Result: `{result}`",
        "",
        "## Required Checks",
        "",
    ]
    for check in checks:
        lines.append(f"- {check}")
    lines.extend(["", "## Findings", ""])
    for finding in findings:
        lines.append(f"- {finding}")
    lines.extend(["", "## Guardrails", ""])
    for guardrail in guardrails:
        lines.append(f"- {guardrail}")
    lines.extend(
        [
            "",
            "## Recommended Sequence",
            "",
            "1. Keep service account token automount disabled by default.",
            "2. Inventory existing operator, workload, and migration permissions privately.",
            "3. Convert broad permissions into namespace-scoped Roles and RoleBindings.",
            "4. Add OIDC or Keycloak group mapping only after MFA and audit retention are reviewed.",
            "5. Move to tenant isolation only after quota, NetworkPolicy, secret, and GitOps ownership are defined.",
            "",
            "## Example Commands",
            "",
            "```bash",
            "make access-governance-plan ACCESS_GOVERNANCE_PROFILE=lab-audit IMPORT_REDACT=true",
            "make access-governance-plan ACCESS_GOVERNANCE_PROFILE=production-rbac ACCESS_GOVERNANCE_AUDIT_EVIDENCE=true ACCESS_GOVERNANCE_BREAK_GLASS_REVIEW=true IMPORT_REDACT=true",
            "make access-governance-plan ACCESS_GOVERNANCE_PROFILE=oidc-sso ACCESS_GOVERNANCE_IDENTITY_PROVIDER=keycloak ACCESS_GOVERNANCE_GROUP_MAPPING=reviewed IMPORT_REDACT=true",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe access governance, RBAC, and tenant isolation plan.")
    parser.add_argument("--config", default="config/access-governance.yaml")
    parser.add_argument("--profile", default="")
    parser.add_argument("--identity-provider", default="")
    parser.add_argument("--group-mapping", default="")
    parser.add_argument("--tenant-model", default="")
    parser.add_argument("--rbac-inventory", default="")
    parser.add_argument("--audit-evidence", action="store_true")
    parser.add_argument("--break-glass-review", action="store_true")
    parser.add_argument("--output", default="reports/access-governance-plan.md")
    parser.add_argument("--overrides", default="reports/access-governance-values.yaml")
    parser.add_argument("--redact-sensitive", action="store_true")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    output_path = Path(args.output)
    overrides_path = Path(args.overrides)
    if not config_path.is_absolute():
        config_path = (ROOT / config_path).resolve()
    if not output_path.is_absolute():
        output_path = (ROOT / output_path).resolve()
    if not overrides_path.is_absolute():
        overrides_path = (ROOT / overrides_path).resolve()

    config = load_yaml_file(config_path)
    args.profile = args.profile or str(config.get("defaultProfile", "disabled"))
    profile = select_profile(config, args.profile)
    findings = profile_findings(args.profile, profile, args)
    write_overrides(overrides_path, args.profile, profile, args)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generate_report(args, config, profile, findings), encoding="utf-8")
    print(f"Access governance plan written: {output_path}")
    print(f"Access governance values overlay written: {overrides_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
