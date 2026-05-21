#!/usr/bin/env python3
"""Generate a public-safe database migration controller plan."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - keeps the planner usable on lean operator hosts.
    yaml = None


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_FAMILY = {"postgresql", "postgis", "timescaledb"}


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


def bool_from_text(value: str | bool | None, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def public_path(path: str, redact_sensitive: bool) -> str:
    if not redact_sensitive:
        return path
    normalized = path.replace("\\", "/")
    if normalized.startswith("/var/lib/urban-platform/private"):
        return "/var/lib/urban-platform/private/<path>"
    return normalized


def profile_config(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = config.get("profiles", {})
    if not isinstance(profiles, dict):
        raise SystemExit("Database migration config must contain a profiles mapping.")
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown database migration profile `{profile_name}`. Available profiles: {choices}")
    profile = profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Database migration profile `{profile_name}` must be a mapping.")
    return profile


def database_instance_counts(values: dict[str, Any]) -> tuple[int, int, dict[str, int]]:
    instances = values.get("databases", {}).get("instances", {})
    if not isinstance(instances, dict):
        return 0, 0, {}
    counts: dict[str, int] = {}
    enabled_total = 0
    for config in instances.values():
        if not isinstance(config, dict):
            continue
        if config.get("enabled", True) is False:
            continue
        engine = str(config.get("engine", "postgresql"))
        counts[engine] = counts.get(engine, 0) + 1
        enabled_total += 1
    postgres_family_total = sum(count for engine, count in counts.items() if engine in POSTGRES_FAMILY)
    return enabled_total, postgres_family_total, counts


def target_map_count(path: str) -> tuple[str, int]:
    if not path:
        return "not-configured", 0
    target_path = Path(path).expanduser()
    if not target_path.exists():
        return "missing", 0
    try:
        data = load_yaml_file(target_path)
    except Exception:
        return "unreadable", 0
    targets = data.get("databaseTargets", data)
    if isinstance(targets, dict):
        return "present", len(targets)
    return "invalid", 0


def findings(
    *,
    profile_name: str,
    allow_secret_material: bool,
    skip_unavailable: bool,
    target_status: str,
    postgres_family_total: int,
) -> list[str]:
    result: list[str] = []
    if not allow_secret_material:
        result.append("WARN: Database execution will not run dump/restore until MIGRATION_ALLOW_SECRET_MATERIAL=true is set on the trusted operator machine.")
    if target_status == "missing":
        result.append("WARN: Private database target map is missing; import-auto can initialize it, but restore will skip targets until mappings exist.")
    elif target_status in {"unreadable", "invalid"}:
        result.append("ERROR: Private database target map exists but is not readable as a mapping.")
    if profile_name == "production" and skip_unavailable:
        result.append("WARN: Production profile should use MIGRATION_SKIP_UNAVAILABLE_DATABASES=false so unreachable sources fail the run.")
    if postgres_family_total == 0:
        result.append("INFO: No enabled PostgreSQL-family Helm targets were detected in the selected values file.")
    return result or ["OK: Database migration controller settings are internally consistent."]


def generate_report(args: argparse.Namespace, config: dict[str, Any], values: dict[str, Any]) -> str:
    default_profile = str(config.get("defaultProfile", "lab"))
    selected_profile = args.profile or default_profile
    profile = profile_config(config, selected_profile)
    skip_unavailable = bool_from_text(args.skip_unavailable_databases, bool(profile.get("skipUnavailableSources", True)))
    allow_secret_material = bool_from_text(args.allow_secret_material, False)
    target_status, target_count = target_map_count(args.db_targets)
    enabled_total, postgres_family_total, engine_counts = database_instance_counts(values)
    engine_config = config.get("engines", {})
    phases = config.get("phases", [])
    guardrails = profile.get("guardrails", [])
    if not isinstance(engine_config, dict):
        engine_config = {}
    if not isinstance(phases, list):
        phases = []
    if not isinstance(guardrails, list):
        guardrails = []
    report_findings = findings(
        profile_name=selected_profile,
        allow_secret_material=allow_secret_material,
        skip_unavailable=skip_unavailable,
        target_status=target_status,
        postgres_family_total=postgres_family_total,
    )
    result = "FAIL" if any(item.startswith("ERROR:") for item in report_findings) else ("WARN" if any(item.startswith("WARN:") for item in report_findings) else "PASS")

    lines = [
        "# Database Migration Controller Plan",
        "",
        "This report is public-safe. It does not print DSNs, passwords, source service names, private node addresses, dump contents, or target secret values.",
        "",
        f"- Profile: `{selected_profile}`",
        f"- Namespace: `{args.namespace}`",
        f"- Dump directory: `{public_path(args.dump_dir, args.redact_sensitive)}`",
        f"- Database target map: `{public_path(args.db_targets, args.redact_sensitive)}`",
        f"- Target map status: `{target_status}`",
        f"- Target map entries: `{target_count}`",
        f"- Enabled Helm database targets: `{enabled_total}`",
        f"- PostgreSQL-family Helm targets: `{postgres_family_total}`",
        f"- PostgreSQL client image: `{args.postgres_client_image}`",
        f"- Skip unavailable sources: `{str(skip_unavailable).lower()}`",
        f"- Secret-bearing execution allowed: `{str(allow_secret_material).lower()}`",
        f"- Dump format: `{profile.get('dumpFormat', 'custom')}`",
        f"- Result: `{result}`",
        "",
        "## Controller Phases",
        "",
        "| Phase | Automation |",
        "|---|---|",
    ]
    for phase in phases:
        if isinstance(phase, dict):
            lines.append(f"| `{phase.get('name', '-')}` | {phase.get('automation', '-')} |")

    lines.extend(["", "## Engine Support", "", "| Engine | Status | Dump | Restore |", "|---|---|---|---|"])
    for engine, engine_data in sorted(engine_config.items()):
        if not isinstance(engine_data, dict):
            continue
        lines.append(
            f"| `{engine}` | `{engine_data.get('status', '-')}` | `{engine_data.get('sourceTool', '-')}` | `{engine_data.get('restoreTool', '-')}` |"
        )

    lines.extend(["", "## Enabled Helm Target Engines", ""])
    if engine_counts:
        for engine, count in sorted(engine_counts.items()):
            lines.append(f"- `{engine}`: `{count}`")
    else:
        lines.append("- No enabled database targets found in selected values.")

    lines.extend(["", "## Dump Restore Contract", ""])
    for flag in profile.get("dumpFlags", []):
        lines.append(f"- Dump flag: `{flag}`")
    for flag in profile.get("restoreFlags", []):
        lines.append(f"- Restore flag: `{flag}`")
    lines.extend(
        [
            "- PostgreSQL-family migration uses `pg_dump --format=custom` and `pg_restore --clean --if-exists --no-owner`.",
            "- If local PostgreSQL tools are missing, the migration uses `MIGRATION_POSTGRES_CLIENT_IMAGE` with the selected container tool.",
            "- `MIGRATION_SKIP_UNAVAILABLE_DATABASES` controls whether unreachable sources are skipped or fail the database stage.",
            "- Optional engines remain target-map scaffolds until their operator, managed service, or external target profile is declared.",
        ]
    )

    lines.extend(["", "## Guardrails", ""])
    for guardrail in guardrails:
        lines.append(f"- {guardrail}")

    lines.extend(["", "## Findings", ""])
    for finding in report_findings:
        lines.append(f"- {finding}")

    lines.extend(
        [
            "",
            "## Example Commands",
            "",
            "```bash",
            "make database-migration-plan IMPORT_REDACT=true",
            "make import-migrate PROJECT_PATH=/path/to/compose-project MIGRATION_STAGE=databases MIGRATION_EXECUTE=true MIGRATION_ALLOW_SECRET_MATERIAL=true",
            "make import-auto PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true MIGRATION_ALLOW_SECRET_MATERIAL=true",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe database migration controller plan.")
    parser.add_argument("--config", default=str(ROOT / "config/database-migration.yaml"))
    parser.add_argument("--values", default=str(ROOT / "helm/urban-platform-infra/values.yaml"))
    parser.add_argument("--profile", default="")
    parser.add_argument("--output", default=str(ROOT / "reports/database-migration-plan.md"))
    parser.add_argument("--namespace", default="urban-platform")
    parser.add_argument("--dump-dir", default="/var/lib/urban-platform/private/db-dumps")
    parser.add_argument("--db-targets", default="/var/lib/urban-platform/private/db-targets.yaml")
    parser.add_argument("--postgres-client-image", default="docker.io/library/postgres:18.3")
    parser.add_argument("--skip-unavailable-databases", default="")
    parser.add_argument("--allow-secret-material", default="")
    parser.add_argument("--redact-sensitive", action="store_true")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = (ROOT / config_path).resolve()
    values_path = Path(args.values)
    if not values_path.is_absolute():
        values_path = (ROOT / values_path).resolve()
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (ROOT / output_path).resolve()

    config = load_yaml_file(config_path)
    values = load_yaml_file(values_path)
    report = generate_report(args, config, values)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Database migration controller plan written: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
