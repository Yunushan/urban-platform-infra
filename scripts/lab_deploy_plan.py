#!/usr/bin/env python3
"""Generate a public-safe lab capacity and progressive deploy plan."""
from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - keeps the planner usable on lean operator hosts.
    yaml = None


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Component:
    name: str
    category: str
    replicas: int
    cpu_m: int
    memory_mi: int
    storage_gi: float = 0.0
    note: str = ""

    @property
    def total_cpu_m(self) -> int:
        return self.cpu_m * self.replicas

    @property
    def total_memory_mi(self) -> int:
        return self.memory_mi * self.replicas

    @property
    def total_storage_gi(self) -> float:
        return self.storage_gi * self.replicas


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


def parse_cpu_m(value: Any) -> int:
    if value is None or value == "":
        return 0
    text = str(value).strip()
    if text.endswith("m"):
        return int(float(text[:-1]))
    return int(float(text) * 1000)


def parse_memory_mi(value: Any) -> int:
    if value is None or value == "":
        return 0
    text = str(value).strip()
    units = [
        ("Ki", 1 / 1024),
        ("Mi", 1),
        ("Gi", 1024),
        ("Ti", 1024 * 1024),
        ("K", 1 / 1000),
        ("M", 1000 / 1024),
        ("G", 1000 * 1000 / 1024),
    ]
    for suffix, factor in units:
        if text.endswith(suffix):
            return int(math.ceil(float(text[: -len(suffix)]) * factor))
    return int(math.ceil(float(text) / 1024 / 1024))


