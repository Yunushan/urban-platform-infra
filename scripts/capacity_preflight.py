#!/usr/bin/env python3
"""Fail-fast public-safe cluster capacity guard for lab deploy/import paths."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from lab_deploy_plan import (  # noqa: E402
    collect_components,
    component_rows,
    database_names,
    load_yaml,
    nested,
    parse_cpu_m,
    parse_memory_mi,
    total,
)


def optional_int(value: str, default: int) -> int:
    text = str(value or "").strip()
    if text in {"", "0", "-1"}:
        return default
    return int(text)


def optional_float(value: str, default: float) -> float:
    text = str(value or "").strip()
    if text in {"", "0", "0.0"}:
        return default
    return float(text)


def bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def setting(mapping: dict[str, Any], key: str, default: Any = None) -> Any:
    value = mapping.get(key, default)
    return default if value is None else value


def add(finding_list: list[tuple[str, str]], level: str, message: str) -> None:
    finding_list.append((level, message))


def result_for(findings: list[tuple[str, str]]) -> str:
    if any(level == "ERROR" for level, _ in findings):
        return "FAIL"
    if findings:
        return "WARN"
    return "PASS"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a public-safe capacity preflight before deploy/import work.")
    parser.add_argument("--values", default="helm/urban-platform-infra/values.yaml")
    parser.add_argument("--capacity", default="config/lab-capacity.yaml")
    parser.add_argument("--environment-profiles", default="config/environment-profiles.yaml")
    parser.add_argument("--capacity-profile", default="")
    parser.add_argument("--environment-profile", default="lab")
    parser.add_argument("--node-count", default="")
    parser.add_argument("--node-cpu", default="")
    parser.add_argument("--node-memory", default="")
    parser.add_argument("--utilization-limit", default="")
    parser.add_argument("--max-pods", default="")
    parser.add_argument("--max-databases", default="")
    parser.add_argument("--max-imported-workloads", default="")
    parser.add_argument("--import-batch", default="")
    parser.add_argument("--capacity-evidence", default="")
    parser.add_argument("--output", default="reports/capacity-preflight.md")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    values = load_yaml(ROOT / args.values)
    capacity = load_yaml(ROOT / args.capacity)
    environment_profiles = load_yaml(ROOT / args.environment_profiles)

    capacity_profile_name = args.capacity_profile or str(capacity.get("defaultProfile", "three-node-4g"))
    capacity_profile = nested(capacity, "profiles", capacity_profile_name)
    if not isinstance(capacity_profile, dict):
        raise SystemExit(f"Unknown capacity profile: {capacity_profile_name}")

    environment_profile_name = args.environment_profile or "lab"
    environment_profile = nested(environment_profiles, "profiles", environment_profile_name)
    if not isinstance(environment_profile, dict):
        raise SystemExit(f"Unknown environment profile: {environment_profile_name}")

    node_count = optional_int(args.node_count, int(setting(capacity_profile, "nodes", 3)))
    node_cpu_m = parse_cpu_m(args.node_cpu or setting(capacity_profile, "cpuPerNode", 4))
    node_memory_mi = parse_memory_mi(args.node_memory or setting(capacity_profile, "memoryPerNode", "4Gi"))
    utilization = optional_float(args.utilization_limit, float(setting(capacity_profile, "capacityUtilizationLimit", 0.70)))
    max_pods = optional_int(args.max_pods, int(setting(capacity_profile, "maxPods", 80)))
    max_databases = optional_int(args.max_databases, int(setting(capacity_profile, "maxDatabases", 3)))
    max_imported_workloads = optional_int(
        args.max_imported_workloads,
        int(setting(capacity_profile, "importedBatchSize", 40)),
    )
    import_batch = str(args.import_batch or setting(environment_profile, "importBatch", "auto"))

    components, warnings, recommendations = collect_components(values)
    cpu_m, memory_mi, storage_gi, pods = total(components)
    usable_cpu_m = int(node_count * node_cpu_m * utilization)
    usable_memory_mi = int(node_count * node_memory_mi * utilization)
    db_names = database_names(components)

    findings: list[tuple[str, str]] = []
    if cpu_m > usable_cpu_m:
        add(findings, "ERROR", f"Requested CPU exceeds selected capacity budget: {cpu_m}m > {usable_cpu_m}m.")
    if memory_mi > usable_memory_mi:
        add(findings, "ERROR", f"Requested memory exceeds selected capacity budget: {memory_mi}Mi > {usable_memory_mi}Mi.")
    if pods > max_pods:
        add(findings, "ERROR", f"Estimated pod count exceeds selected guardrail: {pods} > {max_pods}.")
    if len(db_names) > max_databases:
        add(findings, "WARN", f"Enabled database count exceeds first-wave lab guardrail: {len(db_names)} > {max_databases}. Use the generated lab values overlay before deploy.")

    env_kind = str(setting(environment_profile, "environment", environment_profile_name))
    migration_profile = str(setting(environment_profile, "migrationProfile", ""))
    if env_kind == "lab":
        if migration_profile != "lab":
            add(findings, "ERROR", "Lab environment profile must use `migrationProfile: lab`.")
        if import_batch == "all":
            add(findings, "ERROR", "Lab capacity preflight refuses `MIGRATION_IMPORT_BATCH=all`; use `auto` or a numbered batch.")
        if max_imported_workloads > int(setting(capacity_profile, "importedBatchSize", 40)):
            add(findings, "WARN", "Imported workload batch size is above the selected lab profile default.")
        if not bool_value(nested(values, "global", "skipPlaceholderWorkloads"), False):
            add(findings, "ERROR", "Lab values must keep `global.skipPlaceholderWorkloads=true`.")
        if nested(values, "global", "replicaOverride") not in {1, "1"}:
            add(findings, "ERROR", "Lab values must keep `global.replicaOverride=1` for first-wave deploys.")
    elif env_kind == "production" and not args.capacity_evidence:
        add(findings, "ERROR", "Production capacity preflight requires a private capacity evidence path.")

    for warning in warnings:
        add(findings, "WARN", warning)

    if recommendations:
        add(findings, "INFO", "Review lab recommendations before enabling optional components.")

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Cluster Capacity Preflight",
        "",
        "This report is public-safe. It uses committed Helm values, committed capacity profiles, and explicit sizing inputs only. It does not read kubeconfigs, inventories, node addresses, project files, image layers, credentials, or private evidence contents.",
        "",
        f"- Result: `{result_for(findings)}`",
        f"- Environment profile: `{environment_profile_name}`",
        f"- Environment kind: `{env_kind}`",
        f"- Migration profile: `{migration_profile or '-'}`",
        f"- Capacity profile: `{capacity_profile_name}`",
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
        f"- First-wave database limit: `{max_databases}`",
        f"- Imported workload batch limit: `{max_imported_workloads}`",
        f"- Import batch mode: `{import_batch}`",
        f"- Capacity evidence: `{'provided' if args.capacity_evidence else 'not-provided'}`",
        "",
        "## Findings",
        "",
    ]
    if findings:
        lines.extend(f"- **{level}** - {message}" for level, message in findings)
    else:
        lines.append("- **OK** - Selected values fit the capacity guardrail.")

    lines.extend(
        [
            "",
            "## Estimated Components",
            "",
            *component_rows(components, limit=60),
            "",
            "## Next Actions",
            "",
            "- Run `make lab-deploy-plan` when this report warns about first-wave database or optional-component pressure.",
            "- Use `make deploy-auto HELM_EXTRA_ARGS=\"-f reports/lab-deploy-values.yaml\"` for constrained labs.",
            "- Keep `MIGRATION_IMPORT_BATCH=auto` or a numbered batch until capacity is proven.",
            "- Use production profiles only with private capacity, backup, storage, registry, and release evidence reviewed.",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Cluster capacity preflight written: {args.output}")

    if args.strict and any(level == "ERROR" for level, _ in findings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
