#!/usr/bin/env python3
"""Generate a public-safe ingress and edge migration plan."""
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


def nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def bool_from_text(value: str | bool | None, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def public_value(value: str, redact_sensitive: bool, placeholder: str) -> str:
    if not value:
        return ""
    return placeholder if redact_sensitive else value


def profile_config(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = config.get("profiles", {})
    if not isinstance(profiles, dict):
        raise SystemExit("Edge migration config must contain a profiles mapping.")
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown edge migration profile `{profile_name}`. Available profiles: {choices}")
    profile = profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Edge migration profile `{profile_name}` must be a mapping.")
    return profile


def source_allowlist_count(values: dict[str, Any], allowed_cidrs: str) -> tuple[bool, int]:
    allowlist = nested(values, "ingress", "sourceAllowList", default={})
    enabled = isinstance(allowlist, dict) and bool(allowlist.get("enabled", False))
    cidrs = []
    if isinstance(allowlist, dict):
        cidrs.extend(str(item).strip() for item in allowlist.get("cidrs", []) if str(item).strip())
        cidrs.extend(str(allowlist.get("cidrsText", "")).split())
    cidrs.extend(allowed_cidrs.split())
    return enabled or bool(allowed_cidrs.strip()), len(list(dict.fromkeys(cidrs)))


def tls_mode(values: dict[str, Any], tls_cert_file: str, tls_key_file: str) -> str:
    tls = nested(values, "ingress", "tls", default={})
    if not isinstance(tls, dict) or tls.get("enabled", True) is False:
        return "disabled"
    external_tls = nested(values, "secretManagement", "externalSecrets", "ingressTls", "enabled", default=False)
    if external_tls:
        return "external-secret"
    if tls_cert_file or tls_key_file:
        return "provided-cert-files"
    if tls.get("createSecret", True) is False:
        return "existing-secret"
    cert_manager = tls.get("certManager", {}) if isinstance(tls.get("certManager", {}), dict) else {}
    self_signed = tls.get("selfSigned", {}) if isinstance(tls.get("selfSigned", {}), dict) else {}
    if cert_manager.get("enabled", True) and self_signed.get("enabled", True):
        return "cert-manager-self-signed"
    if cert_manager.get("enabled", True):
        return "cert-manager"
    return "inline-or-manual"


def findings(
    *,
    ingress_enabled: bool,
    ingress_class: str,
    ingress_host: str,
    tls_enabled: bool,
    tls_mode_name: str,
    tls_cert_file: str,
    tls_key_file: str,
    source_allowlist_enabled: bool,
    profile: dict[str, Any],
) -> list[str]:
    result: list[str] = []
    if not ingress_enabled:
        result.append("WARN: Ingress is disabled; public edge cutover will not create routes.")
    if ingress_class == "traefik" and not ingress_host and tls_enabled:
        result.append("WARN: Traefik TLS is enabled but no ingress host was provided in values or MIGRATION_INGRESS_HOST.")
    if bool(profile.get("requireTls", True)) and tls_mode_name == "disabled":
        result.append("ERROR: Selected edge profile requires TLS, but ingress TLS is disabled.")
    if bool(tls_cert_file) != bool(tls_key_file):
        result.append("ERROR: Both MIGRATION_TLS_CERT_FILE and MIGRATION_TLS_KEY_FILE are required when providing certificate files.")
    if ingress_class == "traefik" and not source_allowlist_enabled and bool(profile.get("sourceAllowListRecommended", False)):
        result.append("WARN: Source allowlist is not enabled; review public route exposure before production cutover.")
    if ingress_class == "none":
        result.append("INFO: Internal-only profile selected; route candidates should stay unapplied.")
    return result or ["OK: Edge migration settings are internally consistent."]


def generate_report(args: argparse.Namespace, config: dict[str, Any], values: dict[str, Any]) -> str:
    default_profile = str(config.get("defaultProfile", "traefik-public"))
    selected_profile = args.profile or default_profile
    profile = profile_config(config, selected_profile)
    ingress_enabled = bool_from_text(args.ingress_enabled, bool(nested(values, "ingress", "enabled", default=True)))
    ingress_class = args.ingress_class or str(nested(values, "ingress", "className", default=profile.get("ingressClassName", "traefik")))
    webserver = args.webserver or str(nested(values, "webserver", "provider", default=profile.get("webserverProvider", "nginx")))
    ingress_host = args.ingress_host or str(nested(values, "ingress", "host", default="") or nested(values, "global", "cluster", "domain", default=""))
    tls_enabled = bool(nested(values, "ingress", "tls", "enabled", default=True))
    tls_secret_name = str(nested(values, "ingress", "tls", "secretName", default="urban-platform-tls"))
    tls_mode_name = tls_mode(values, args.tls_cert_file, args.tls_key_file)
    source_allowlist_enabled, source_allowlist_count_value = source_allowlist_count(values, args.allowed_cidrs)
    ssl_redirect = bool(nested(values, "ingress", "sslRedirect", default=True))
    force_ssl_redirect = bool(nested(values, "ingress", "forceSslRedirect", default=True))
    report_findings = findings(
        ingress_enabled=ingress_enabled,
        ingress_class=ingress_class,
        ingress_host=ingress_host,
        tls_enabled=tls_enabled,
        tls_mode_name=tls_mode_name,
        tls_cert_file=args.tls_cert_file,
        tls_key_file=args.tls_key_file,
        source_allowlist_enabled=source_allowlist_enabled,
        profile=profile,
    )
    result = "FAIL" if any(item.startswith("ERROR:") for item in report_findings) else ("WARN" if any(item.startswith("WARN:") for item in report_findings) else "PASS")
    phases = config.get("phases", [])
    checks = config.get("checks", [])
    guardrails = profile.get("guardrails", [])
    if not isinstance(phases, list):
        phases = []
    if not isinstance(checks, list):
        checks = []
    if not isinstance(guardrails, list):
        guardrails = []

    lines = [
        "# Ingress And Edge Migration Plan",
        "",
        "This report is public-safe. It does not print private DNS names, VIPs, node addresses, TLS private keys, certificate contents, or route backend names from private projects.",
        "",
        f"- Profile: `{selected_profile}`",
        f"- Namespace: `{args.namespace}`",
        f"- Ingress enabled: `{str(ingress_enabled).lower()}`",
        f"- Ingress class: `{ingress_class}`",
        f"- Webserver provider: `{webserver}`",
        f"- Public host configured: `{str(bool(ingress_host)).lower()}`",
        f"- Public host: `{public_value(ingress_host, args.redact_sensitive, '<ingress-host>') or '-'}`",
        f"- TLS enabled: `{str(tls_enabled).lower()}`",
        f"- TLS mode: `{tls_mode_name}`",
        f"- TLS secret: `{public_value(tls_secret_name, args.redact_sensitive, '<tls-secret>') or '-'}`",
        f"- HTTP redirect: `{str(ssl_redirect or force_ssl_redirect).lower()}`",
        f"- Source allowlist enabled: `{str(source_allowlist_enabled).lower()}`",
        f"- Source allowlist entries: `{source_allowlist_count_value}`",
        f"- Require backend Service before apply: `{str(bool(profile.get('requireBackendServiceBeforeApply', True))).lower()}`",
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

    lines.extend(
        [
            "",
            "## Edge Conversion Rules",
            "",
            "- Compose services that publish host ports `80` or `443` should become Kubernetes Services plus Ingress routes.",
            "- Compose nginx edge gateways should move external routing to Traefik Ingress and remain as internal backends only when still needed.",
            "- Compose Traefik services should not be imported as a second edge controller when RKE2 bundled Traefik is selected.",
            "- Generated Ingress candidates are written before apply; execution applies only candidates whose backend Services already exist.",
            "- TLS can come from an existing secret, provided cert/key files, cert-manager issuer, External Secrets, or self-signed lab fallback.",
            "- Provided cert/key files map to `MIGRATION_TLS_CERT_FILE` and `MIGRATION_TLS_KEY_FILE`.",
            "- Review source allowlist settings before opening production routes.",
            "",
            "## Guardrails",
            "",
        ]
    )
    for guardrail in guardrails:
        lines.append(f"- {guardrail}")

    lines.extend(["", "## Required Checks", ""])
    for check in checks:
        lines.append(f"- {check}")

    lines.extend(["", "## Findings", ""])
    for finding in report_findings:
        lines.append(f"- {finding}")

    lines.extend(
        [
            "",
            "## Example Commands",
            "",
            "```bash",
            "make edge-migration-plan IMPORT_REDACT=true MIGRATION_INGRESS_HOST=app.example.invalid",
            "make import-migrate PROJECT_PATH=/path/to/compose-project MIGRATION_STAGE=manifests MIGRATION_EXECUTE=true MIGRATION_INGRESS_HOST=app.example.invalid",
            "make deploy-auto DEPLOY_INGRESS_HOST=app.example.invalid DEPLOY_ALLOWED_CIDRS=\"203.0.113.0/24\"",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe ingress and edge migration plan.")
    parser.add_argument("--config", default=str(ROOT / "config/edge-migration.yaml"))
    parser.add_argument("--values", default=str(ROOT / "helm/urban-platform-infra/values.yaml"))
    parser.add_argument("--profile", default="")
    parser.add_argument("--output", default=str(ROOT / "reports/edge-migration-plan.md"))
    parser.add_argument("--namespace", default="urban-platform")
    parser.add_argument("--ingress-class", default="")
    parser.add_argument("--webserver", default="")
    parser.add_argument("--ingress-host", default="")
    parser.add_argument("--ingress-enabled", default="")
    parser.add_argument("--tls-cert-file", default="")
    parser.add_argument("--tls-key-file", default="")
    parser.add_argument("--allowed-cidrs", default="")
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
    print(f"Edge migration plan written: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
