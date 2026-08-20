#!/usr/bin/env python3
"""Check the repository's mandatory and optional operator tool contract."""

from __future__ import annotations

import argparse
import importlib.util
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: Path) -> dict[str, Any]:
    if importlib.util.find_spec("yaml") is None:
        raise SystemExit("PyYAML is required to read the tooling contract.")
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"Tooling contract must be a mapping: {path}")
    return data


def run_version(command: str, args: list[str]) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [command, *args],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    detail = output.splitlines()[0] if output else f"exit code {completed.returncode}"
    return completed.returncode == 0, detail


def command_for(tool: dict[str, Any]) -> tuple[str, str] | None:
    alternatives = tool.get("alternatives")
    commands = alternatives if isinstance(alternatives, list) else tool.get("commands", [])
    if not isinstance(commands, list):
        return None
    for candidate in commands:
        command = str(candidate).strip()
        if command and shutil.which(command):
            return command, str(Path(shutil.which(command) or command))
    return None


def scopes_for_requested(requested: str, scopes: dict[str, Any]) -> list[str]:
    if requested != "all":
        if requested not in scopes:
            raise SystemExit(f"Unknown tooling scope {requested!r}; choose {', '.join(sorted(scopes))}.")
        return [requested]
    return [name for name in scopes if name != "all"]


def merge_tools(scope_names: list[str], scopes: dict[str, Any]) -> tuple[set[str], set[str]]:
    mandatory: set[str] = set()
    optional: set[str] = set()
    for scope_name in scope_names:
        scope = scopes.get(scope_name) or {}
        mandatory.update(str(name) for name in scope.get("mandatory", []) or [])
        optional.update(str(name) for name in scope.get("optional", []) or [])
    optional.difference_update(mandatory)
    return mandatory, optional


def check_tool(name: str, tool: dict[str, Any], required: bool) -> dict[str, str]:
    found = command_for(tool)
    display = str(tool.get("displayName", name))
    if not found:
        return {
            "name": name,
            "display": display,
            "class": "mandatory" if required else "optional",
            "status": "MISSING" if required else "OPTIONAL-MISSING",
            "detail": "No supported command is available on PATH.",
        }
    command, path = found
    version_args = tool.get("versionArgs", [])
    probe_ok, version = run_version(command, [str(value) for value in version_args])
    expected_version = str(tool.get("expectedVersion", "")).strip()
    if not probe_ok:
        status = "BROKEN"
        detail = f"{path} - version probe failed: {version}"
    elif expected_version and expected_version not in version:
        status = "VERSION-MISMATCH"
        detail = f"{path} - {version} (expected {expected_version})"
    else:
        status = "OK"
        detail = f"{path} - {version}"
    return {
        "name": name,
        "display": display,
        "class": "mandatory" if required else "optional",
        "status": status,
        "detail": detail,
    }


def render_report(
    contract: dict[str, Any],
    requested_scope: str,
    scope_names: list[str],
    results: list[dict[str, str]],
) -> str:
    failures = [item for item in results if item["status"] in {"MISSING", "BROKEN", "VERSION-MISMATCH"} and item["class"] == "mandatory"]
    lines = [
        "# Tool Inventory",
        "",
        "This report is public-safe. It contains tool names, versions, and generic availability only; it does not include private hosts, paths, kubeconfigs, credentials, or command output beyond the first version line.",
        "",
        f"- Requested scope: `{requested_scope}`",
        f"- Evaluated scopes: `{', '.join(scope_names)}`",
        f"- Host platform: `{platform.system()} {platform.release()}`",
        f"- Result: `{'FAIL' if failures else 'PASS'}`",
        "",
        "| Tool | Requirement | Status | Detail |",
        "|---|---|---|---|",
    ]
    for item in sorted(results, key=lambda value: (value["class"], value["name"])):
        detail = item["detail"].replace("|", "\\|")
        lines.append(f"| `{item['display']}` | `{item['class']}` | `{item['status']}` | {detail} |")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `docker-or-podman` is an alternative group; one of the two is sufficient for image workflows.",
            "- The built-in Python load runner does not require k6, Vegeta, or hey. Those tools remain optional for teams that standardize on them.",
            "- `fio` is a benchmark tool. Never run destructive I/O benchmarks against a production data volume; use a dedicated test volume and an approved maintenance window.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check mandatory and optional repository tools.")
    parser.add_argument("--config", default="config/tooling.yaml")
    parser.add_argument("--scope", default="all")
    parser.add_argument("--output", default="")
    parser.add_argument("--no-fail", action="store_true")
    args = parser.parse_args(argv)

    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    contract = load_yaml(config_path)
    scopes = contract.get("scopes", {})
    tools = contract.get("tools", {})
    if not isinstance(scopes, dict) or not isinstance(tools, dict):
        raise SystemExit("Tooling contract must define scopes and tools mappings.")
    scope_names = scopes_for_requested(args.scope, scopes)
    mandatory, optional = merge_tools(scope_names, scopes)
    unknown = sorted((mandatory | optional) - set(tools))
    if unknown:
        raise SystemExit(f"Tooling scopes reference unknown tools: {', '.join(unknown)}")

    results = [
        check_tool(name, tools[name], True)
        for name in sorted(mandatory)
    ] + [
        check_tool(name, tools[name], False)
        for name in sorted(optional)
    ]
    for item in results:
        print(f"[{item['status']}] {item['display']}: {item['detail']}")

    if args.output:
        output_path = Path(args.output).expanduser()
        if not output_path.is_absolute():
            output_path = ROOT / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(render_report(contract, args.scope, scope_names, results), encoding="utf-8")
        print(f"Wrote tool inventory report: {output_path}")

    blocking_statuses = {"MISSING", "BROKEN", "VERSION-MISMATCH"}
    return 0 if args.no_fail or not any(item["class"] == "mandatory" and item["status"] in blocking_statuses for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
