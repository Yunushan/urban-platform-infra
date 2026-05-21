#!/usr/bin/env python3
"""Generate a public-safe observability and SLO readiness plan."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - keeps the planner usable on lean operator hosts.
    yaml = None


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = [
    "prometheus",
    "grafana",
    "opentelemetry",
    "elasticsearch",
    "kibana",
    "logstash",
    "loki",
    "clickhouse",
    "opensearch",
    "graylog",
]


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
    if value.lower() in {"null", "none", "~"}:
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
        line_indent = len(raw_line) - len(raw_line.lstrip(" "))
        if line_indent <= indent:
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
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if stripped.startswith("- "):
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


def load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) if yaml else load_simple_yaml(text)
    data = data or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def nested(mapping: dict[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def flag(value: Any) -> str:
    return "enabled" if value is True else "disabled"


def slugify_heading(heading: str) -> str:
    value = heading.strip().lower()
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"[^a-z0-9 -]", "", value)
    value = re.sub(r"\s+", "-", value)
    return value.strip("-")


def markdown_anchors(text: str) -> set[str]:
    anchors: set[str] = set()
    for line in text.splitlines():
        if line.startswith("#"):
            anchors.add(slugify_heading(line.lstrip("#").strip()))
    return anchors


def objective_rows(objectives: dict[str, Any]) -> list[str]:
    rows = [
        "| Objective | Target | Source | Alert | Runbook |",
        "|---|---:|---|---|---|",
    ]
    for name, objective in sorted(objectives.items()):
        if not isinstance(objective, dict):
            continue
        rows.append(
            "| `{}` | `{}` | `{}` | `{}` | `{}` |".format(
                name,
                objective.get("target", "n/a"),
                objective.get("source", "n/a"),
                objective.get("alert", "n/a"),
                objective.get("runbook", "n/a"),
            )
        )
    return rows


def component_rows(values: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    rows = [
        "| Component | Values default | Contract default | Notes |",
        "|---|---|---|---|",
    ]
    observability_values = values.get("observability", {})
    profiles = contract.get("profiles", {}) if isinstance(contract.get("profiles"), dict) else {}
    for component in COMPONENTS:
        values_component = observability_values.get(component, {}) if isinstance(observability_values, dict) else {}
        contract_component = profiles.get(component, {}) if isinstance(profiles.get(component), dict) else {}
        rows.append(
            "| `{}` | `{}` | `{}` | `{}` |".format(
                component,
                flag(values_component.get("enabled") if isinstance(values_component, dict) else False),
                flag(contract_component.get("enabled")),
                contract_component.get("purpose", "optional"),
            )
        )
    return rows


def gate_rows(gates: list[tuple[str, str, str]]) -> list[str]:
    rows = [
        "| Gate | State | Public-safe note |",
        "|---|---|---|",
    ]
    rows.extend(f"| {gate} | `{state}` | {note} |" for gate, state, note in gates)
    return rows


def build_plan(
    values: dict[str, Any],
    observability_contract: dict[str, Any],
    slo_contract: dict[str, Any],
    runbook_text: str,
    rules_text: str,
    servicemonitor_text: str,
    args: argparse.Namespace,
) -> tuple[str, bool]:
    observability_values = values.get("observability", {}) if isinstance(values.get("observability"), dict) else {}
    monitoring_values = values.get("monitoring", {}) if isinstance(values.get("monitoring"), dict) else {}
    rules_values = monitoring_values.get("prometheusRules", {}) if isinstance(monitoring_values.get("prometheusRules"), dict) else {}
    monitors_values = monitoring_values.get("serviceMonitors", {}) if isinstance(monitoring_values.get("serviceMonitors"), dict) else {}
    objectives = slo_contract.get("objectives", {}) if isinstance(slo_contract.get("objectives"), dict) else {}
    dashboard_names = slo_contract.get("dashboards", {}).get("required", []) if isinstance(slo_contract.get("dashboards"), dict) else []
    if not isinstance(dashboard_names, list):
        dashboard_names = []

    findings: list[tuple[str, str]] = []
    gates: list[tuple[str, str, str]] = []

    default_disabled = observability_values.get("profile") == "disabled" and observability_contract.get("default") == "disabled"
    gates.append(
        (
            "Lab-safe default",
            "pass" if default_disabled else "warn",
            "Heavy observability remains opt-in for 4-core/4 GiB lab nodes.",
        )
    )
    if not default_disabled:
        findings.append(("WARN", "Observability should stay disabled by default for the lab profile."))

    enabled_components = [
        component
        for component in COMPONENTS
        if isinstance(observability_values.get(component), dict) and observability_values.get(component, {}).get("enabled") is True
    ]
    if args.profile == "lab" and enabled_components:
        findings.append(("ERROR", f"Lab profile has heavy observability components enabled: {', '.join(enabled_components)}."))

    monitoring_enabled = monitoring_values.get("enabled") is True
    rules_enabled = rules_values.get("enabled") is True
    monitors_enabled = monitors_values.get("enabled") is True
    gates.append(
        (
            "Prometheus Operator CRD gate",
            "manual-ready" if not monitoring_enabled else "enabled",
            "Enable chart monitoring only after PrometheusRule and ServiceMonitor CRDs exist.",
        )
    )
    if monitoring_enabled and not rules_enabled:
        findings.append(("WARN", "Monitoring is enabled but PrometheusRule generation is disabled."))
    if monitors_enabled and not monitors_values.get("targets"):
        findings.append(("WARN", "ServiceMonitor generation is enabled without scrape targets."))

    runbook_anchors = markdown_anchors(runbook_text)
    missing_alerts: list[str] = []
    missing_runbooks: list[str] = []
    malformed_objectives: list[str] = []
    for objective_name, objective in objectives.items():
        if not isinstance(objective, dict):
            malformed_objectives.append(objective_name)
            continue
        for key in ["target", "sli", "source", "alert", "runbook"]:
            if key not in objective:
                malformed_objectives.append(objective_name)
                break
        alert = str(objective.get("alert", "")).strip()
        if alert and alert not in rules_text:
            missing_alerts.append(alert)
        runbook = str(objective.get("runbook", "")).strip()
        if "#" in runbook:
            anchor = runbook.rsplit("#", 1)[1]
            if anchor not in runbook_anchors:
                missing_runbooks.append(runbook)
        elif runbook:
            missing_runbooks.append(runbook)

    if len(objectives) < 5:
        findings.append(("ERROR", "SLO contract should define at least five production objectives."))
    if malformed_objectives:
        findings.append(("ERROR", f"SLO objectives have missing fields: {', '.join(sorted(set(malformed_objectives)))}."))
    for alert in sorted(set(missing_alerts)):
        findings.append(("ERROR", f"SLO alert is missing from PrometheusRule template: {alert}."))
    for runbook in sorted(set(missing_runbooks)):
        findings.append(("ERROR", f"SLO runbook anchor is missing: {runbook}."))

    gates.append(
        (
            "SLO contract",
            "pass" if len(objectives) >= 5 and not malformed_objectives else "fail",
            "Objectives must include target, SLI, source, alert, and runbook.",
        )
    )
    gates.append(
        (
            "Alert template coverage",
            "pass" if not missing_alerts and "PrometheusRule" in rules_text else "fail",
            "Every SLO alert should be emitted by the chart PrometheusRule template.",
        )
    )
    gates.append(
        (
            "Runbook coverage",
            "pass" if not missing_runbooks else "fail",
            "Every SLO alert should point to a public-safe runbook anchor.",
        )
    )
    gates.append(
        (
            "ServiceMonitor template",
            "pass" if "ServiceMonitor" in servicemonitor_text and "namespaceSelector" in servicemonitor_text else "fail",
            "Generic scrape targets stay disabled until services expose real Prometheus metrics.",
        )
    )

    if "https://example.com/" not in str(rules_values.get("runbookBaseUrl", "")):
        findings.append(("WARN", "Default runbookBaseUrl should remain an example.com placeholder in public defaults."))
    if not dashboard_names:
        findings.append(("WARN", "SLO contract has no required dashboard list."))

    lines = [
        "# Observability And SLO Readiness Plan",
        "",
        "This report is public-safe. It reports readiness gates and committed defaults only; it does not read kubeconfigs, private endpoints, credentials, event payloads, or cluster logs.",
        "",
        f"- Profile: `{args.profile}`",
        f"- Values file: `{args.values}`",
        f"- Observability contract: `{args.observability_config}`",
        f"- SLO contract: `{args.slo_config}`",
        f"- Observability default profile: `{observability_values.get('profile', 'unknown')}`",
        f"- Monitoring enabled by default: `{str(monitoring_enabled).lower()}`",
        f"- PrometheusRule generation default: `{flag(rules_enabled)}`",
        f"- ServiceMonitor generation default: `{flag(monitors_enabled)}`",
        f"- SLO objectives: `{len(objectives)}`",
        f"- Required dashboards: `{len(dashboard_names)}`",
        "",
        "## Readiness Gates",
        "",
        *gate_rows(gates),
        "",
        "## Component Defaults",
        "",
        *component_rows(values, observability_contract),
        "",
        "## SLO Objective Coverage",
        "",
        *objective_rows(objectives),
        "",
        "## Production Enablement Sequence",
        "",
        "1. Run `make observability-plan` and clear any `ERROR` findings.",
        "2. Install the Prometheus Operator stack through `make install-operators DEPLOY_ENABLE_PROMETHEUS=true DEPLOY_ENABLE_GRAFANA=true` when capacity is available.",
        "3. Confirm `prometheusrules.monitoring.coreos.com` and `servicemonitors.monitoring.coreos.com` exist before setting `monitoring.enabled=true`.",
        "4. Enable only the needed logging/search pipeline: Elastic, Loki, OpenSearch, Graylog, or ClickHouse.",
        "5. Add real ServiceMonitor targets only for services that expose Prometheus-format metrics.",
        "6. Review monthly SLO error budget, alert noise, missing dashboards, and runbook gaps.",
        "",
    ]
    if findings:
        lines.extend(["## Findings", ""])
        lines.extend(f"- {level}: {message}" for level, message in findings)
        lines.append("")
    else:
        lines.extend(["## Findings", "", "- OK: Observability and SLO readiness gates are satisfied for committed defaults.", ""])

    failed = any(level == "ERROR" for level, _ in findings)
    return "\n".join(lines), failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe observability and SLO readiness plan.")
    parser.add_argument("--values", default="helm/urban-platform-infra/values.yaml")
    parser.add_argument("--observability-config", default="config/observability.yaml")
    parser.add_argument("--slo-config", default="config/slo.yaml")
    parser.add_argument("--runbooks", default="docs/runbooks.md")
    parser.add_argument("--rules-template", default="helm/urban-platform-infra/templates/monitoring-rules.yaml")
    parser.add_argument("--servicemonitor-template", default="helm/urban-platform-infra/templates/monitoring-servicemonitors.yaml")
    parser.add_argument("--output", default="reports/observability-plan.md")
    parser.add_argument("--profile", choices=["lab", "production"], default="lab")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    values = load_yaml(ROOT / args.values)
    observability_contract = load_yaml(ROOT / args.observability_config)
    slo_contract = load_yaml(ROOT / args.slo_config)
    runbook_text = (ROOT / args.runbooks).read_text(encoding="utf-8")
    rules_text = (ROOT / args.rules_template).read_text(encoding="utf-8")
    servicemonitor_text = (ROOT / args.servicemonitor_template).read_text(encoding="utf-8")

    report, failed = build_plan(
        values,
        observability_contract,
        slo_contract,
        runbook_text,
        rules_text,
        servicemonitor_text,
        args,
    )
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"Observability plan written: {args.output}")
    if args.strict and failed:
        print("Observability strict mode failed: clear ERROR findings before production enablement.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
