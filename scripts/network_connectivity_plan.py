#!/usr/bin/env python3
"""Generate a public-safe network connectivity, egress, and service mesh plan."""
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


def select_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = config.get("profiles", {})
    if not isinstance(profiles, dict):
        raise SystemExit("Network connectivity config must contain a profiles mapping.")
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown network connectivity profile `{profile_name}`. Available profiles: {choices}")
    profile = profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Network connectivity profile `{profile_name}` must be a mapping.")
    return profile


def profile_findings(profile_name: str, profile: dict[str, Any], args: argparse.Namespace) -> list[str]:
    findings: list[str] = []
    network_policy = as_mapping(profile.get("networkPolicy"))
    service_mesh = as_mapping(profile.get("serviceMesh"))
    egress = as_mapping(profile.get("egress"))
    tls = as_mapping(profile.get("tls"))

    if not bool_value(profile.get("enabled"), False):
        findings.append(f"INFO: Profile `{profile_name}` is plan-only; committed values keep network automation disabled.")
    if bool_value(profile.get("requireTrafficInventory"), False) and not args.traffic_inventory:
        findings.append("WARN: Restricted networking requires a private traffic inventory before enforcement.")
    if bool_value(profile.get("requireDnsTlsEvidence"), False) and not args.dns_tls_evidence:
        findings.append("WARN: DNS and TLS ownership evidence is required before tightening routes or mesh policy.")
    if bool_value(profile.get("requireEgressReview"), False) and not args.egress_contract:
        findings.append("WARN: Production egress should use reviewed CIDRs, FQDN policy, or an owned egress gateway.")
    if bool_value(profile.get("requireMeshReadiness"), False) and not args.mesh_readiness:
        findings.append("WARN: Service mesh requires capacity, sidecar/proxy policy, health probe, and rollback readiness.")
    if bool_value(service_mesh.get("enabled"), False):
        findings.append("WARN: Service mesh enablement is intentionally opt-in and should start in permissive mode.")
    if bool_value(egress.get("requireExplicitCidrs"), False) and not args.egress_contract:
        findings.append("WARN: Explicit egress contracts are required before removing shared external web egress.")
    if bool_value(tls.get("requireTrustedIssuer"), False) and not args.dns_tls_evidence:
        findings.append("WARN: Trusted issuer or private CA readiness must be proven before production TLS enforcement.")
    if bool_value(network_policy.get("defaultDeny"), False):
        findings.append("INFO: Default-deny NetworkPolicy requires explicit DNS, ingress-controller, operator, and Kubernetes API allowances.")
    return findings or ["OK: Network connectivity settings are internally consistent."]


def result_from_findings(findings: list[str]) -> str:
    if any(item.startswith("ERROR:") for item in findings):
        return "FAIL"
    if any(item.startswith("WARN:") for item in findings):
        return "WARN"
    return "PASS"