def parse_storage_gi(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return parse_memory_mi(value) / 1024


def effective_replicas(values: dict[str, Any], desired: Any, default: int = 1) -> int:
    override = nested(values, "global", "replicaOverride")
    if override not in {None, "", 0, "0"}:
        return max(1, int(override))
    return max(1, int(desired or default))


def resource_pair(resources: Any) -> tuple[int, int]:
    if not isinstance(resources, dict):
        return 0, 0
    requests = resources.get("requests", {}) if isinstance(resources.get("requests"), dict) else {}
    return parse_cpu_m(requests.get("cpu")), parse_memory_mi(requests.get("memory"))


def enabled(mapping: Any) -> bool:
    return isinstance(mapping, dict) and mapping.get("enabled") is True


def collect_components(values: dict[str, Any]) -> tuple[list[Component], list[str], list[str]]:
    components: list[Component] = []
    warnings: list[str] = []
    recommendations: list[str] = []
    global_values = values.get("global", {}) if isinstance(values.get("global"), dict) else {}
    skip_placeholder = global_values.get("skipPlaceholderWorkloads") is True

    provider_name = nested(values, "webserver", "provider")
    provider = nested(values, "webserver", "providers", str(provider_name)) if provider_name else None
    if enabled(provider):
        cpu_m, memory_mi = resource_pair(provider.get("resources"))
        components.append(
            Component(
                name=f"webserver-{provider_name}",
                category="edge",
                replicas=effective_replicas(values, provider.get("replicas"), 1),
                cpu_m=cpu_m,
                memory_mi=memory_mi,
            )
        )

    databases = values.get("databases", {}) if isinstance(values.get("databases"), dict) else {}
    db_resources = databases.get("resources", {}) if isinstance(databases.get("resources"), dict) else {}
    db_cpu_m, db_memory_mi = resource_pair(db_resources)
    storage_override = databases.get("storageOverride", {}) if isinstance(databases.get("storageOverride"), dict) else {}
    for name, db in sorted((databases.get("instances", {}) or {}).items()):
        if not enabled(db):
            continue
        db_storage = db.get("storage", {}) if isinstance(db.get("storage"), dict) else {}
        storage = storage_override.get("size") or db_storage.get("size")
        components.append(
            Component(
                name=name,
                category="database",
                replicas=effective_replicas(values, db.get("instances"), databases.get("defaultInstances", 1)),
                cpu_m=db_cpu_m,
                memory_mi=db_memory_mi,
                storage_gi=parse_storage_gi(storage),
                note=str(db.get("engine", "database")),
            )
        )

    kafka = nested(values, "messaging", "kafka")
    if enabled(kafka):
        cpu_m, memory_mi = resource_pair(kafka.get("resources"))
        storage = nested(kafka, "storage", "size")
        components.append(Component("kafka", "messaging", effective_replicas(values, kafka.get("replicas"), 1), cpu_m, memory_mi, parse_storage_gi(storage)))
        zookeeper = kafka.get("zookeeper", {}) if isinstance(kafka.get("zookeeper"), dict) else {}
        if enabled(zookeeper):
            cpu_m, memory_mi = resource_pair(zookeeper.get("resources"))
            components.append(
                Component("zookeeper", "messaging", effective_replicas(values, zookeeper.get("replicas"), 1), cpu_m, memory_mi, parse_storage_gi(nested(zookeeper, "storage", "size")))
            )
        kafka_ui = kafka.get("ui", {}) if isinstance(kafka.get("ui"), dict) else {}
        if enabled(kafka_ui):
            cpu_m, memory_mi = resource_pair(kafka_ui.get("resources"))
            components.append(Component("kafka-ui", "optional", effective_replicas(values, kafka_ui.get("replicas"), 1), cpu_m, memory_mi, note="disable first in small labs"))
            recommendations.append("Disable Kafka UI for the first lab deploy unless you are testing Kafka administration.")

    redis = nested(values, "messaging", "redis")
    if enabled(redis):
        cpu_m, memory_mi = resource_pair(redis.get("resources"))
        components.append(Component("redis", "cache", effective_replicas(values, redis.get("replicas"), 1), cpu_m, memory_mi, parse_storage_gi(nested(redis, "storage", "size"))))
        sentinel = redis.get("sentinel", {}) if isinstance(redis.get("sentinel"), dict) else {}
        if enabled(sentinel):
            cpu_m, memory_mi = resource_pair(sentinel.get("resources"))
            components.append(Component("redis-sentinel", "cache", effective_replicas(values, sentinel.get("replicas"), 1), cpu_m, memory_mi))

    observability = values.get("observability", {}) if isinstance(values.get("observability"), dict) else {}
    for name in ["elasticsearch", "kibana", "logstash", "grafana", "prometheus", "opentelemetry", "loki", "clickhouse", "opensearch", "graylog"]:
        item = observability.get(name, {}) if isinstance(observability.get(name), dict) else {}
        if enabled(item):
            cpu_m, memory_mi = resource_pair(item.get("resources"))
            replicas = item.get("replicas") or item.get("count") or 1
            components.append(Component(name, "observability", effective_replicas(values, replicas, 1), cpu_m, memory_mi, note="opt-in after capacity is proven"))
            warnings.append(f"Heavy observability component is enabled for lab planning: {name}.")

    zabbix = values.get("zabbixAgent", {}) if isinstance(values.get("zabbixAgent"), dict) else {}
    if enabled(zabbix):
        components.append(Component("zabbix-agent", "optional", effective_replicas(values, zabbix.get("replicas"), 1), 0, 0, note="no default requests; disable first in small labs"))
        recommendations.append("Disable Zabbix agent for the first lab deploy unless agent telemetry is required.")

    workloads = values.get("workloads", {}) if isinstance(values.get("workloads"), dict) else {}
    skipped_placeholders = 0
    for name, workload in sorted(workloads.items()):
        if not enabled(workload):
            continue
        image_repo = str(nested(workload, "image", "repository") or "")
        if skip_placeholder and image_repo.startswith("example-app-"):
            skipped_placeholders += 1
            continue
        cpu_m, memory_mi = resource_pair(workload.get("resources"))
        components.append(
            Component(
                name=name,
                category="workload",
                replicas=effective_replicas(values, workload.get("replicas"), global_values.get("defaultReplicas", 1)),
                cpu_m=cpu_m,
                memory_mi=memory_mi,
                note="application",
            )
        )
    if skipped_placeholders:
        recommendations.append(f"Placeholder application workloads skipped by default: {skipped_placeholders}.")
    if not skip_placeholder:
        warnings.append("Placeholder application workloads are not skipped; this can flood a small lab.")
    if nested(values, "autoscaling", "enabled") is not False:
        warnings.append("Autoscaling is enabled; lab plans should keep it disabled until metrics are installed.")
    if nested(values, "backup", "enabled") is True:
        warnings.append("Backups are enabled; first lab deploy should keep backup automation disabled.")
    if nested(values, "platformCapabilities", "enabled") is True:
        warnings.append("Optional platform capabilities are enabled; first lab deploy should keep them disabled.")

    return components, warnings, recommendations


def total(components: list[Component]) -> tuple[int, int, float, int]:
    return (
        sum(item.total_cpu_m for item in components),
        sum(item.total_memory_mi for item in components),
        sum(item.total_storage_gi for item in components),
        sum(item.replicas for item in components),
    )


def component_rows(components: list[Component], limit: int = 80) -> list[str]:
    rows = [
        "| Component | Category | Replicas | CPU request | Memory request | Storage | Note |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for item in components[:limit]:
        rows.append(
            f"| `{item.name}` | `{item.category}` | `{item.replicas}` | `{item.total_cpu_m}m` | `{item.total_memory_mi}Mi` | `{item.total_storage_gi:.1f}Gi` | {item.note or '-'} |"
        )
    if len(components) > limit:
        rows.append(f"| `+{len(components) - limit} more` | `-` | `-` | `-` | `-` | `-` | `-` |")
    return rows


def database_names(components: list[Component]) -> list[str]:
    return [item.name for item in components if item.category == "database"]


def progressive_waves(profile: dict[str, Any], db_names: list[str], batch_size: int) -> list[str]:
    lines = [
        "| Wave | Scope | Lab rule |",
        "|---|---|---|",
    ]
    for index, wave in enumerate(profile.get("progressiveWaves", []) or [], start=1):
        if isinstance(wave, dict):
            lines.append(f"| `{index}` | `{wave.get('name', 'wave')}` | {wave.get('description', '-')} |")
    if db_names:
        lines.append(f"| `database subsets` | `{min(batch_size, len(db_names))}` database(s) first | Keep the rest disabled until app connectivity is proven. |")
    lines.append(f"| `imported workloads` | `{batch_size}` service(s) per batch | Use `MIGRATION_IMPORT_BATCH=1`, then continue batch-by-batch. |")
    return lines


def overlay_text(profile: dict[str, Any], db_names: list[str], max_databases: int) -> str:
    enabled_dbs = set(db_names[:max_databases])
    lines = [
        "# Generated by scripts/lab_deploy_plan.py. Review before use.",
        "global:",
        "  replicaOverride: 1",
        "  skipPlaceholderWorkloads: true",
        "autoscaling:",
        "  enabled: false",
        "backup:",
        "  enabled: false",
        "  profile: disabled",
        "platformCapabilities:",
        "  enabled: false",
        "observability:",
        "  profile: disabled",
        "  prometheus:",
        "    enabled: false",
        "  grafana:",
        "    enabled: false",
        "  elasticsearch:",
        "    enabled: false",
        "  kibana:",
        "    enabled: false",
        "  logstash:",
        "    enabled: false",
        "  loki:",
        "    enabled: false",
        "  clickhouse:",
        "    enabled: false",
        "messaging:",
        "  kafka:",
        "    ui:",
        f"      enabled: {str(not profile.get('disableKafkaUi', True)).lower()}",
        "  redis:",
        "    sentinel:",
        "      enabled: false",
        "zabbixAgent:",
        f"  enabled: {str(not profile.get('disableZabbixAgent', True)).lower()}",
    ]
    if db_names:
        lines.extend(["databases:", "  instances:"])
        for name in db_names:
            lines.extend([f"    {name}:", f"      enabled: {str(name in enabled_dbs).lower()}"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe lab capacity and progressive deploy plan.")
    parser.add_argument("--values", default="helm/urban-platform-infra/values.yaml")
    parser.add_argument("--capacity", default="config/lab-capacity.yaml")
    parser.add_argument("--profile", default="")
    parser.add_argument("--output", default="reports/lab-deploy-plan.md")
    parser.add_argument("--overrides", default="reports/lab-deploy-values.yaml")
    parser.add_argument("--node-count", type=int, default=0)
    parser.add_argument("--node-cpu", default="")
    parser.add_argument("--node-memory", default="")
    parser.add_argument("--utilization-limit", type=float, default=0.0)
    parser.add_argument("--max-pods", type=int, default=0)
    parser.add_argument("--max-databases", type=int, default=-1)
    parser.add_argument("--batch-size", type=int, default=0)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    values = load_yaml(ROOT / args.values)
    capacity = load_yaml(ROOT / args.capacity)
    profile_name = args.profile or str(capacity.get("defaultProfile", "three-node-4g"))
    profile = nested(capacity, "profiles", profile_name)
    if not isinstance(profile, dict):
        raise SystemExit(f"Unknown lab capacity profile: {profile_name}")

    node_count = args.node_count or int(profile.get("nodes", 3))
    node_cpu_m = parse_cpu_m(args.node_cpu or profile.get("cpuPerNode", 4))
    node_memory_mi = parse_memory_mi(args.node_memory or profile.get("memoryPerNode", "4Gi"))
    utilization = args.utilization_limit or float(profile.get("capacityUtilizationLimit", 0.70))
    max_pods = args.max_pods or int(profile.get("maxPods", 80))
    max_databases = args.max_databases if args.max_databases >= 0 else int(profile.get("maxDatabases", 3))
    batch_size = args.batch_size or int(profile.get("importedBatchSize", 40))

    components, warnings, recommendations = collect_components(values)
    cpu_m, memory_mi, storage_gi, pods = total(components)
    usable_cpu_m = int(node_count * node_cpu_m * utilization)
    usable_memory_mi = int(node_count * node_memory_mi * utilization)
    db_names = database_names(components)

    findings: list[tuple[str, str]] = []
    if cpu_m > usable_cpu_m:
        findings.append(("ERROR", f"CPU requests exceed lab budget: {cpu_m}m > {usable_cpu_m}m."))
    if memory_mi > usable_memory_mi:
        findings.append(("ERROR", f"Memory requests exceed lab budget: {memory_mi}Mi > {usable_memory_mi}Mi."))
    if pods > max_pods:
        findings.append(("ERROR", f"Estimated pod count exceeds lab guardrail: {pods} > {max_pods}."))
    if len(db_names) > max_databases:
        findings.append(("WARN", f"Enabled database count is high for this lab: {len(db_names)} > first-wave limit {max_databases}."))
    for warning in warnings:
        findings.append(("WARN", warning))

    output = ROOT / args.output
    overrides = ROOT / args.overrides
    output.parent.mkdir(parents=True, exist_ok=True)
    overrides.parent.mkdir(parents=True, exist_ok=True)
    overrides.write_text(overlay_text(profile, db_names, max_databases), encoding="utf-8")

    lines = [
        "# Lab Capacity And Progressive Deploy Plan",
        "",
        "This report is public-safe. It uses committed Helm defaults and lab sizing inputs only; it does not read kubeconfigs, private inventories, node addresses, credentials, image layers, or project data.",
        "",
        f"- Profile: `{profile_name}`",
        f"- Nodes: `{node_count}`",
        f"- Node CPU: `{node_cpu_m}m`",
        f"- Node memory: `{node_memory_mi}Mi`",
        f"- Utilization limit: `{utilization:.2f}`",
        f"- Usable CPU budget: `{usable_cpu_m}m`",
        f"- Usable memory budget: `{usable_memory_mi}Mi`",
        f"- Estimated CPU requests: `{cpu_m}m`",
        f"- Estimated memory requests: `{memory_mi}Mi`",
        f"- Estimated PVC storage: `{storage_gi:.1f}Gi`",
        f"- Estimated pods: `{pods}`",
        f"- Enabled databases: `{len(db_names)}`",
        f"- Generated lab override: `{args.overrides}`",
        f"- Result: `{'FAIL' if any(level == 'ERROR' for level, _ in findings) else ('WARN' if findings else 'PASS')}`",
        "",
        "## Progressive Waves",
        "",
        *progressive_waves(profile, db_names, batch_size),
        "",
        "## Estimated Components",
        "",
        *component_rows(components),
        "",
        "## Generated Override Intent",
        "",
        "- Keep `global.replicaOverride=1` for first-wave lab deploys.",
        "- Keep `global.skipPlaceholderWorkloads=true` until real/imported images are selected.",
        "- Keep observability, backups, optional capabilities, Kafka UI, Redis Sentinel, and Zabbix agent disabled first.",
        f"- Keep only the first `{max_databases}` database(s) enabled in the generated lab override.",
        f"- Keep imported application workloads to `{batch_size}` service(s) per batch.",
        "",
        "## Findings",
        "",
    ]
    if findings:
        lines.extend(f"- {level}: {message}" for level, message in findings)
    else:
        lines.append("- OK: Committed defaults fit the selected lab request budget.")
    if recommendations:
        lines.extend(["", "## Recommendations", ""])
        lines.extend(f"- {item}" for item in recommendations)
    lines.extend(
        [
            "",
            "## Example Commands",
            "",
            "```bash",
            f"make lab-deploy-plan LAB_DEPLOY_PROFILE={profile_name}",
            f"make deploy-auto HELM_EXTRA_ARGS=\"-f {args.overrides}\"",
            "make import-auto PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true MIGRATION_IMPORT_BATCH=1",
            "```",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Lab deploy plan written: {args.output}")
    print(f"Lab deploy override written: {args.overrides}")

    if args.strict and any(level == "ERROR" for level, _ in findings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
