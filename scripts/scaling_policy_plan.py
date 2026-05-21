#!/usr/bin/env python3
"""Generate a public-safe scaling policy and capacity automation plan."""
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


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def select_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = config.get("profiles", {})
    if not isinstance(profiles, dict):
        raise SystemExit("Scaling policy config must contain a profiles mapping.")
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown scaling policy profile `{profile_name}`. Available profiles: {choices}")
    profile = profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Scaling policy profile `{profile_name}` must be a mapping.")
    return profile


def profile_findings(profile_name: str, profile: dict[str, Any], args: argparse.Namespace) -> list[str]:
    findings: list[str] = []
    enabled = bool_value(profile.get("enabled"), False)
    hpa = as_mapping(profile.get("hpa"))
    vpa = as_mapping(profile.get("vpa"))
    keda = as_mapping(profile.get("keda"))
    cluster_autoscaler = as_mapping(profile.get("clusterAutoscaler"))
    right_sizing = as_mapping(profile.get("rightSizing"))

    if not enabled:
        findings.append(f"INFO: Profile `{profile_name}` is disabled; fixed replica and manual capacity review remain the default.")
    if bool_value(profile.get("requireMetrics"), False) and not args.metrics_source:
        findings.append("WARN: Scaling policy requires a private metrics source or adapter readiness proof.")
    if bool_value(profile.get("requireSlo"), False) and not args.metrics_source:
        findings.append("WARN: Production scaling should be tied to SLO or saturation metrics.")
    if bool_value(profile.get("requireLoadTest"), False) and not args.load_test_evidence:
        findings.append("WARN: Load-test or replay evidence is required before trusting autoscaling thresholds.")
    if bool_value(profile.get("requireCapacityReport"), False) and not args.capacity_report:
        findings.append("WARN: Capacity report evidence is required before enabling this scaling profile.")
    if bool_value(profile.get("requireEventSource"), False) and not args.event_source:
        findings.append("WARN: KEDA/event-driven scaling requires a private event source and trigger contract.")
    if bool_value(hpa.get("enabled"), False) and not args.metrics_source:
        findings.append("WARN: HPA requires metrics-server, Prometheus Adapter, or another reviewed metrics source.")
    if bool_value(vpa.get("enabled"), False) and bool_value(hpa.get("enabled"), False):
        findings.append("WARN: VPA and HPA together require careful mode selection; start VPA in recommendation or Initial mode.")
    if bool_value(keda.get("enabled"), False):
        findings.append("WARN: KEDA triggers must be defined privately because queue, stream, or schedule metadata can disclose workload details.")
    if bool_value(cluster_autoscaler.get("enabled"), False):
        findings.append("WARN: Cluster autoscaler is infrastructure-owned; do not enable it through public chart defaults.")
    if bool_value(right_sizing.get("requireRequests"), False):
        findings.append("INFO: Workload CPU and memory requests must be reviewed before autoscaling thresholds are trusted.")
    return findings or ["OK: Scaling policy settings are internally consistent."]


def result_from_findings(findings: list[str]) -> str:
    if any(item.startswith("ERROR:") for item in findings):
        return "FAIL"
    if any(item.startswith("WARN:") for item in findings):
        return "WARN"
    return "PASS"


