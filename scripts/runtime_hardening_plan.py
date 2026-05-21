#!/usr/bin/env python3
"""Generate a public-safe runtime hardening and admission policy plan."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - keeps the planner usable on lean operator hosts.
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
IMAGES_DIR = ROOT / "scripts" / "images"
if str(IMAGES_DIR) not in sys.path:
    sys.path.insert(0, str(IMAGES_DIR))

import promotion_plan  # noqa: E402


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"", "''", '""'}:
        return ""
    if value in {"[]", "[ ]"}:
        return []
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


def select_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = config.get("profiles", {})
    if not isinstance(profiles, dict):
        raise SystemExit("Runtime hardening config must contain a profiles mapping.")
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown runtime hardening profile `{profile_name}`. Available profiles: {choices}")
    profile = profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Runtime hardening profile `{profile_name}` must be a mapping.")
    return profile


def nested_get(data: dict[str, Any], path: list[str], default: Any = None) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def unique_images(values_path: Path) -> list[promotion_plan.ImageObject]:
    images = promotion_plan.images_from_file(values_path)
    return sorted({(image.source, image.path, image.reference): image for image in images}.values(), key=lambda item: (item.source, item.path))


def profile_findings(profile: dict[str, Any], values: dict[str, Any], images: list[promotion_plan.ImageObject]) -> list[str]:
    findings: list[str] = []
    enabled = bool_value(profile.get("enabled"), False)
    enforcement_mode = str(profile.get("enforcementMode", "audit"))
    namespace_enforce = nested_get(values, ["namespace", "podSecurity", "enforce"], "")
    read_only_root = nested_get(values, ["global", "security", "readOnlyRootFilesystem"], False)
    run_as_non_root = nested_get(values, ["global", "security", "runAsNonRoot"], False)
    allow_privilege_escalation = nested_get(values, ["global", "security", "allowPrivilegeEscalation"], True)
    seccomp_type = nested_get(values, ["global", "podSecurityContext", "seccompProfile", "type"], "")
    dropped = nested_get(values, ["global", "security", "capabilities", "drop"], [])
    missing_digest = [image for image in images if not image.digest]

    if not enabled:
        findings.append("INFO: Selected profile is disabled; output is advisory only.")
    if profile.get("podSecurityEnforce") and namespace_enforce != profile.get("podSecurityEnforce"):
        level = "ERROR" if enforcement_mode == "enforce" else "WARN"
        findings.append(f"{level}: Namespace Pod Security enforce is `{namespace_enforce}`, target is `{profile.get('podSecurityEnforce')}`.")
    if bool_value(profile.get("requireReadOnlyRootFilesystem"), False) and read_only_root is not True:
        level = "ERROR" if enforcement_mode == "enforce" else "WARN"
        findings.append(f"{level}: readOnlyRootFilesystem is not enabled globally.")
    if bool_value(profile.get("requireRunAsNonRoot"), False) and run_as_non_root is not True:
        findings.append("ERROR: runAsNonRoot must be true for selected profile.")
    if bool_value(profile.get("disallowPrivilegeEscalation"), False) and allow_privilege_escalation is not False:
        findings.append("ERROR: allowPrivilegeEscalation must be false for selected profile.")
    if bool_value(profile.get("requireRuntimeDefaultSeccomp"), False) and seccomp_type != "RuntimeDefault":
        findings.append("ERROR: RuntimeDefault seccomp is required for selected profile.")
    if bool_value(profile.get("requireDropAllCapabilities"), False) and "ALL" not in {str(item) for item in dropped}:
        findings.append("ERROR: selected profile requires dropping ALL Linux capabilities.")
    if bool_value(profile.get("requireDigestImages"), False) and missing_digest:
        level = "ERROR" if enforcement_mode == "enforce" else "WARN"
        findings.append(f"{level}: {len(missing_digest)} image reference(s) are not digest pinned.")
    if bool_value(profile.get("requireSignedImages"), False):
        findings.append("WARN: signed-image admission requires private signature policy and trust roots outside Git.")
    return findings or ["OK: Runtime hardening settings match the selected profile."]


def result_from_findings(findings: list[str]) -> str:
    if any(item.startswith("ERROR:") for item in findings):
        return "FAIL"
    if any(item.startswith("WARN:") for item in findings):
        return "WARN"
    return "PASS"


def write_overrides(path: Path, profile_name: str, profile: dict[str, Any]) -> None:
    lines = [
        "runtimeHardening:",
        "  enabled: false",
        f"  profile: {profile_name}",
        f"  enforcementMode: {profile.get('enforcementMode', 'audit')}",
        f"  policyEngine: {profile.get('policyEngine', 'none')}",
        "  podSecurity:",
        f"    targetEnforce: {profile.get('podSecurityEnforce', 'baseline')}",
        f"    targetAudit: {profile.get('podSecurityAudit', 'restricted')}",
        f"    targetWarn: {profile.get('podSecurityWarn', 'restricted')}",
        "  workloadSecurity:",
        f"    requireRunAsNonRoot: {str(bool_value(profile.get('requireRunAsNonRoot'), True)).lower()}",
        f"    requireReadOnlyRootFilesystem: {str(bool_value(profile.get('requireReadOnlyRootFilesystem'), False)).lower()}",
        f"    requireRuntimeDefaultSeccomp: {str(bool_value(profile.get('requireRuntimeDefaultSeccomp'), True)).lower()}",
        f"    requireDropAllCapabilities: {str(bool_value(profile.get('requireDropAllCapabilities'), True)).lower()}",
        f"    disallowPrivilegeEscalation: {str(bool_value(profile.get('disallowPrivilegeEscalation'), True)).lower()}",
        f"    disallowHostNamespaces: {str(bool_value(profile.get('disallowHostNamespaces'), True)).lower()}",
        "  images:",
        f"    requireDigestPins: {str(bool_value(profile.get('requireDigestImages'), False)).lower()}",
        f"    requireSignatureVerification: {str(bool_value(profile.get('requireSignedImages'), False)).lower()}",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_report(args: argparse.Namespace, config: dict[str, Any], profile: dict[str, Any], values: dict[str, Any], images: list[promotion_plan.ImageObject], findings: list[str]) -> str:
    controller = config.get("controller", {}) if isinstance(config.get("controller", {}), dict) else {}
    guardrails = config.get("guardrails", [])
    if not isinstance(guardrails, list):
        guardrails = []
    missing_digest = [image for image in images if not image.digest]
    result = result_from_findings(findings)
    lines = [
        "# Runtime Hardening And Admission Policy Plan",
        "",
        "This report is public-safe. It does not install admission controllers, mutate clusters, read image layers, print signing keys, or expose private registry data.",
        "",
        f"- Profile: `{args.profile}`",
        f"- Enabled: `{str(bool_value(profile.get('enabled'), False)).lower()}`",
        f"- Enforcement mode: `{profile.get('enforcementMode', 'audit')}`",
        f"- Policy engine: `{profile.get('policyEngine', 'none')}`",
        f"- Namespace enforce target: `{profile.get('podSecurityEnforce', '-')}`",
        f"- Current namespace enforce: `{nested_get(values, ['namespace', 'podSecurity', 'enforce'], '-')}`",
        f"- Read-only root required: `{str(bool_value(profile.get('requireReadOnlyRootFilesystem'), False)).lower()}`",
        f"- Digest image requirement: `{str(bool_value(profile.get('requireDigestImages'), False)).lower()}`",
        f"- Signed image requirement: `{str(bool_value(profile.get('requireSignedImages'), False)).lower()}`",
        f"- Images discovered: `{len(images)}`",
        f"- Images missing digest pins: `{len(missing_digest)}`",
        f"- Report: `{args.output}`",
        f"- Values overlay: `{args.overrides}`",
        f"- Result: `{result}`",
        "",
        "## Admission Checks",
        "",
    ]
    checks = controller.get("admissionChecks", [])
    if isinstance(checks, list):
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
            "1. Run `lab-audit` and fix rendered-manifest warnings.",
            "2. Promote production images by digest.",
            "3. Map writable paths before enabling read-only root filesystems.",
            "4. Enable Kyverno or another admission engine in a private overlay.",
            "5. Add signed-image admission only after trust roots and break-glass process are documented.",
            "",
            "## Example Commands",
            "",
            "```bash",
            "make runtime-hardening-plan RUNTIME_HARDENING_PROFILE=lab-audit IMPORT_REDACT=true",
            "make runtime-hardening-plan RUNTIME_HARDENING_PROFILE=production-restricted IMPORT_REDACT=true",
            "make policy",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe runtime hardening and admission policy plan.")
    parser.add_argument("--config", default="config/runtime-hardening.yaml")
    parser.add_argument("--values", default="helm/urban-platform-infra/values.yaml")
    parser.add_argument("--profile", default="")
    parser.add_argument("--output", default="reports/runtime-hardening-plan.md")
    parser.add_argument("--overrides", default="reports/runtime-hardening-values.yaml")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--redact-sensitive", action="store_true")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    values_path = Path(args.values)
    output_path = Path(args.output)
    overrides_path = Path(args.overrides)
    if not config_path.is_absolute():
        config_path = (ROOT / config_path).resolve()
    if not values_path.is_absolute():
        values_path = (ROOT / values_path).resolve()
    if not output_path.is_absolute():
        output_path = (ROOT / output_path).resolve()
    if not overrides_path.is_absolute():
        overrides_path = (ROOT / overrides_path).resolve()

    config = load_yaml_file(config_path)
    args.profile = args.profile or str(config.get("defaultProfile", "disabled"))
    profile = select_profile(config, args.profile)
    values = load_yaml_file(values_path)
    images = unique_images(values_path)
    findings = profile_findings(profile, values, images)
    write_overrides(overrides_path, args.profile, profile)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generate_report(args, config, profile, values, images, findings), encoding="utf-8")
    print(f"Runtime hardening plan written: {output_path}")
    print(f"Runtime hardening values overlay written: {overrides_path}")
    if args.strict and result_from_findings(findings) == "FAIL" and bool_value(profile.get("enabled"), False):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
