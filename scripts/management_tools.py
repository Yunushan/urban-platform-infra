#!/usr/bin/env python3
"""Plan and explicitly deploy optional platform-management tools.

The repository owns the catalog and safety gates, while each upstream project
owns its chart or container configuration.  This command therefore never
embeds credentials or silently installs tools: Helm installs require a private
values file and explicit confirmation, and Compose installs require a private
environment file plus explicit confirmation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - CI installs PyYAML.
    raise SystemExit("PyYAML is required for management-tool checks.") from exc


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/management-tools.yaml"
DEFAULT_VALUES = ROOT / "helm/urban-platform-infra/values.yaml"
EXPECTED_TOOLS = {
    "rancher",
    "portainer",
    "headlamp",
    "devtron",
    "freelens",
    "k9s",
    "komodo",
    "arcane",
}
HELM_MODEL = "in-cluster-helm"
COMPOSE_MODEL = "external-docker-compose"
VALID_MODELS = {HELM_MODEL, COMPOSE_MODEL, "desktop", "cli"}
VERSION_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
IMAGE_DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$", re.IGNORECASE)
VERSION_OUTPUT_RE = re.compile(r"(?<!\d)v?(\d+\.\d+\.\d+)(?!\d)")
MISSING = object()
HOST_PATH_ENV_KEYS = {
    "KOMODO_BACKUPS_PATH",
    "PERIPHERY_ROOT_DIRECTORY",
    "ARCANE_PROJECTS_DIRECTORY",
    "ARCANE_BUILDS_DIRECTORY",
}


def load_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise SystemExit(f"Required management-tool file does not exist: {path}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{path} must contain a YAML mapping.")
    return value


def bool_value(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def is_mutable_pin(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"latest", "stable", "edge", "main", "*"} or ":latest" in normalized or "@latest" in normalized


def is_version_pin(value: Any) -> bool:
    normalized = str(value or "").strip()
    return bool(normalized) and not is_mutable_pin(normalized) and bool(VERSION_RE.fullmatch(normalized))


def catalog_tools(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tools = catalog.get("tools")
    if not isinstance(tools, dict):
        raise SystemExit("Management-tool catalog must contain a tools mapping.")
    return tools


def validate_catalog(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if catalog.get("version") != 1:
        errors.append("catalog version must be 1")
    if catalog.get("enabledByDefault") is not False:
        errors.append("enabledByDefault must be false")
    selection = catalog.get("selection")
    if not isinstance(selection, dict):
        errors.append("selection must be a mapping")
    else:
        for key in [
            "requireExplicitSelection",
            "requirePinnedVersions",
            "requireDigestPins",
            "allowMutableTags",
            "allowDockerSocket",
            "requirePrivateValuesForHelm",
            "requirePrivateEnvironmentFile",
            "requireTlsForInCluster",
            "productionRequiresPrivateApproval",
        ]:
            expected = key not in {"allowMutableTags", "allowDockerSocket"}
            if selection.get(key) is not expected:
                errors.append(f"selection.{key} must be {str(expected).lower()}")
    update_policy = catalog.get("updatePolicy")
    if not isinstance(update_policy, dict):
        errors.append("updatePolicy must be a mapping")
    else:
        for key in ["autoUpdate"]:
            if update_policy.get(key) is not False:
                errors.append(f"updatePolicy.{key} must be false")
        for key in ["requirePullRequest", "requireRollbackPlan", "requireReleaseEvidence"]:
            if update_policy.get(key) is not True:
                errors.append(f"updatePolicy.{key} must be true")

    tools = catalog.get("tools")
    if not isinstance(tools, dict):
        return errors
    missing = sorted(EXPECTED_TOOLS - set(tools))
    unexpected = sorted(set(tools) - EXPECTED_TOOLS)
    if missing:
        errors.append(f"tools missing: {', '.join(missing)}")
    if unexpected:
        errors.append(f"tools contain unsupported entries: {', '.join(unexpected)}")
    for name in sorted(EXPECTED_TOOLS & set(tools)):
        tool = tools[name]
        if not isinstance(tool, dict):
            errors.append(f"tool {name} must be a mapping")
            continue
        model = str(tool.get("deploymentModel", ""))
        if model not in VALID_MODELS:
            errors.append(f"tool {name} has an invalid deploymentModel: {model}")
        if not tool.get("versionSource"):
            errors.append(f"tool {name} must declare versionSource")
        for field in ["version", "chartVersion", "image", "imageTag"]:
            if field in tool and is_mutable_pin(tool.get(field)):
                errors.append(f"tool {name} must not use a mutable {field} pin")
        if "version" in tool and tool.get("version") not in (None, "") and not is_version_pin(tool.get("version")):
            errors.append(f"tool {name} version must be an exact version")
        if model == HELM_MODEL:
            for field in ["repoName", "repoUrl", "chart", "releaseName", "namespace"]:
                if not str(tool.get(field, "")).strip():
                    errors.append(f"tool {name} must declare {field}")
            if tool.get("valuesRequired") is not True:
                errors.append(f"tool {name} must require a private values file")
            if tool.get("tlsRequired") is not True:
                errors.append(f"tool {name} must require TLS")
            if name == "rancher" and tool.get("helmMajor") != 3:
                errors.append("tool rancher must require Helm major version 3")
            if "helmMajor" in tool and not isinstance(tool.get("helmMajor"), int):
                errors.append(f"tool {name} helmMajor must be an integer")
            if "minHelmVersion" in tool and not is_version_pin(tool.get("minHelmVersion")):
                errors.append(f"tool {name} minHelmVersion must be an exact version")
            checks = tool.get("requiredValueChecks", [])
            if checks not in (None, "") and not isinstance(checks, list):
                errors.append(f"tool {name} requiredValueChecks must be a list")
            elif isinstance(checks, list):
                for index, check in enumerate(checks):
                    if not isinstance(check, dict):
                        errors.append(f"tool {name} requiredValueChecks[{index}] must be a mapping")
                        continue
                    if not str(check.get("path", "")).strip():
                        errors.append(f"tool {name} requiredValueChecks[{index}] must declare path")
                    if check.get("operator") not in {"equals", "not_equals", "nonempty", "one_of"}:
                        errors.append(f"tool {name} requiredValueChecks[{index}] has an invalid operator")
                    if check.get("operator") in {"equals", "not_equals", "one_of"} and "expected" not in check:
                        errors.append(f"tool {name} requiredValueChecks[{index}] must declare expected")
                    if check.get("operator") == "one_of" and not isinstance(check.get("expected"), list):
                        errors.append(f"tool {name} requiredValueChecks[{index}] one_of expected must be a list")
        elif model in {"desktop", "cli"}:
            if not is_version_pin(tool.get("version")):
                errors.append(f"tool {name} must declare an exact workstation version")
        elif model == COMPOSE_MODEL:
            for field in ["composeFile", "composeProfile"]:
                if not str(tool.get(field, "")).strip():
                    errors.append(f"tool {name} must declare {field}")
            if tool.get("requiresDockerSocket") is not True:
                errors.append(f"tool {name} must declare Docker socket risk")
            if tool.get("externalHostRequired") is not True:
                errors.append(f"tool {name} must require an external host")
            for field in ["imageEnv", "requiredSecretEnv", "requiredEnv"]:
                if not isinstance(tool.get(field), list) or not tool.get(field):
                    errors.append(f"tool {name} must declare a non-empty {field} list")
    return errors


def load_and_validate_catalog(path: Path) -> dict[str, Any]:
    catalog = load_mapping(path)
    errors = validate_catalog(catalog)
    if errors:
        raise SystemExit("Invalid management-tool catalog:\n- " + "\n- ".join(errors))
    return catalog


def parse_selection(raw: str) -> list[str]:
    selected = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if "all" in selected:
        raise SystemExit("Use an explicit comma-separated management-tool selection; `all` is not accepted.")
    if len(selected) != len(set(selected)):
        raise SystemExit("Management-tool selection contains duplicates.")
    return selected


def parse_chart_versions(raw: str) -> dict[str, str]:
    versions: dict[str, str] = {}
    for item in raw.split(","):
        entry = item.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise SystemExit("MANAGEMENT_TOOLS_CHART_VERSIONS must use name=version entries separated by commas.")
        name, version = (part.strip().lower() for part in entry.split("=", 1))
        if not name or not version:
            raise SystemExit("MANAGEMENT_TOOLS_CHART_VERSIONS contains an empty tool name or chart version.")
        if name in versions:
            raise SystemExit(f"Management-tool chart versions contain a duplicate entry for {name}.")
        versions[name] = version
    return versions


def management_values(values: dict[str, Any]) -> dict[str, Any]:
    block = values.get("managementTools", {})
    if block in (None, ""):
        return {}
    if not isinstance(block, dict):
        raise SystemExit("managementTools in Helm values must be a mapping.")
    return block


def enabled_from_values(catalog: dict[str, Any], values: dict[str, Any]) -> list[str]:
    block = management_values(values)
    return [
        name
        for name in sorted(catalog_tools(catalog))
        if isinstance(block.get(name), dict) and bool_value(block[name].get("enabled"))
    ]


def validate_selected(selected: list[str], catalog: dict[str, Any]) -> None:
    unknown = sorted(set(selected) - set(catalog_tools(catalog)))
    if unknown:
        available = ", ".join(sorted(catalog_tools(catalog)))
        raise SystemExit(f"Unknown management tool(s): {', '.join(unknown)}. Available: {available}")


def tool_override(name: str, values: dict[str, Any]) -> dict[str, Any]:
    block = management_values(values)
    override = block.get(name, {})
    if override in (None, ""):
        return {}
    if not isinstance(override, dict):
        raise SystemExit(f"managementTools.{name} in Helm values must be a mapping.")
    return override


def selected_for_command(args: argparse.Namespace, catalog: dict[str, Any], values: dict[str, Any]) -> list[str]:
    explicit = parse_selection(args.selected)
    if explicit:
        validate_selected(explicit, catalog)
        return explicit
    if args.command == "plan":
        return enabled_from_values(catalog, values)
    raise SystemExit(f"{args.command} requires --selected with an explicit comma-separated tool list.")


def safe_relative_path(path: Path) -> bool:
    try:
        return os.path.commonpath([str(path.resolve()), str(ROOT.resolve())]) == str(ROOT.resolve())
    except ValueError:
        return False


def private_values_path(name: str, override: dict[str, Any], values_dir: str) -> Path:
    raw = str(override.get("valuesFile", "")).strip()
    if not raw and values_dir:
        raw = str(Path(values_dir).expanduser() / f"{name}.values.yaml")
    if not raw:
        raise SystemExit(
            f"managementTools.{name}.valuesFile is required; provide a private Helm values file "
            "or MANAGEMENT_TOOLS_VALUES_DIR."
        )
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise SystemExit(f"Private values file for {name} must be an absolute path: {path}")
    resolved = path.resolve()
    if safe_relative_path(resolved):
        raise SystemExit(f"Private values file for {name} must be outside the repository checkout: {resolved}")
    if not resolved.is_file():
        raise SystemExit(f"Private values file for {name} does not exist: {resolved}")
    return resolved


def nested_value(document: dict[str, Any], dotted_path: str) -> Any:
    current: Any = document
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def validate_private_values(name: str, tool: dict[str, Any], values_file: Path) -> None:
    checks = tool.get("requiredValueChecks", []) or []
    if not checks:
        return
    document = load_mapping(values_file)
    failures: list[str] = []
    for check in checks:
        path = str(check.get("path", "")).strip()
        operator = str(check.get("operator", "")).strip()
        actual = nested_value(document, path)
        expected = check.get("expected")
        failed = False
        if operator == "equals":
            failed = actual is MISSING or actual != expected
        elif operator == "not_equals":
            failed = actual is MISSING or actual == expected
        elif operator == "nonempty":
            failed = actual is MISSING or actual is None or (isinstance(actual, str) and not actual.strip()) or actual == []
        elif operator == "one_of":
            failed = actual is MISSING or not isinstance(expected, list) or actual not in expected
        if failed:
            failures.append(path)
    if failures:
        raise SystemExit(
            f"Private values for {name} failed required safety checks: {', '.join(sorted(set(failures)))}. "
            "Review the upstream chart values without placing secrets in the repository."
        )


def chart_version(
    name: str,
    catalog_tool: dict[str, Any],
    override: dict[str, Any],
    chart_versions: dict[str, str] | None = None,
) -> str:
    chart_versions = chart_versions or {}
    version = str(chart_versions.get(name, override.get("chartVersion", catalog_tool.get("chartVersion", "")))).strip()
    if not version:
        raise SystemExit(f"Pinned chartVersion is required for {name}; mutable or floating versions are disabled.")
    if not is_version_pin(version):
        raise SystemExit(f"Pinned chartVersion for {name} must be an exact numeric version, not `{version}`.")
    return version


def helm_version(helm: str) -> tuple[int, int, int]:
    try:
        completed = subprocess.run(
            [helm, "version", "--short"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise SystemExit(f"Helm executable could not be run: {helm}") from exc
    output = (completed.stdout + completed.stderr).strip()
    match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", output)
    if completed.returncode != 0 or not match:
        raise SystemExit(f"Could not determine the Helm major version from `{helm} version --short`.")
    return tuple(int(part) for part in match.groups())


def helm_major_version(helm: str) -> int:
    return helm_version(helm)[0]


def version_at_least(actual: tuple[int, int, int], minimum: str) -> bool:
    match = VERSION_RE.fullmatch(str(minimum).strip())
    if not match:
        return False
    parts = tuple(int(part) for part in re.findall(r"\d+", match.group(0))[:3])
    return actual >= parts


def display_chart_version(catalog_tool: dict[str, Any], override: dict[str, Any]) -> str:
    version = str(override.get("chartVersion", catalog_tool.get("chartVersion", ""))).strip()
    return version if version and is_version_pin(version) else "private exact chart pin required"


def is_digest_pinned_image(value: str) -> bool:
    normalized = value.strip()
    return bool(normalized) and not any(char.isspace() for char in normalized) and bool(IMAGE_DIGEST_RE.search(normalized))


def workstation_version(name: str, tool: dict[str, Any], override: dict[str, Any]) -> str:
    version = str(override.get("version", tool.get("version", ""))).strip()
    if not is_version_pin(version):
        raise SystemExit(f"{name} must declare an exact workstation version before it can be checked.")
    return version.lstrip("v")


def detected_workstation_version(output: str) -> str:
    match = VERSION_OUTPUT_RE.search(output)
    return match.group(1) if match else ""


def redact_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if safe_relative_path(Path(path)):
        return "<repository-path>"
    return "<private-path>" if normalized else ""


def read_env_file_keys(path: Path) -> dict[str, str]:
    if not path.is_absolute():
        raise SystemExit(f"Compose environment file must be an absolute path: {path}")
    if safe_relative_path(path):
        raise SystemExit("Compose environment files containing credentials must be outside the repository checkout.")
    if not path.is_file():
        raise SystemExit(f"Compose environment file does not exist: {path}")
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            result[key] = value.strip().strip("'\"")
    return result


def compose_values_environment(name: str, override: dict[str, Any]) -> dict[str, str]:
    field_map = {
        "komodo": {
            "externalHost": "KOMODO_HOST",
            "coreImage": "KOMODO_CORE_IMAGE",
            "peripheryImage": "KOMODO_PERIPHERY_IMAGE",
            "mongoImage": "KOMODO_MONGO_IMAGE",
            "peripheryRootDirectory": "PERIPHERY_ROOT_DIRECTORY",
        },
        "arcane": {
            "image": "ARCANE_IMAGE",
            "projectsDirectory": "ARCANE_PROJECTS_DIRECTORY",
            "buildsDirectory": "ARCANE_BUILDS_DIRECTORY",
        },
    }.get(name, {})
    return {
        environment_name: str(override[field]).strip()
        for field, environment_name in field_map.items()
        if str(override.get(field, "")).strip()
    }


def compose_context(
    args: argparse.Namespace,
    catalog: dict[str, Any],
    values: dict[str, Any],
    selected: list[str],
) -> tuple[dict[str, tuple[dict[str, str], Path | None]], dict[str, str]]:
    base_environment = {key: value for key, value in os.environ.items() if value}
    contexts: dict[str, tuple[dict[str, str], Path | None]] = {}
    aggregate: dict[str, str] = dict(base_environment)
    explicit_env_file = str(args.env_file).strip()
    for name in selected:
        override = tool_override(name, values)
        raw_env_file = explicit_env_file or str(override.get("environmentFile", "")).strip()
        env_file: Path | None = None
        environment = dict(base_environment)
        environment.update(compose_values_environment(name, override))
        if raw_env_file:
            env_file = Path(raw_env_file).expanduser()
            environment.update(read_env_file_keys(env_file))
            environment[f"{name.upper()}_ENV_FILE"] = str(env_file)
        aggregate.update(environment)
        contexts[name] = (environment, env_file)
    return contexts, aggregate


def missing_compose_environment(
    selected: list[str],
    catalog: dict[str, Any],
    environment: dict[str, str],
    contexts: dict[str, tuple[dict[str, str], Path | None]] | None = None,
) -> list[str]:
    missing: set[str] = set()
    selection = catalog.get("selection", {})
    require_digest_pins = isinstance(selection, dict) and bool_value(selection.get("requireDigestPins"))
    require_private_environment_file = isinstance(selection, dict) and bool_value(
        selection.get("requirePrivateEnvironmentFile")
    )
    for name in selected:
        tool = catalog_tools(catalog)[name]
        if require_private_environment_file and contexts is not None and contexts[name][1] is None:
            missing.add(f"{name}.environmentFile")
        for key in tool.get("imageEnv", []) + tool.get("requiredSecretEnv", []) + tool.get("requiredEnv", []):
            if not environment.get(str(key), "").strip():
                missing.add(str(key))
        for key in tool.get("imageEnv", []):
            value = environment.get(str(key), "").strip()
            if value and (is_mutable_pin(value) or ":latest" in value.lower()):
                raise SystemExit(f"{key} must be an exact image pin and cannot use a mutable tag.")
            if value and require_digest_pins and not is_digest_pinned_image(value):
                raise SystemExit(f"{key} must include an immutable sha256 digest (for example image:tag@sha256:<64-hex>).")
        for key in HOST_PATH_ENV_KEYS:
            value = environment.get(key, "").strip()
            if not value:
                continue
            if value and (not Path(value).is_absolute() or safe_relative_path(Path(value))):
                raise SystemExit(f"{key} must be an absolute host path outside the repository checkout.")
        if name == "komodo":
            host = environment.get("KOMODO_HOST", "").strip().lower()
            if host and not host.startswith("https://"):
                raise SystemExit("KOMODO_HOST must use https:// for the external Komodo management endpoint.")
    return sorted(missing)


def compose_file_for(tool: dict[str, Any]) -> Path:
    path = ROOT / str(tool.get("composeFile", ""))
    if not path.is_file():
        raise SystemExit(f"Compose integration file does not exist: {path}")
    return path


def report_header(title: str) -> list[str]:
    return [f"# {title}", "", f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}", ""]


def write_report(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def plan(args: argparse.Namespace, catalog: dict[str, Any], values: dict[str, Any]) -> int:
    selected = selected_for_command(args, catalog, values)
    all_tools = catalog_tools(catalog)
    enabled = set(enabled_from_values(catalog, values))
    lines = report_header("Management Tools Plan")
    lines.extend(
        [
            "This report is public-safe. It contains no credentials, private values, kubeconfigs, image digests, or private hostnames.",
            "All tools are disabled by default and are outside the normal platform `deploy` and CI paths.",
            "",
            f"Explicit selection: {'yes' if args.selected.strip() else 'no'}",
            f"Values-enabled tools: {', '.join(sorted(enabled)) if enabled else 'none'}",
            f"Plan selection: {', '.join(selected) if selected else 'none'}",
            "",
            "| Tool | Model | Status | Deployment boundary | Pin/TLS requirement |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for name in sorted(all_tools):
        tool = all_tools[name]
        override = tool_override(name, values)
        model = str(tool.get("deploymentModel"))
        is_selected = name in selected
        status = "selected" if is_selected else ("enabled in values" if name in enabled else "available")
        if model == HELM_MODEL:
            boundary = f"Helm {tool.get('chart')} in `{tool.get('namespace')}` as `{tool.get('releaseName')}`"
            helm_requirement = f"Helm v{tool['helmMajor']}; " if tool.get("helmMajor") else ""
            requirement = f"{helm_requirement}{display_chart_version(tool, override)}; TLS required"
        elif model == COMPOSE_MODEL:
            boundary = f"external Docker Compose profile `{tool.get('composeProfile')}`"
            requirement = "private pinned image refs; Docker socket risk"
        else:
            boundary = "operator workstation only; no cluster workload"
            requirement = f"version {tool.get('version', 'operator-selected')}"
        lines.append(f"| {tool.get('displayName', name)} | `{model}` | {status} | {boundary} | {requirement} |")
    lines.extend(
        [
            "",
            "## Required Controls",
            "",
            "- Use exact Helm chart versions and private values files for Kubernetes installations.",
            "- Use TLS, reviewed RBAC, durable storage, and external secret references before production enablement.",
            "- Keep Docker-socket tools on an external management host; do not mount the socket into the RKE2 workload cluster.",
            "- Install FreeLens and k9s on an operator workstation with a least-privilege kubeconfig context.",
            "- Updates are approval-only: review upstream release notes, run CI, capture rollback evidence, then change the pin.",
        ]
    )
    output = Path(args.output)
    if args.output:
        write_report(output, lines)
        print(f"Management-tool plan written: {redact_path(str(output))}")
    else:
        print("\n".join(lines))
    return 0


def run_command(command: list[str], environment: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(command))
    subprocess.run(command, check=True, env=environment)


def install_helm(args: argparse.Namespace, catalog: dict[str, Any], values: dict[str, Any]) -> int:
    selected = selected_for_command(args, catalog, values)
    all_tools = catalog_tools(catalog)
    chart_versions = parse_chart_versions(args.chart_versions)
    unknown_chart_versions = sorted(set(chart_versions) - set(all_tools))
    if unknown_chart_versions:
        raise SystemExit(f"Chart-version overrides reference unknown management tool(s): {', '.join(unknown_chart_versions)}")
    preflight: list[tuple[str, str, Path]] = []
    for name in selected:
        tool = all_tools[name]
        if tool.get("deploymentModel") != HELM_MODEL:
            raise SystemExit(
                f"{name} is `{tool.get('deploymentModel')}`; use management-tools-plan or "
                "management-tools-compose-plan for its supported deployment boundary."
            )
        version = chart_version(name, tool, tool_override(name, values), chart_versions)
        path = private_values_path(name, tool_override(name, values), args.values_dir)
        validate_private_values(name, tool, path)
        preflight.append((name, version, path))

    if not args.execute or not args.confirm:
        raise SystemExit("Refusing Helm mutation. Set --execute and --confirm after reviewing the management-tool plan.")

    actual_helm = helm_version(args.helm)
    for name, _, _ in preflight:
        required_helm_major = all_tools[name].get("helmMajor")
        if required_helm_major is not None and actual_helm[0] != int(required_helm_major):
            raise SystemExit(
                f"{name} requires Helm v{required_helm_major} for its upstream installation contract; "
                f"the selected Helm executable is v{'.'.join(str(part) for part in actual_helm)}. Set MANAGEMENT_TOOLS_HELM to a compatible Helm v{required_helm_major} binary."
            )
        minimum_helm = str(all_tools[name].get("minHelmVersion", "")).strip()
        if minimum_helm and not version_at_least(actual_helm, minimum_helm):
            raise SystemExit(
                f"{name} requires Helm >= {minimum_helm}; the selected Helm executable is "
                f"v{'.'.join(str(part) for part in actual_helm)}. Set MANAGEMENT_TOOLS_HELM to a compatible Helm binary."
            )

    for name, version, values_file in preflight:
        tool = all_tools[name]
        helm = args.helm
        run_command([helm, "repo", "add", str(tool["repoName"]), str(tool["repoUrl"]), "--force-update"])
        run_command([helm, "repo", "update", str(tool["repoName"])])
        command = [
            helm,
            "upgrade",
            "--install",
            str(tool["releaseName"]),
            str(tool["chart"]),
            "--namespace",
            str(tool["namespace"]),
            "--create-namespace",
            "--version",
            version,
            "--values",
            str(values_file),
            "--wait",
            "--atomic",
            "--timeout",
            args.timeout,
            "--history-max",
            "10",
        ]
        if args.kubeconfig:
            command.extend(["--kubeconfig", args.kubeconfig])
        run_command(command)
        print(f"Installed {name} using its pinned chart and private values file.")
    return 0


def install_compose(args: argparse.Namespace, catalog: dict[str, Any], values: dict[str, Any]) -> int:
    selected = selected_for_command(args, catalog, values)
    all_tools = catalog_tools(catalog)
    contexts, aggregate_environment = compose_context(args, catalog, values, selected)
    missing = missing_compose_environment(selected, catalog, aggregate_environment, contexts)
    if missing:
        raise SystemExit("Missing private Compose environment values: " + ", ".join(missing))
    if not args.execute or not args.confirm:
        raise SystemExit("Refusing Compose mutation. Set --execute and --confirm after reviewing the management-tool plan.")
    tool_name_to_file: dict[tuple[Path, Path | None], list[str]] = {}
    for name in selected:
        tool = all_tools[name]
        if tool.get("deploymentModel") != COMPOSE_MODEL:
            raise SystemExit(f"{name} is not an external Docker Compose tool.")
        compose_file = compose_file_for(tool)
        env_file = contexts[name][1]
        tool_name_to_file.setdefault((compose_file, env_file), []).append(name)
    for (compose_file, env_file), names in tool_name_to_file.items():
        profiles = [str(all_tools[name]["composeProfile"]) for name in names]
        command = [args.container_tool, "compose", "-f", str(compose_file)]
        if env_file:
            command.extend(["--env-file", str(env_file)])
        for profile in profiles:
            command.extend(["--profile", profile])
        run_command([*command, "config", "--quiet"], environment=contexts[names[0]][0])
        command.extend(["up", "-d"])
        run_command(command, environment=contexts[names[0]][0])
        print(f"Started external Compose profile(s): {', '.join(names)}")
    return 0


def compose_plan(args: argparse.Namespace, catalog: dict[str, Any], values: dict[str, Any]) -> int:
    selected = selected_for_command(args, catalog, values)
    all_tools = catalog_tools(catalog)
    contexts, aggregate_environment = compose_context(args, catalog, values, selected)
    missing = missing_compose_environment(selected, catalog, aggregate_environment, contexts)
    lines = report_header("External Management Tools Compose Plan")
    lines.extend(
        [
            "This report is public-safe. Secret values are checked without being printed.",
            "The plan does not start containers. Use the guarded `management-tools-compose-up` target for an explicit external-host deployment.",
            "",
            f"Selected tools: {', '.join(selected)}",
            f"Private environment file supplied: {'yes' if any(env_file for _, env_file in contexts.values()) else 'no'}",
            f"Missing required environment keys: {', '.join(missing) if missing else 'none detected'}",
            "",
            "| Tool | Profile | Compose file | Required boundary |",
            "| --- | --- | --- | --- |",
        ]
    )
    for name in selected:
        tool = all_tools[name]
        if tool.get("deploymentModel") != COMPOSE_MODEL:
            raise SystemExit(f"{name} is not an external Docker Compose tool.")
        compose_file = compose_file_for(tool)
        lines.append(
            f"| {tool.get('displayName', name)} | `{tool.get('composeProfile')}` | `{compose_file.relative_to(ROOT).as_posix()}` | external host; Docker socket is required |"
        )
    lines.extend(
        [
            "",
            "Required before execution:",
            "",
            "- Use exact, non-mutable image references supplied only through the private environment file.",
            "- Keep Komodo and Arcane on a dedicated external management host; do not run their Docker socket mounts in the RKE2 workload cluster.",
            "- Put the private environment file outside this checkout and provide TLS through an external reverse proxy or reviewed upstream configuration.",
        ]
    )
    write_report(Path(args.output), lines)
    print(f"External Compose plan written: {redact_path(args.output)}")
    return 0


def workstation_check(args: argparse.Namespace, catalog: dict[str, Any], values: dict[str, Any]) -> int:
    selected = selected_for_command(args, catalog, values)
    all_tools = catalog_tools(catalog)
    results: list[tuple[str, str, str, str]] = []
    failed = False
    for name in selected:
        tool = all_tools[name]
        if tool.get("deploymentModel") not in {"desktop", "cli"}:
            raise SystemExit(f"{name} is `{tool.get('deploymentModel')}`; workstation checks only support desktop/CLI tools.")
        expected = workstation_version(name, tool, tool_override(name, values))
        command_name = str(tool.get("command", name)).strip()
        command_path = shutil.which(command_name)
        if not command_path:
            results.append((name, "MISSING", expected, "command is not available on PATH"))
            failed = True
            continue
        version_args = [str(value) for value in tool.get("versionArgs", [])]
        try:
            completed = subprocess.run(
                [command_path, *version_args],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            results.append((name, "BROKEN", expected, "version probe failed or timed out"))
            failed = True
            continue
        detected = detected_workstation_version((completed.stdout or "") + "\n" + (completed.stderr or ""))
        if completed.returncode != 0 or not detected:
            results.append((name, "BROKEN", expected, "version probe returned no usable version"))
            failed = True
        elif detected != expected:
            results.append((name, "VERSION-MISMATCH", expected, f"detected {detected}"))
            failed = True
        else:
            results.append((name, "OK", expected, f"detected {detected}"))

    lines = report_header("Management Tools Workstation Check")
    lines.extend(
        [
            "This report contains command status and exact versions only; it does not include kubeconfig contents or credentials.",
            "The check never downloads, installs, or changes FreeLens, k9s, or the cluster.",
            "",
            "| Tool | Status | Expected | Detail |",
            "| --- | --- | --- | --- |",
        ]
    )
    for name, status, expected, detail in results:
        lines.append(f"| {all_tools[name].get('displayName', name)} | `{status}` | `{expected}` | {detail} |")
    write_report(Path(args.output), lines)
    print(f"Management-tool workstation report written: {redact_path(args.output)}")
    for name, status, expected, detail in results:
        print(f"[{status}] {name}: expected {expected}; {detail}")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Management-tool catalog path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List supported management tools")
    list_parser.set_defaults(handler="list")

    plan_parser = subparsers.add_parser("plan", help="Write a public-safe selection and readiness plan")
    plan_parser.add_argument("--values", default=str(DEFAULT_VALUES))
    plan_parser.add_argument("--selected", default="")
    plan_parser.add_argument("--output", default="reports/management-tools-plan.md")
    plan_parser.set_defaults(handler="plan")

    install_parser = subparsers.add_parser("install", help="Explicitly install selected in-cluster Helm tools")
    install_parser.add_argument("--values", default=str(DEFAULT_VALUES))
    install_parser.add_argument("--selected", default="")
    install_parser.add_argument("--values-dir", default="")
    install_parser.add_argument("--chart-versions", default="", help="Comma-separated exact chart pins, for example headlamp=0.32.0")
    install_parser.add_argument("--helm", default="helm")
    install_parser.add_argument("--kubeconfig", default="")
    install_parser.add_argument("--timeout", default="20m")
    install_parser.add_argument("--execute", action="store_true")
    install_parser.add_argument("--confirm", action="store_true")
    install_parser.set_defaults(handler="install")

    compose_parser = subparsers.add_parser("compose", help="Plan or explicitly start external Compose tools")
    compose_parser.add_argument("--values", default=str(DEFAULT_VALUES))
    compose_parser.add_argument("--selected", default="")
    compose_parser.add_argument("--env-file", default="")
    compose_parser.add_argument("--container-tool", default="docker")
    compose_parser.add_argument("--output", default="reports/management-tools-compose-plan.md")
    compose_parser.add_argument("--execute", action="store_true")
    compose_parser.add_argument("--confirm", action="store_true")
    compose_parser.set_defaults(handler="compose")

    workstation_parser = subparsers.add_parser(
        "workstation",
        help="Check exact versions of selected FreeLens or k9s workstation tools",
    )
    workstation_parser.add_argument("--values", default=str(DEFAULT_VALUES))
    workstation_parser.add_argument("--selected", default="")
    workstation_parser.add_argument("--output", default="reports/management-tools-workstation.md")
    workstation_parser.set_defaults(handler="workstation")
    return parser


def list_tools(catalog: dict[str, Any]) -> int:
    print("Tool\tModel\tDefault\tVersion/Chart\tBoundary")
    for name in sorted(catalog_tools(catalog)):
        tool = catalog_tools(catalog)[name]
        model = str(tool.get("deploymentModel"))
        if model == HELM_MODEL:
            pin = "private chart pin required"
            if tool.get("helmMajor"):
                pin += f"; Helm v{tool['helmMajor']}"
            if tool.get("minHelmVersion"):
                pin += f" (>= {tool['minHelmVersion']})"
            boundary = f"{tool.get('chart')} -> {tool.get('namespace')}"
        elif model == COMPOSE_MODEL:
            pin = "private image pins required"
            boundary = f"external profile {tool.get('composeProfile')}"
        else:
            pin = str(tool.get("version", "operator-selected"))
            boundary = "operator workstation"
        print(f"{name}\t{model}\tfalse\t{pin}\t{boundary}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    catalog = load_and_validate_catalog(Path(args.config).expanduser())
    if args.handler == "list":
        return list_tools(catalog)
    values = load_mapping(Path(args.values).expanduser())
    if args.handler == "plan":
        return plan(args, catalog, values)
    if args.handler == "install":
        return install_helm(args, catalog, values)
    if args.handler == "compose":
        if args.execute:
            return install_compose(args, catalog, values)
        return compose_plan(args, catalog, values)
    if args.handler == "workstation":
        return workstation_check(args, catalog, values)
    parser.error(f"Unsupported management-tool command: {args.handler}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