def write_overrides(path: Path, profile_name: str, profile: dict[str, Any]) -> None:
    network_policy = as_mapping(profile.get("networkPolicy"))
    service_mesh = as_mapping(profile.get("serviceMesh"))
    egress = as_mapping(profile.get("egress"))
    dns = as_mapping(profile.get("dns"))
    tls = as_mapping(profile.get("tls"))
    lines = [
        "networkConnectivity:",
        "  enabled: false",
        f"  profile: {profile_name}",
        f"  mode: {profile.get('mode', 'baseline')}",
        f"  ingressClassName: {profile.get('ingressClassName', 'traefik')}",
        "  networkPolicy:",
        f"    enabled: {str(bool_value(network_policy.get('enabled'), True)).lower()}",
        f"    profile: {network_policy.get('profile', 'existing-defaults')}",
        f"    defaultDeny: {str(bool_value(network_policy.get('defaultDeny'), True)).lower()}",
        f"    dnsEgress: {str(bool_value(network_policy.get('dnsEgress'), True)).lower()}",
        f"    kubernetesApiEgress: {str(bool_value(network_policy.get('kubernetesApiEgress'), True)).lower()}",
        f"    externalWebEgress: {str(bool_value(network_policy.get('externalWebEgress'), False)).lower()}",
        "  serviceMesh:",
        f"    enabled: {str(bool_value(service_mesh.get('enabled'), False)).lower()}",
        f"    provider: {service_mesh.get('provider', 'none')}",
        f"    mtlsMode: {service_mesh.get('mtlsMode', 'disabled')}",
        f"    trafficPolicy: {service_mesh.get('trafficPolicy', 'disabled')}",
        "  egress:",
        f"    mode: {egress.get('mode', 'existing-rules')}",
        f"    requireExplicitCidrs: {str(bool_value(egress.get('requireExplicitCidrs'), False)).lower()}",
        "  dns:",
        f"    provider: {dns.get('provider', 'kube-dns')}",
        f"    namespace: {dns.get('namespace', 'kube-system')}",
        "  tls:",
        f"    mode: {tls.get('mode', 'ingress-secret')}",
        f"    requireTrustedIssuer: {str(bool_value(tls.get('requireTrustedIssuer'), False)).lower()}",
        "  reports:",
        "    plan: reports/network-connectivity-plan.md",
        "    overrides: reports/network-connectivity-values.yaml",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_report(args: argparse.Namespace, config: dict[str, Any], profile: dict[str, Any], findings: list[str]) -> str:
    controller = as_mapping(config.get("controller"))
    checks = config.get("requiredChecks", [])
    guardrails = config.get("guardrails", [])
    if not isinstance(checks, list):
        checks = []
    if not isinstance(guardrails, list):
        guardrails = []
    network_policy = as_mapping(profile.get("networkPolicy"))
    service_mesh = as_mapping(profile.get("serviceMesh"))
    egress = as_mapping(profile.get("egress"))
    dns = as_mapping(profile.get("dns"))
    tls = as_mapping(profile.get("tls"))
    result = result_from_findings(findings)
    traffic_inventory = "<private-traffic-inventory>" if args.redact_sensitive and args.traffic_inventory else (args.traffic_inventory or "-")
    egress_contract = "<private-egress-contract>" if args.redact_sensitive and args.egress_contract else (args.egress_contract or "-")
    lines = [
        "# Network Connectivity And Service Mesh Plan",
        "",
        "This report is public-safe. It does not install a service mesh, mutate NetworkPolicies, print private hostnames, expose node names, or list internal CIDR inventories.",
        "",
        f"- Profile: `{args.profile}`",
        f"- Enabled: `{str(bool_value(profile.get('enabled'), False)).lower()}`",
        f"- Mode: `{profile.get('mode', 'baseline')}`",
        f"- Ingress class: `{profile.get('ingressClassName', 'traefik')}`",
        f"- NetworkPolicy enabled: `{str(bool_value(network_policy.get('enabled'), True)).lower()}`",
        f"- NetworkPolicy profile: `{network_policy.get('profile', '-')}`",
        f"- Default deny: `{str(bool_value(network_policy.get('defaultDeny'), False)).lower()}`",
        f"- DNS egress: `{str(bool_value(network_policy.get('dnsEgress'), False)).lower()}`",
        f"- Kubernetes API egress: `{str(bool_value(network_policy.get('kubernetesApiEgress'), False)).lower()}`",
        f"- External web egress: `{str(bool_value(network_policy.get('externalWebEgress'), False)).lower()}`",
        f"- Service mesh enabled: `{str(bool_value(service_mesh.get('enabled'), False)).lower()}`",
        f"- Service mesh provider: `{service_mesh.get('provider', 'none')}`",
        f"- mTLS mode: `{service_mesh.get('mtlsMode', 'disabled')}`",
        f"- Traffic policy: `{service_mesh.get('trafficPolicy', 'disabled')}`",
        f"- Egress mode: `{egress.get('mode', 'existing-rules')}`",
        f"- Require explicit CIDRs: `{str(bool_value(egress.get('requireExplicitCidrs'), False)).lower()}`",
        f"- DNS provider: `{dns.get('provider', '-')}`",
        f"- TLS mode: `{tls.get('mode', '-')}`",
        f"- Traffic inventory: `{traffic_inventory}`",
        f"- Egress contract: `{egress_contract}`",
        f"- DNS/TLS evidence: `{str(args.dns_tls_evidence).lower()}`",
        f"- Mesh readiness: `{str(args.mesh_readiness).lower()}`",
        f"- Report: `{args.output or controller.get('report', '-')}`",
        f"- Values overlay: `{args.overrides or controller.get('overrides', '-')}`",
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
            "1. Keep existing default-deny NetworkPolicy and same-namespace rules as the baseline.",
            "2. Review DNS, Kubernetes API, ingress-controller, operator, and external egress allowances.",
            "3. Add private traffic inventory and egress contracts before removing broad lab egress.",
            "4. Rehearse TLS issuer, route, and health probe behavior before strict enforcement.",
            "5. Enable Linkerd or Istio only after capacity, progressive delivery, and rollback gates are ready.",
            "",
            "## Example Commands",
            "",
            "```bash",
            "make network-connectivity-plan NETWORK_CONNECTIVITY_PROFILE=lab-baseline IMPORT_REDACT=true",
            "make network-connectivity-plan NETWORK_CONNECTIVITY_PROFILE=production-restricted NETWORK_CONNECTIVITY_DNS_TLS_EVIDENCE=true IMPORT_REDACT=true",
            "make network-connectivity-plan NETWORK_CONNECTIVITY_PROFILE=mesh-linkerd NETWORK_CONNECTIVITY_MESH_READINESS=true IMPORT_REDACT=true",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe network connectivity, egress, and service mesh plan.")
    parser.add_argument("--config", default="config/network-connectivity.yaml")
    parser.add_argument("--profile", default="")
    parser.add_argument("--traffic-inventory", default="")
    parser.add_argument("--egress-contract", default="")
    parser.add_argument("--dns-tls-evidence", action="store_true")
    parser.add_argument("--mesh-readiness", action="store_true")
    parser.add_argument("--output", default="reports/network-connectivity-plan.md")
    parser.add_argument("--overrides", default="reports/network-connectivity-values.yaml")
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
    print(f"Network connectivity plan written: {output_path}")
    print(f"Network connectivity values overlay written: {overrides_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
