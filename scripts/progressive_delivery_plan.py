#!/usr/bin/env python3
"""Generate a public-safe progressive delivery and rollback plan."""
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


def select_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = config.get("profiles", {})
    if not isinstance(profiles, dict):
        raise SystemExit("Progressive delivery config must contain a profiles mapping.")
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown progressive delivery profile `{profile_name}`. Available profiles: {choices}")
    profile = profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Progressive delivery profile `{profile_name}` must be a mapping.")
    return profile


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def profile_findings(profile_name: str, profile: dict[str, Any], args: argparse.Namespace) -> list[str]:
    findings: list[str] = []
    enabled = bool_value(profile.get("enabled"), False)
    controller = str(profile.get("controller", "none"))
    strategy = str(profile.get("strategy", "rolling-update"))
    analysis_mode = str(profile.get("analysisMode", "disabled"))
    canary_steps = list_value(profile.get("canarySteps", []))

    if not enabled:
        findings.append(f"INFO: Profile `{profile_name}` is disabled; standard Helm rollout and manual rollback remain the default.")
    if strategy == "canary" and not canary_steps:
        findings.append("ERROR: Canary profile must define canary steps.")
    if controller in {"argo-rollouts", "flagger"}:
        findings.append(f"WARN: `{controller}` must be installed and owned through a private operator/GitOps path before this profile is enabled.")
    if bool_value(profile.get("requireGitOps"), False) and not args.gitops_profile:
        findings.append("WARN: Production progressive delivery should be tied to a reviewed GitOps delivery profile.")
    if bool_value(profile.get("requireMetrics"), False) and analysis_mode != "automated":
        findings.append("ERROR: Metrics are required but automated analysis is not selected.")
    if bool_value(profile.get("requireSlo"), False) and not args.slo_source:
        findings.append("WARN: Production progressive delivery requires private SLO metric queries or analysis templates.")
    if bool_value(profile.get("requireRollbackDrill"), False) and not args.rollback_drill:
        findings.append("WARN: Rollback drill evidence is required before trusting automatic rollback.")
    if bool_value(profile.get("requireTrafficSplitting"), False) and str(profile.get("trafficProvider", "native")) == "native":
        findings.append("ERROR: Traffic splitting is required but traffic provider is native.")
    if bool_value(profile.get("autoPromotion"), False):
        findings.append("WARN: Automatic promotion is enabled; confirm SLO gates and rollback automation first.")
    if args.runtime_profile and args.runtime_profile in {"production-restricted", "enterprise-signed"}:
        findings.append("INFO: Runtime hardening profile is production-oriented; verify rollout controller pods satisfy the same policy.")
    return findings or ["OK: Progressive delivery settings are internally consistent."]


def result_from_findings(findings: list[str]) -> str:
    if any(item.startswith("ERROR:") for item in findings):
        return "FAIL"
    if any(item.startswith("WARN:") for item in findings):
        return "WARN"
    return "PASS"


