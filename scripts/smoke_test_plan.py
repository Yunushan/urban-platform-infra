#!/usr/bin/env python3
"""Generate a public-safe post-migration smoke-test and health-probe plan."""
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
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lower() in {"null", "none", "~"}:
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


def bool_text(value: Any) -> str:
    return "true" if bool(value) else "false"


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def redacted(value: str, fallback: str = "-") -> str:
    return "<redacted>" if value else fallback


def profiles(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("profiles", {})
    if not isinstance(value, dict):
        raise SystemExit("Smoke-test config must contain a profiles mapping.")
    return value


def profile_config(config: dict[str, Any], requested_profile: str) -> tuple[str, dict[str, Any]]:
    profile_name = requested_profile or str(config.get("defaultProfile", "disabled"))
    all_profiles = profiles(config)
    if profile_name not in all_profiles:
        choices = ", ".join(sorted(all_profiles))
        raise SystemExit(f"Unknown smoke-test profile `{profile_name}`. Available profiles: {choices}")
    profile = all_profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Smoke-test profile `{profile_name}` must be a mapping.")
    return profile_name, profile


def nested_bool(profile: dict[str, Any], section: str, key: str) -> bool:
    value = profile.get(section, {})
    if not isinstance(value, dict):
        return False
    return bool(value.get(key, False))


def nested_value(profile: dict[str, Any], section: str, key: str, default: str = "-") -> str:
    value = profile.get(section, {})
    if not isinstance(value, dict):
        return default
    item = value.get(key, default)
    return default if item is None else str(item)


def check_catalog(config: dict[str, Any]) -> list[dict[str, str]]:
    value = config.get("checkCatalog", [])
    if not isinstance(value, list):
        return []
    rows = []
    for item in value:
        if isinstance(item, dict):
            rows.append({"id": str(item.get("id", "-")), "description": str(item.get("description", "-"))})
    return rows


def guardrails(config: dict[str, Any]) -> list[str]:
    value = config.get("guardrails", [])
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def findings(args: argparse.Namespace, profile_name: str, profile: dict[str, Any]) -> list[str]:
    items = ["INFO: Smoke-test planner generated public-safe probe intent only."]
    if args.execute:
        items.append("WARN: Execute was requested; active probes still require a private runner or trusted operator context.")
    if nested_bool(profile, "checks", "requireHttpRoutes") and not args.ingress_host:
        items.append("WARN: HTTP route checks require a private ingress host or approved synthetic target.")
    if nested_bool(profile, "evidence", "requireResults") and not args.evidence:
        items.append("WARN: This profile requires private smoke-test result evidence before cutover.")
    if nested_bool(profile, "evidence", "requireOwnerReview") and not args.evidence:
        items.append("WARN: This profile requires owner-reviewed smoke-test evidence before cutover.")
    if profile_name == "production-smoke" and not nested_bool(profile, "checks", "requireExternalSynthetic"):
        items.append("ERROR: Production smoke profile must require external synthetic checks.")
    return items


def generate_overrides(profile_name: str, profile: dict[str, Any], args: argparse.Namespace, output_path: Path) -> None:
    checks = profile.get("checks", {}) if isinstance(profile.get("checks"), dict) else {}
    evidence = profile.get("evidence", {}) if isinstance(profile.get("evidence"), dict) else {}
    runner = nested_value(profile, "execution", "runner", "none")
    values = {
        "smokeTesting": {
            "enabled": False,
            "profile": profile_name,
            "mode": str(profile.get("mode", "baseline")),
            "execution": {
                "enabled": False,
                "runner": runner if runner in {"none", "kubectl", "kubernetes-job", "external-monitor"} else "external-monitor",
                "namespace": args.namespace or "urban-platform",
                "serviceAccountName": "",
            },
            "probes": {
                "kubernetesRollout": bool(checks.get("requireKubernetesRollout", False)),
                "httpRoutes": bool(checks.get("requireHttpRoutes", False)),
                "tcpServices": bool(checks.get("requireTcpServices", False)),
                "databaseConnections": bool(checks.get("requireDatabaseConnections", False)),
                "messagingConnections": bool(checks.get("requireMessagingConnections", False)),
                "externalSynthetic": bool(checks.get("requireExternalSynthetic", False)),
            },
            "evidence": {
                "requirePlan": bool(evidence.get("requirePlan", False)),
                "requireResults": bool(evidence.get("requireResults", False)),
                "requireOwnerReview": bool(evidence.get("requireOwnerReview", False)),
            },
            "reports": {
                "plan": "reports/smoke-test-plan.md",
                "overrides": "reports/smoke-test-values.yaml",
            },
        }
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(["# Generated by scripts/smoke_test_plan.py. Review before use.", *dump_yaml(values), ""]), encoding="utf-8")


def generate_report(args: argparse.Namespace, config: dict[str, Any], profile_name: str, profile: dict[str, Any], output_path: Path, overrides_path: Path) -> str:
    items = findings(args, profile_name, profile)
    result = "FAIL" if any(item.startswith("ERROR:") for item in items) else ("WARN" if any(item.startswith("WARN:") for item in items) else "PASS")
    checks = profile.get("checks", {}) if isinstance(profile.get("checks"), dict) else {}
    evidence = profile.get("evidence", {}) if isinstance(profile.get("evidence"), dict) else {}
    lines = [
        "# Post-Migration Smoke-Test And Health-Probe Plan",
        "",
        "This report is public-safe. It defines post-migration smoke-test and health-probe intent without printing private URLs, IPs, credentials, DSNs, service names, or customer identifiers.",
        "",
        f"- Profile: `{profile_name}`",
        f"- Enabled by default: `{bool_text(config.get('enabledByDefault', False))}`",
        f"- Mode: `{profile.get('mode', 'baseline')}`",
        f"- Namespace: `{args.namespace or 'urban-platform'}`",
        f"- Ingress host: `{redacted(args.ingress_host) if args.redact_sensitive else (args.ingress_host or '-')}`",
        f"- Execution requested: `{bool_text(args.execute)}`",
        f"- Runner: `{nested_value(profile, 'execution', 'runner', 'none')}`",
        f"- Evidence input: `{redacted(args.evidence) if args.redact_sensitive else (args.evidence or '-')}`",
        f"- Generated values overlay: `{display_path(overrides_path)}`",
        f"- Result: `{result}`",
        "",
        "## Required Probe Categories",
        "",
        f"- Kubernetes rollout: `{bool_text(checks.get('requireKubernetesRollout', False))}`",
        f"- HTTP route: `{bool_text(checks.get('requireHttpRoutes', False))}`",
        f"- TCP service: `{bool_text(checks.get('requireTcpServices', False))}`",
        f"- Database connection: `{bool_text(checks.get('requireDatabaseConnections', False))}`",
        f"- Messaging connection: `{bool_text(checks.get('requireMessagingConnections', False))}`",
        f"- External synthetic: `{bool_text(checks.get('requireExternalSynthetic', False))}`",
        "- Probe catalog: `kubernetes rollout`, `database connection`, `messaging connection`.",
        "",
        "## Evidence Gates",
        "",
        f"- Plan required: `{bool_text(evidence.get('requirePlan', False))}`",
        f"- Results required: `{bool_text(evidence.get('requireResults', False))}`",
        f"- Owner review required: `{bool_text(evidence.get('requireOwnerReview', False))}`",
        "",
        "## Check Catalog",
        "",
        "| Check | Public-safe intent |",
        "|---|---|",
    ]
    for row in check_catalog(config):
        lines.append(f"| `{row['id']}` | {row['description']} |")
    if not check_catalog(config):
        lines.append("| `-` | No checks declared. |")

    lines.extend(["", "## Guardrails", ""])
    for item in guardrails(config):
        lines.append(f"- {item}")
    if not guardrails(config):
        lines.append("- No guardrails declared.")

    lines.extend(
        [
            "",
            "## Operator Command",
            "",
            "```bash",
            f"make smoke-test-plan SMOKE_TEST_PROFILE={profile_name} IMPORT_REDACT=true",
            "```",
            "",
            "## Findings",
            "",
        ]
    )
    for item in items:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def resolve_path(path: str) -> Path:
    value = Path(path)
    return value if value.is_absolute() else (ROOT / value).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe post-migration smoke-test and health-probe plan.")
    parser.add_argument("--config", default=str(ROOT / "config/smoke-tests.yaml"))
    parser.add_argument("--profile", default="")
    parser.add_argument("--namespace", default="urban-platform")
    parser.add_argument("--ingress-host", default="")
    parser.add_argument("--evidence", default="")
    parser.add_argument("--output", default=str(ROOT / "reports/smoke-test-plan.md"))
    parser.add_argument("--overrides", default=str(ROOT / "reports/smoke-test-values.yaml"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--redact-sensitive", action="store_true")
    args = parser.parse_args(argv)

    config = load_yaml_file(resolve_path(args.config))
    profile_name, profile = profile_config(config, args.profile)
    output_path = resolve_path(args.output)
    overrides_path = resolve_path(args.overrides)
    generate_overrides(profile_name, profile, args, overrides_path)
    report = generate_report(args, config, profile_name, profile, output_path, overrides_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Smoke-test plan written to {display_path(output_path)}")
    print(f"Smoke-test values overlay written to {display_path(overrides_path)}")
    if "Result: `FAIL`" in report:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
