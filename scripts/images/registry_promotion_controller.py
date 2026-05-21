#!/usr/bin/env python3
"""Generate a public-safe registry promotion controller plan."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - keeps the planner usable on lean operator hosts.
    yaml = None

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import promotion_plan  # noqa: E402


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


def public_registry(registry: str, redact_sensitive: bool) -> str:
    if not registry:
        return ""
    return "<private-registry>" if redact_sensitive else registry


def select_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = config.get("profiles", {})
    if not isinstance(profiles, dict):
        raise SystemExit("Registry promotion config must contain a profiles mapping.")
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown registry promotion profile `{profile_name}`. Available profiles: {choices}")
    profile = profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Registry promotion profile `{profile_name}` must be a mapping.")
    return profile


def unique_images(values_path: Path) -> list[promotion_plan.ImageObject]:
    images = promotion_plan.images_from_file(values_path)
    return sorted({(image.source, image.path, image.reference): image for image in images}.values(), key=lambda item: (item.source, item.path))


def policy_sets(policy_path: Path) -> tuple[dict[str, Any], set[str], set[tuple[str, str]], str]:
    policy = promotion_plan.read_policy(policy_path).get("policy", {})
    blocked = {str(tag).strip() for tag in policy.get("disallowMutableTags", [])}
    approved = {
        (str(item.get("repository", "")).strip(), str(item.get("tag", "")).strip())
        for item in policy.get("approvedRuntimeImages", [])
        if isinstance(item, dict)
    }
    default_tag = str(policy.get("defaultApplicationTag", "0.1.0"))
    return policy, blocked, approved, default_tag


def build_findings(
    *,
    profile_name: str,
    profile: dict[str, Any],
    registry: str,
    image_pull_secret: str,
    missing_digest_count: int,
    mutable_count: int,
    invalid_digest_count: int,
    placeholder_count: int,
) -> list[str]:
    findings: list[str] = []
    enabled = bool_value(profile.get("enabled"), False)
    execution_mode = str(profile.get("executionMode", "plan"))
    if not enabled:
        findings.append(f"INFO: Profile `{profile_name}` is disabled; controller output is advisory only.")
    if bool_value(profile.get("registryRequired"), False) and not registry:
        findings.append("ERROR: Selected profile requires REGISTRY_PROMOTION_REGISTRY.")
    if bool_value(profile.get("imagePullSecretRequired"), False) and not image_pull_secret:
        findings.append("ERROR: Selected profile requires a registry image pull secret.")
    if bool_value(profile.get("requireDigestPins"), False) and missing_digest_count:
        level = "ERROR" if execution_mode == "enforce" else "WARN"
        findings.append(f"{level}: Selected profile requires digest pins; {missing_digest_count} image reference(s) are missing digests.")
    if mutable_count:
        findings.append(f"ERROR: {mutable_count} image reference(s) use mutable tags.")
    if invalid_digest_count:
        findings.append(f"ERROR: {invalid_digest_count} image reference(s) have invalid digest syntax.")
    if execution_mode == "enforce" and placeholder_count:
        findings.append(f"WARN: {placeholder_count} placeholder application image reference(s) still need private promoted images.")
    return findings or ["OK: Registry promotion controller settings are internally consistent."]


def result_from_findings(findings: list[str]) -> str:
    if any(item.startswith("ERROR:") for item in findings):
        return "FAIL"
    if any(item.startswith("WARN:") for item in findings):
        return "WARN"
    return "PASS"


def write_overrides(
    *,
    output: Path,
    profile_name: str,
    profile: dict[str, Any],
    registry: str,
    image_pull_secret: str,
    credential_source: str,
    redact_sensitive: bool,
) -> None:
    registry_value = public_registry(registry, redact_sensitive) or "private-registry.example.invalid/platform"
    pull_secret = image_pull_secret or "registry-credentials"
    lines = [
        "global:",
        f"  imageRegistry: {registry_value!r}",
        "  imagePullSecrets:",
        f"    - {pull_secret}",
        "  imagePullPolicy: IfNotPresent",
        "imagePromotionController:",
        "  enabled: false",
        f"  profile: {profile_name}",
        f"  executionMode: {profile.get('executionMode', 'plan')}",
        f"  imageMode: {profile.get('imageMode', 'registry')}",
        f"  registry: {registry_value!r}",
        f"  imagePullSecret: {pull_secret}",
        f"  credentialSource: {credential_source}",
        f"  requireDigestPins: {str(bool_value(profile.get('requireDigestPins'), False)).lower()}",
        f"  requireVulnerabilityScan: {str(bool_value(profile.get('requireVulnerabilityScan'), False)).lower()}",
        f"  requireSbom: {str(bool_value(profile.get('requireSbom'), False)).lower()}",
        f"  requireSignatureOrAttestation: {str(bool_value(profile.get('requireSignatureOrAttestation'), False)).lower()}",
        f"  requirePromotionRecord: {str(bool_value(profile.get('requirePromotionRecord'), False)).lower()}",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_report(
    *,
    args: argparse.Namespace,
    config: dict[str, Any],
    profile: dict[str, Any],
    images: list[promotion_plan.ImageObject],
    findings: list[str],
    counts: dict[str, int],
) -> str:
    controller = config.get("controller", {}) if isinstance(config.get("controller", {}), dict) else {}
    guardrails = config.get("guardrails", [])
    if not isinstance(guardrails, list):
        guardrails = []
    registry = public_registry(args.registry, args.redact_sensitive)
    result = result_from_findings(findings)
    lines = [
        "# Image Registry Promotion Controller",
        "",
        "This report is public-safe. It does not log in to registries, push images, read image layers, read kubeconfigs, or print registry credentials.",
        "",
        f"- Profile: `{args.profile}`",
        f"- Enabled: `{str(bool_value(profile.get('enabled'), False)).lower()}`",
        f"- Execution mode: `{profile.get('executionMode', 'plan')}`",
        f"- Image mode: `{profile.get('imageMode', 'registry')}`",
        f"- Registry: `{registry or '-'}`",
        f"- Credential source: `{args.credential_source}`",
        f"- Image pull secret: `{args.image_pull_secret or controller.get('pullSecretName', 'registry-credentials')}`",
        f"- Values file: `{args.values}`",
        f"- Policy file: `{args.policy}`",
        f"- Images discovered: `{counts['images']}`",
        f"- Missing digest pins: `{counts['missing_digest']}`",
        f"- Mutable tags: `{counts['mutable']}`",
        f"- Placeholder application images: `{counts['placeholders']}`",
        f"- Runtime images outside approved policy: `{counts['unapproved_runtime']}`",
        f"- Result: `{result}`",
        "",
        "## Controller Outputs",
        "",
        f"- Public-safe report: `{args.output}`",
        f"- Public-safe Helm override template: `{args.overrides}`",
        "",
        "## Required Evidence",
        "",
        f"- Digest pins: `{str(bool_value(profile.get('requireDigestPins'), False)).lower()}`",
        f"- Vulnerability scan: `{str(bool_value(profile.get('requireVulnerabilityScan'), False)).lower()}`",
        f"- SBOM: `{str(bool_value(profile.get('requireSbom'), False)).lower()}`",
        f"- Signature or attestation: `{str(bool_value(profile.get('requireSignatureOrAttestation'), False)).lower()}`",
        f"- Promotion record: `{str(bool_value(profile.get('requirePromotionRecord'), False)).lower()}`",
        "",
        "## Promotion Flow",
        "",
    ]
    if profile.get("imageMode") == "preload":
        lines.extend(
            [
                "1. Build or retag images on the operator.",
                "2. Save image archives into the private image output directory.",
                "3. Stream archives to every RKE2 node and import them into containerd.",
                "4. Keep registry fields disabled until a private registry is ready.",
            ]
        )
    else:
        lines.extend(
            [
                "1. Build or retag images on the operator or CI runner.",
                "2. Push promoted tags to the private registry through an approved credential source.",
                "3. Capture scan, SBOM, signature or attestation, and promotion record evidence.",
                "4. Deploy private overrides with `global.imageRegistry`, `imagePullSecrets`, and digest-pinned image objects.",
            ]
        )
    lines.extend(["", "## Findings", ""])
    for finding in findings:
        lines.append(f"- {finding}")
    lines.extend(["", "## Guardrails", ""])
    for guardrail in guardrails:
        lines.append(f"- {guardrail}")
    lines.extend(["", "## Sample Candidates", ""])
    lines.append("| Source | Current image |")
    lines.append("|---|---|")
    for image in images[:30]:
        lines.append(f"| `{image.source}:{image.path}` | `{image.reference}` |")
    if len(images) > 30:
        lines.append(f"| `+{len(images) - 30} more` | `-` |")
    lines.extend(
        [
            "",
            "## Next Commands",
            "",
            "```bash",
            "make image-promotion-plan IMAGE_PROMOTION_REGISTRY=private-registry.example.invalid/platform",
            "make import-auto PROJECT_PATH=/path/to/compose-project MIGRATION_IMAGE_MODE=registry MIGRATION_REGISTRY=private-registry.example.invalid/platform",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe registry promotion controller plan.")
    parser.add_argument("--config", default="config/registry-promotion.yaml")
    parser.add_argument("--values", default="helm/urban-platform-infra/values.yaml")
    parser.add_argument("--policy", default="config/image-policy.yaml")
    parser.add_argument("--profile", default="")
    parser.add_argument("--registry", default="")
    parser.add_argument("--credential-source", default="")
    parser.add_argument("--image-pull-secret", default="")
    parser.add_argument("--output", default="reports/registry-promotion-controller.md")
    parser.add_argument("--overrides", default="reports/registry-promotion-values.yaml")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--redact-sensitive", action="store_true")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    values_path = Path(args.values)
    policy_path = Path(args.policy)
    output_path = Path(args.output)
    overrides_path = Path(args.overrides)
    for name, path in {
        "config": config_path,
        "values": values_path,
        "policy": policy_path,
        "output": output_path,
        "overrides": overrides_path,
    }.items():
        if not path.is_absolute():
            resolved = (ROOT / path).resolve()
            if name == "config":
                config_path = resolved
            elif name == "values":
                values_path = resolved
            elif name == "policy":
                policy_path = resolved
            elif name == "output":
                output_path = resolved
            else:
                overrides_path = resolved

    config = load_yaml_file(config_path)
    profile_name = args.profile or str(config.get("defaultProfile", "disabled"))
    args.profile = profile_name
    profile = select_profile(config, profile_name)
    controller = config.get("controller", {}) if isinstance(config.get("controller", {}), dict) else {}
    args.credential_source = args.credential_source or str(profile.get("credentialSource", "none"))
    args.image_pull_secret = args.image_pull_secret or str(controller.get("pullSecretName", "registry-credentials"))

    policy, blocked, approved, default_tag = policy_sets(policy_path)
    images = unique_images(values_path)
    mutable = [image for image in images if promotion_plan.is_mutable_tag(image.tag, blocked)]
    missing_digest = [image for image in images if not image.digest]
    placeholders = [image for image in images if image.repository.startswith("example-app-") and image.tag == default_tag]
    unapproved_runtime = [
        image
        for image in images
        if image.tag and not image.digest and not image.repository.startswith("example-app-") and (image.repository, image.tag) not in approved
    ]
    invalid_digest = [image for image in images if image.digest and not promotion_plan.DIGEST_RE.fullmatch(image.digest)]
    counts = {
        "images": len(images),
        "missing_digest": len(missing_digest),
        "mutable": len(mutable),
        "placeholders": len(placeholders),
        "unapproved_runtime": len(unapproved_runtime),
    }
    findings = build_findings(
        profile_name=profile_name,
        profile=profile,
        registry=args.registry,
        image_pull_secret=args.image_pull_secret,
        missing_digest_count=len(missing_digest),
        mutable_count=len(mutable),
        invalid_digest_count=len(invalid_digest),
        placeholder_count=len(placeholders),
    )

    write_overrides(
        output=overrides_path,
        profile_name=profile_name,
        profile=profile,
        registry=args.registry,
        image_pull_secret=args.image_pull_secret,
        credential_source=args.credential_source,
        redact_sensitive=args.redact_sensitive,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generate_report(args=args, config=config, profile=profile, images=images, findings=findings, counts=counts), encoding="utf-8")
    print(f"Registry promotion controller report written: {output_path}")
    print(f"Registry promotion override template written: {overrides_path}")
    if args.strict and result_from_findings(findings) == "FAIL" and bool_value(profile.get("enabled"), False):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