def write_overrides(path: Path, profile_name: str, profile: dict[str, Any]) -> None:
    steps = list_value(profile.get("canarySteps", []))
    lines = [
        "progressiveDelivery:",
        "  enabled: false",
        f"  profile: {profile_name}",
        f"  strategy: {profile.get('strategy', 'rolling-update')}",
        f"  controller: {profile.get('controller', 'none')}",
        f"  trafficProvider: {profile.get('trafficProvider', 'native')}",
        "  analysis:",
        f"    enabled: {str(str(profile.get('analysisMode', 'disabled')) != 'disabled').lower()}",
        f"    mode: {profile.get('analysisMode', 'disabled')}",
        "    metrics: []",
        "  canary:",
        f"    enabled: {str(profile.get('strategy') == 'canary').lower()}",
        f"    maxUnavailable: {profile.get('maxUnavailable', '25%')}",
        f"    maxSurge: {profile.get('maxSurge', '25%')}",
    ]
    if steps:
        lines.append("    steps:")
        lines.extend(f"      - {step}" for step in steps)
    else:
        lines.append("    steps: []")
    lines.extend(
        [
            "  blueGreen:",
            f"    enabled: {str(profile.get('strategy') == 'blue-green').lower()}",
            "    previewService: false",
            f"    autoPromotion: {str(bool_value(profile.get('autoPromotion'), False)).lower()}",
            "  rollback:",
            f"    automatic: {str(bool_value(profile.get('automaticRollback'), False)).lower()}",
            "    requireSmokeTests: true",
            f"    requireRollbackDrill: {str(bool_value(profile.get('requireRollbackDrill'), False)).lower()}",
            "  reports:",
            "    plan: reports/progressive-delivery-plan.md",
            "    overrides: reports/progressive-delivery-values.yaml",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_report(args: argparse.Namespace, config: dict[str, Any], profile: dict[str, Any], findings: list[str]) -> str:
    controller = config.get("controller", {}) if isinstance(config.get("controller"), dict) else {}
    guardrails = config.get("guardrails", [])
    checks = controller.get("requiredChecks", [])
    if not isinstance(guardrails, list):
        guardrails = []
    if not isinstance(checks, list):
        checks = []
    result = result_from_findings(findings)
    steps = ", ".join(str(step) for step in list_value(profile.get("canarySteps", []))) or "-"
    lines = [
        "# Progressive Delivery And Rollback Plan",
        "",
        "This report is public-safe. It does not install rollout controllers, mutate clusters, create traffic-shift resources, read private analysis queries, or print customer service names.",
        "",
        f"- Profile: `{args.profile}`",
        f"- Enabled: `{str(bool_value(profile.get('enabled'), False)).lower()}`",
        f"- Strategy: `{profile.get('strategy', 'rolling-update')}`",
        f"- Controller: `{profile.get('controller', 'none')}`",
        f"- Traffic provider: `{profile.get('trafficProvider', 'native')}`",
        f"- Analysis mode: `{profile.get('analysisMode', 'disabled')}`",
        f"- Canary steps: `{steps}`",
        f"- Auto promotion: `{str(bool_value(profile.get('autoPromotion'), False)).lower()}`",
        f"- Automatic rollback: `{str(bool_value(profile.get('automaticRollback'), False)).lower()}`",
        f"- GitOps profile: `{args.gitops_profile or '-'}`",
        f"- Runtime profile: `{args.runtime_profile or '-'}`",
        f"- SLO source: `{('<private-slo-analysis>' if args.redact_sensitive else args.slo_source) if args.slo_source else '-'}`",
        f"- Rollback drill evidence: `{str(args.rollback_drill).lower()}`",
        f"- Report: `{args.output}`",
        f"- Values overlay: `{args.overrides}`",
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
            "1. Keep standard Helm rollout as the baseline.",
            "2. Rehearse `lab-canary` with one or two low-risk workloads.",
            "3. Define SLO-backed analysis templates in private configuration.",
            "4. Install and own the rollout controller through a reviewed operator path.",
            "5. Enable production canary or blue-green only after rollback drills pass.",
            "",
            "## Example Commands",
            "",
            "```bash",
            "make progressive-delivery-plan PROGRESSIVE_DELIVERY_PROFILE=lab-canary IMPORT_REDACT=true",
            "make progressive-delivery-plan PROGRESSIVE_DELIVERY_PROFILE=production-canary IMPORT_REDACT=true",
            "helm rollback urban-platform-infra <REVISION> -n urban-platform",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe progressive delivery and rollback plan.")
    parser.add_argument("--config", default="config/progressive-delivery.yaml")
    parser.add_argument("--profile", default="")
    parser.add_argument("--gitops-profile", default="")
    parser.add_argument("--runtime-profile", default="")
    parser.add_argument("--slo-source", default="")
    parser.add_argument("--rollback-drill", action="store_true")
    parser.add_argument("--output", default="reports/progressive-delivery-plan.md")
    parser.add_argument("--overrides", default="reports/progressive-delivery-values.yaml")
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
    write_overrides(overrides_path, args.profile, profile)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generate_report(args, config, profile, findings), encoding="utf-8")
    print(f"Progressive delivery plan written: {output_path}")
    print(f"Progressive delivery values overlay written: {overrides_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