def write_overrides(path: Path, profile_name: str, profile: dict[str, Any]) -> None:
    hpa = as_mapping(profile.get("hpa"))
    vpa = as_mapping(profile.get("vpa"))
    keda = as_mapping(profile.get("keda"))
    cluster_autoscaler = as_mapping(profile.get("clusterAutoscaler"))
    right_sizing = as_mapping(profile.get("rightSizing"))
    triggers = list_value(keda.get("triggers"))
    lines = [
        "scalingPolicy:",
        "  enabled: false",
        f"  profile: {profile_name}",
        f"  mode: {profile.get('mode', 'disabled')}",
        f"  metricsSource: {profile.get('metricsSource', 'none')}",
        "  hpa:",
        f"    enabled: {str(bool_value(hpa.get('enabled'), False)).lower()}",
        f"    minReplicas: {hpa.get('minReplicas', 1)}",
        f"    maxReplicas: {hpa.get('maxReplicas', 3)}",
        f"    targetCPUUtilizationPercentage: {hpa.get('targetCPUUtilizationPercentage', 70)}",
        "  vpa:",
        f"    enabled: {str(bool_value(vpa.get('enabled'), False)).lower()}",
        f"    updateMode: {vpa.get('updateMode', 'Off')}",
        "  keda:",
        f"    enabled: {str(bool_value(keda.get('enabled'), False)).lower()}",
    ]
    if triggers:
        lines.append("    triggers:")
        lines.extend(f"      - {trigger}" for trigger in triggers)
    else:
        lines.append("    triggers: []")
    lines.extend(
        [
            "  clusterAutoscaler:",
            f"    enabled: {str(bool_value(cluster_autoscaler.get('enabled'), False)).lower()}",
            f"    mode: {cluster_autoscaler.get('mode', 'external')}",
            "  rightSizing:",
            f"    enabled: {str(bool_value(right_sizing.get('enabled'), False)).lower()}",
            f"    capacityUtilizationLimit: {right_sizing.get('capacityUtilizationLimit', 0.70)}",
            f"    requireRequests: {str(bool_value(right_sizing.get('requireRequests'), True)).lower()}",
            "  reports:",
            "    plan: reports/scaling-policy-plan.md",
            "    overrides: reports/scaling-policy-values.yaml",
            "autoscaling:",
            "  enabled: false",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_report(args: argparse.Namespace, config: dict[str, Any], profile: dict[str, Any], findings: list[str]) -> str:
    controller = config.get("controller", {}) if isinstance(config.get("controller"), dict) else {}
    guardrails = config.get("guardrails", [])
    checks = controller.get("requiredChecks", []) if isinstance(controller, dict) else []
    if not isinstance(guardrails, list):
        guardrails = []
    if not isinstance(checks, list):
        checks = []
    hpa = as_mapping(profile.get("hpa"))
    vpa = as_mapping(profile.get("vpa"))
    keda = as_mapping(profile.get("keda"))
    cluster_autoscaler = as_mapping(profile.get("clusterAutoscaler"))
    right_sizing = as_mapping(profile.get("rightSizing"))
    result = result_from_findings(findings)
    event_source = "<private-event-source>" if args.redact_sensitive and args.event_source else (args.event_source or "-")
    metrics_source = "<private-metrics-source>" if args.redact_sensitive and args.metrics_source else (args.metrics_source or profile.get("metricsSource", "-"))
    lines = [
        "# Scaling Policy And Capacity Automation Plan",
        "",
        "This report is public-safe. It does not install autoscaling controllers, mutate workloads, read private metrics, create KEDA triggers, or print node names, queue names, tenant names, or customer service names.",
        "",
        f"- Profile: `{args.profile}`",
        f"- Enabled: `{str(bool_value(profile.get('enabled'), False)).lower()}`",
        f"- Mode: `{profile.get('mode', 'disabled')}`",
        f"- Metrics source: `{metrics_source}`",
        f"- Event source: `{event_source}`",
        f"- Capacity report: `{args.capacity_report or '-'}`",
        f"- Load-test evidence: `{str(args.load_test_evidence).lower()}`",
        f"- HPA enabled: `{str(bool_value(hpa.get('enabled'), False)).lower()}`",
        f"- HPA range: `{hpa.get('minReplicas', 1)}-{hpa.get('maxReplicas', 3)}`",
        f"- HPA CPU target: `{hpa.get('targetCPUUtilizationPercentage', 70)}`",
        f"- VPA enabled: `{str(bool_value(vpa.get('enabled'), False)).lower()}`",
        f"- VPA update mode: `{vpa.get('updateMode', 'Off')}`",
        f"- KEDA enabled: `{str(bool_value(keda.get('enabled'), False)).lower()}`",
        f"- KEDA triggers: `{', '.join(str(item) for item in list_value(keda.get('triggers'))) or '-'}`",
        f"- Cluster autoscaler enabled: `{str(bool_value(cluster_autoscaler.get('enabled'), False)).lower()}`",
        f"- Right-sizing enabled: `{str(bool_value(right_sizing.get('enabled'), False)).lower()}`",
        f"- Capacity utilization limit: `{right_sizing.get('capacityUtilizationLimit', '-')}`",
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
            "1. Keep fixed replicas and lab capacity gates as the baseline.",
            "2. Run `make lab-deploy-plan` and review resource requests first.",
            "3. Install metrics-server or Prometheus Adapter only after capacity is available.",
            "4. Enable HPA for one low-risk stateless workload before broad rollout.",
            "5. Add KEDA or VPA only after private trigger contracts, metrics, and rollback gates are reviewed.",
            "",
            "## Example Commands",
            "",
            "```bash",
            "make scaling-policy-plan SCALING_POLICY_PROFILE=lab-rightsize IMPORT_REDACT=true",
            "make scaling-policy-plan SCALING_POLICY_PROFILE=production-hpa SCALING_POLICY_METRICS_SOURCE=prometheus-adapter SCALING_POLICY_LOAD_TEST_EVIDENCE=true IMPORT_REDACT=true",
            "make lab-deploy-plan LAB_DEPLOY_PROFILE=three-node-4g IMPORT_REDACT=true",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe scaling policy and capacity automation plan.")
    parser.add_argument("--config", default="config/scaling-policy.yaml")
    parser.add_argument("--profile", default="")
    parser.add_argument("--metrics-source", default="")
    parser.add_argument("--event-source", default="")
    parser.add_argument("--capacity-report", default="")
    parser.add_argument("--load-test-evidence", action="store_true")
    parser.add_argument("--output", default="reports/scaling-policy-plan.md")
    parser.add_argument("--overrides", default="reports/scaling-policy-values.yaml")
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
    print(f"Scaling policy plan written: {output_path}")
    print(f"Scaling policy values overlay written: {overrides_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
