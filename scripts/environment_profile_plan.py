#!/usr/bin/env python3
"""Generate a public-safe environment profile plan and values overlay."""
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
        child_indent = len(raw_line) - len(raw_line.lstrip(" "))
        if child_indent < indent:
            return False
        if child_indent == indent:
            return raw_line.lstrip().startswith("- ")
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
                raw_value = raw_value.strip()
                child[key.strip().strip("'\"")] = parse_scalar(raw_value) if raw_value else {}
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
    if isinstance(value, (int, float)):
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


def nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def profile_config(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = config.get("profiles", {})
    if not isinstance(profiles, dict):
        raise SystemExit("Environment profiles config must contain a profiles mapping.")
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown environment profile `{profile_name}`. Available profiles: {choices}")
    profile = profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Environment profile `{profile_name}` must be a mapping.")
    return profile


def topology_config(topologies: dict[str, Any], name: str) -> dict[str, Any]:
    items = topologies.get("topologies", {})
    if not isinstance(items, dict):
        return {}
    value = items.get(name, {})
    return value if isinstance(value, dict) else {}


def bool_text(value: Any) -> str:
    return "true" if bool(value) else "false"


def display_value(value: Any) -> str:
    if isinstance(value, bool):
        return bool_text(value)
    if value is None:
        return "null"
    return str(value)


def profile_findings(profile_name: str, profile: dict[str, Any], topology: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    if profile_name == "production" and not bool(profile.get("strictDatabaseMigration", False)):
        findings.append("ERROR: Production environment profile must enable strict database migration.")
    if profile_name == "production" and not bool(profile.get("requirePrivateRegistry", False)):
        findings.append("ERROR: Production environment profile must require a private registry or approved registry strategy.")
    if profile_name == "lab" and profile.get("imageMode") != "preload":
        findings.append("WARN: Lab environment usually uses preload mode to avoid registry login.")
    if topology and profile_name == "production" and topology.get("production") is not True:
        findings.append("ERROR: Production environment points at a non-production topology.")
    if profile_name != "production" and bool(profile.get("requireReleaseEvidence", False)):
        findings.append("WARN: Non-production profile requires release evidence; confirm this is intentional.")
    return findings or ["OK: Environment profile settings are internally consistent."]


def generate_overlay(profile: dict[str, Any], overlay_path: Path) -> None:
    values = profile.get("helmValues", {})
    if not isinstance(values, dict):
        values = {}
    content = ["# Generated by scripts/environment_profile_plan.py. Review before use.", *dump_yaml(values), ""]
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.write_text("\n".join(content), encoding="utf-8")


def generate_report(args: argparse.Namespace, config: dict[str, Any], topologies: dict[str, Any], profile: dict[str, Any]) -> str:
    topology_name = str(profile.get("topology", ""))
    topology = topology_config(topologies, topology_name)
    requirements = config.get("requirements", {}).get(args.profile, []) if isinstance(config.get("requirements"), dict) else []
    if not isinstance(requirements, list):
        requirements = []
    findings = profile_findings(args.profile, profile, topology)
    result = "FAIL" if any(item.startswith("ERROR:") for item in findings) else ("WARN" if any(item.startswith("WARN:") for item in findings) else "PASS")
    helm_values = profile.get("helmValues", {}) if isinstance(profile.get("helmValues"), dict) else {}

    lines = [
        "# Environment Profile Plan",
        "",
        "This report is public-safe. It contains environment intent and generated override paths only; it does not include private inventories, node addresses, DNS names, TLS material, registry credentials, or customer identifiers.",
        "",
        f"- Profile: `{args.profile}`",
        f"- Environment: `{profile.get('environment', args.profile)}`",
        f"- Topology: `{topology_name or '-'}`",
        f"- Topology production-ready: `{bool_text(topology.get('production', False))}`",
        f"- Minimum nodes: `{topology.get('minimumNodes', '-')}`",
        f"- Migration profile: `{profile.get('migrationProfile', '-')}`",
        f"- Image mode: `{profile.get('imageMode', '-')}`",
        f"- Database migration profile: `{profile.get('databaseMigrationProfile', '-')}`",
        f"- Edge migration profile: `{profile.get('edgeMigrationProfile', '-')}`",
        f"- Secret provider profile: `{profile.get('secretProviderProfile', '-')}`",
        f"- Registry promotion profile: `{profile.get('registryPromotionProfile', '-')}`",
        f"- Runtime hardening profile: `{profile.get('runtimeHardeningProfile', '-')}`",
        f"- GitOps delivery profile: `{profile.get('gitOpsProfile', '-')}`",
        f"- Progressive delivery profile: `{profile.get('progressiveDeliveryProfile', '-')}`",
        f"- Scaling policy profile: `{profile.get('scalingPolicyProfile', '-')}`",
        f"- Network connectivity profile: `{profile.get('networkConnectivityProfile', '-')}`",
        f"- Access governance profile: `{profile.get('accessGovernanceProfile', '-')}`",
        f"- Compliance evidence profile: `{profile.get('complianceEvidenceProfile', '-')}`",
        f"- Incident response profile: `{profile.get('incidentResponseProfile', '-')}`",
        f"- Change management profile: `{profile.get('changeManagementProfile', '-')}`",
        f"- Disaster recovery profile: `{profile.get('disasterRecoveryProfile', '-')}`",
        f"- Backup profile: `{profile.get('backupProfile', '-')}`",
        f"- Observability profile: `{profile.get('observabilityProfile', '-')}`",
        f"- Optional capabilities: `{profile.get('optionalCapabilities', '-')}`",
        f"- Import batch: `{profile.get('importBatch', '-')}`",
        f"- Strict database migration: `{bool_text(profile.get('strictDatabaseMigration', False))}`",
        f"- Require ingress endpoint: `{bool_text(profile.get('requireIngressEndpoint', False))}`",
        f"- Require private registry: `{bool_text(profile.get('requirePrivateRegistry', False))}`",
        f"- Require restore drill: `{bool_text(profile.get('requireRestoreDrill', False))}`",
        f"- Require release evidence: `{bool_text(profile.get('requireReleaseEvidence', False))}`",
        f"- Generated values overlay: `{args.overrides}`",
        f"- Result: `{result}`",
        "",
        "## Generated Helm Intent",
        "",
        f"- `global.environment`: `{display_value(nested(helm_values, 'global', 'environment', default='-'))}`",
        f"- `global.replicaOverride`: `{display_value(nested(helm_values, 'global', 'replicaOverride', default='-'))}`",
        f"- `global.skipPlaceholderWorkloads`: `{display_value(nested(helm_values, 'global', 'skipPlaceholderWorkloads', default='-'))}`",
        f"- `autoscaling.enabled`: `{display_value(nested(helm_values, 'autoscaling', 'enabled', default='-'))}`",
        f"- `backup.profile`: `{display_value(nested(helm_values, 'backup', 'profile', default='-'))}`",
        f"- `gitOpsDelivery.profile`: `{display_value(nested(helm_values, 'gitOpsDelivery', 'profile', default='-'))}`",
        f"- `gitOpsDelivery.controller`: `{display_value(nested(helm_values, 'gitOpsDelivery', 'controller', default='-'))}`",
        f"- `progressiveDelivery.profile`: `{display_value(nested(helm_values, 'progressiveDelivery', 'profile', default='-'))}`",
        f"- `progressiveDelivery.strategy`: `{display_value(nested(helm_values, 'progressiveDelivery', 'strategy', default='-'))}`",
        f"- `scalingPolicy.profile`: `{display_value(nested(helm_values, 'scalingPolicy', 'profile', default='-'))}`",
        f"- `scalingPolicy.mode`: `{display_value(nested(helm_values, 'scalingPolicy', 'mode', default='-'))}`",
        f"- `networkConnectivity.profile`: `{display_value(nested(helm_values, 'networkConnectivity', 'profile', default='-'))}`",
        f"- `networkConnectivity.mode`: `{display_value(nested(helm_values, 'networkConnectivity', 'mode', default='-'))}`",
        f"- `accessGovernance.profile`: `{display_value(nested(helm_values, 'accessGovernance', 'profile', default='-'))}`",
        f"- `accessGovernance.mode`: `{display_value(nested(helm_values, 'accessGovernance', 'mode', default='-'))}`",
        f"- `complianceEvidence.profile`: `{display_value(nested(helm_values, 'complianceEvidence', 'profile', default='-'))}`",
        f"- `complianceEvidence.mode`: `{display_value(nested(helm_values, 'complianceEvidence', 'mode', default='-'))}`",
        f"- `incidentResponse.profile`: `{display_value(nested(helm_values, 'incidentResponse', 'profile', default='-'))}`",
        f"- `incidentResponse.mode`: `{display_value(nested(helm_values, 'incidentResponse', 'mode', default='-'))}`",
        f"- `changeManagement.profile`: `{display_value(nested(helm_values, 'changeManagement', 'profile', default='-'))}`",
        f"- `changeManagement.mode`: `{display_value(nested(helm_values, 'changeManagement', 'mode', default='-'))}`",
        f"- `disasterRecovery.profile`: `{display_value(nested(helm_values, 'disasterRecovery', 'profile', default='-'))}`",
        f"- `disasterRecovery.mode`: `{display_value(nested(helm_values, 'disasterRecovery', 'mode', default='-'))}`",
        f"- `observability.profile`: `{display_value(nested(helm_values, 'observability', 'profile', default='-'))}`",
        f"- `platformCapabilities.enabled`: `{display_value(nested(helm_values, 'platformCapabilities', 'enabled', default='-'))}`",
        f"- `databases.defaultInstances`: `{display_value(nested(helm_values, 'databases', 'defaultInstances', default='-'))}`",
        "",
        "## Requirements",
        "",
    ]
    for requirement in requirements:
        lines.append(f"- {requirement}")
    if not requirements:
        lines.append("- No additional requirements declared for this profile.")

    lines.extend(["", "## Findings", ""])
    for finding in findings:
        lines.append(f"- {finding}")

    lines.extend(
        [
            "",
            "## Example Commands",
            "",
            "```bash",
            "make environment-profile-plan ENV_PROFILE=lab IMPORT_REDACT=true",
            "make deploy-auto HELM_EXTRA_ARGS=\"-f reports/environment-profile-values.yaml\"",
            "make import-auto PROJECT_PATH=/path/to/compose-project MIGRATION_PROFILE=lab MIGRATION_IMAGE_MODE=preload",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe environment profile plan and values overlay.")
    parser.add_argument("--config", default=str(ROOT / "config/environment-profiles.yaml"))
    parser.add_argument("--topologies", default=str(ROOT / "config/deployment-topologies.yaml"))
    parser.add_argument("--profile", default="")
    parser.add_argument("--output", default=str(ROOT / "reports/environment-profile-plan.md"))
    parser.add_argument("--overrides", default=str(ROOT / "reports/environment-profile-values.yaml"))
    parser.add_argument("--redact-sensitive", action="store_true")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = (ROOT / config_path).resolve()
    topologies_path = Path(args.topologies)
    if not topologies_path.is_absolute():
        topologies_path = (ROOT / topologies_path).resolve()
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (ROOT / output_path).resolve()
    overrides_path = Path(args.overrides)
    if not overrides_path.is_absolute():
        overrides_path = (ROOT / overrides_path).resolve()

    config = load_yaml_file(config_path)
    topologies = load_yaml_file(topologies_path)
    default_profile = str(config.get("defaultProfile", "lab"))
    args.profile = args.profile or default_profile
    profile = profile_config(config, args.profile)
    generate_overlay(profile, overrides_path)
    report = generate_report(args, config, topologies, profile)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Environment profile plan written: {output_path}")
    print(f"Environment profile values overlay written: {overrides_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
