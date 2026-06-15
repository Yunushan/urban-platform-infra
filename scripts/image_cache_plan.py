#!/usr/bin/env python3
"""Generate a public-safe image cache, preload, and cleanup plan."""
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


def bool_from_text(value: str | bool | None, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def count_nodes(raw_nodes: str) -> int:
    return len([node for node in raw_nodes.split(",") if node.strip()])


def public_path(path: str, redact_sensitive: bool) -> str:
    if not redact_sensitive:
        return path
    normalized = path.replace("\\", "/")
    if normalized.startswith("/var/lib/urban-platform/private"):
        return "/var/lib/urban-platform/private/<path>"
    return normalized


def public_registry(registry: str, redact_sensitive: bool) -> str:
    if not registry:
        return ""
    return "<private-registry>" if redact_sensitive else registry


def profile_config(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = config.get("profiles", {})
    if not isinstance(profiles, dict):
        raise SystemExit("Image cache config must contain a profiles mapping.")
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown image cache profile `{profile_name}`. Available profiles: {choices}")
    profile = profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"Image cache profile `{profile_name}` must be a mapping.")
    return profile


def report_findings(
    *,
    image_mode: str,
    registry: str,
    node_count: int,
    cleanup_operator_images: bool,
    prune_operator_cache: bool,
    rke2_import_images: bool,
    cleanup_node_import_images: bool,
    cleanup_node_cri_images: bool,
    cleanup_node_content_prune: bool,
    cleanup_node_image_scope: str,
    max_operator_archive_gi: Any,
) -> list[str]:
    findings: list[str] = []
    if image_mode == "registry" and not registry:
        findings.append("ERROR: Registry mode requires MIGRATION_REGISTRY to point at a private registry.")
    if image_mode == "preload" and node_count == 0:
        findings.append("WARN: Preload mode has no MIGRATION_RKE2_NODES; archives will remain on the operator for manual transfer.")
    if image_mode == "preload" and not rke2_import_images:
        findings.append("WARN: RKE2 containerd import is disabled; pods may need an RKE2 restart or manual import before using preloaded images.")
    if image_mode == "preload" and not cleanup_operator_images:
        findings.append("WARN: Operator image/archive cleanup is disabled; monitor operator disk usage.")
    if image_mode == "preload" and node_count > 0 and not cleanup_node_import_images:
        findings.append("WARN: Node imported-image cleanup is disabled; repeated preload reruns can fill RKE2 node disks.")
    if image_mode == "preload" and node_count > 0 and cleanup_node_import_images and not cleanup_node_cri_images:
        findings.append("WARN: Node CRI image cleanup is disabled; stale imported refs may not release containerd snapshots promptly.")
    if image_mode == "preload" and node_count > 0 and not cleanup_node_content_prune:
        findings.append("WARN: Node containerd content pruning is disabled; unreferenced image content may remain after stale refs are removed.")
    if cleanup_node_image_scope not in {"desired", "scheduled"}:
        findings.append("ERROR: Node image cleanup scope must be `desired` or `scheduled`.")
    if image_mode == "preload" and node_count > 0 and cleanup_node_import_images and cleanup_node_image_scope == "scheduled":
        findings.append(
            "WARN: Scheduled node image cleanup is lab-only; pods rescheduled to another node may need the image stage rerun unless a registry is available."
        )
    if not prune_operator_cache:
        findings.append("WARN: Operator build cache pruning is disabled; this can fill small lab disks quickly.")
    if image_mode == "skip":
        findings.append("WARN: Image migration is skipped; workloads need an external image source before Kubernetes rollout.")
    try:
        if image_mode == "preload" and float(max_operator_archive_gi) > 0 and node_count == 0:
            findings.append(f"INFO: Keep at least {max_operator_archive_gi}Gi free for local preload archives when nodes are not configured.")
    except (TypeError, ValueError):
        pass
    return findings or ["OK: Image cache and cleanup settings are internally consistent."]


def generate_report(args: argparse.Namespace, config: dict[str, Any]) -> str:
    default_profile = str(config.get("defaultProfile", "lab-preload"))
    selected_profile = args.profile or default_profile
    profile = profile_config(config, selected_profile)
    image_mode = args.image_mode or str(profile.get("imageMode", "preload"))
    cleanup_operator_images = bool_from_text(args.cleanup_operator_images, bool(profile.get("cleanupOperatorImages", True)))
    prune_operator_cache = bool_from_text(args.prune_operator_cache, bool(profile.get("pruneOperatorCache", True)))
    rke2_import_images = bool_from_text(args.rke2_import_images, bool(profile.get("rke2ImportImages", True)))
    cleanup_node_import_images = bool_from_text(args.cleanup_node_import_images, bool(profile.get("cleanupNodeImportImages", True)))
    cleanup_node_cri_images = bool_from_text(args.cleanup_node_cri_images, bool(profile.get("cleanupNodeCriImages", True)))
    cleanup_node_content_prune = bool_from_text(args.cleanup_node_content_prune, bool(profile.get("cleanupNodeContentPrune", True)))
    cleanup_node_image_scope = args.cleanup_node_image_scope or str(profile.get("cleanupNodeImageScope", "desired"))
    node_count = count_nodes(args.rke2_nodes)
    registry = public_registry(args.registry, args.redact_sensitive)
    image_output_dir = public_path(args.image_output_dir, args.redact_sensitive)
    private_dir = public_path(args.private_dir, args.redact_sensitive)
    max_operator_archive_gi = profile.get("maxOperatorArchiveGi", 0)
    max_operator_cache_gi = profile.get("maxOperatorCacheGi", 0)
    findings = report_findings(
        image_mode=image_mode,
        registry=args.registry,
        node_count=node_count,
        cleanup_operator_images=cleanup_operator_images,
        prune_operator_cache=prune_operator_cache,
        rke2_import_images=rke2_import_images,
        cleanup_node_import_images=cleanup_node_import_images,
        cleanup_node_cri_images=cleanup_node_cri_images,
        cleanup_node_content_prune=cleanup_node_content_prune,
        cleanup_node_image_scope=cleanup_node_image_scope,
        max_operator_archive_gi=max_operator_archive_gi,
    )
    result = "FAIL" if any(item.startswith("ERROR:") for item in findings) else ("WARN" if any(item.startswith("WARN:") for item in findings) else "PASS")
    checks = config.get("checks", [])
    guardrails = profile.get("guardrails", [])
    if not isinstance(checks, list):
        checks = []
    if not isinstance(guardrails, list):
        guardrails = []

    lines = [
        "# Image Cache, Preload, And Cleanup Plan",
        "",
        "This report is public-safe. It redacts registry and private workspace details by default and does not inspect image layers, credentials, node logs, or project source data.",
        "",
        f"- Profile: `{selected_profile}`",
        f"- Image mode: `{image_mode}`",
        f"- Registry: `{registry or '-'}`",
        f"- RKE2 node count: `{node_count}`",
        f"- Private workspace: `{private_dir}`",
        f"- Operator image output: `{image_output_dir}`",
        f"- RKE2 image directory: `{args.rke2_image_dir}`",
        f"- Container tool: `{args.container_tool}`",
        f"- Image tag: `{args.image_tag}`",
        f"- RKE2 containerd import: `{str(rke2_import_images).lower()}`",
        f"- Cleanup operator images: `{str(cleanup_operator_images).lower()}`",
        f"- Prune operator cache: `{str(prune_operator_cache).lower()}`",
        f"- Cleanup node import images: `{str(cleanup_node_import_images).lower()}`",
        f"- Cleanup node CRI images: `{str(cleanup_node_cri_images).lower()}`",
        f"- Cleanup node containerd content: `{str(cleanup_node_content_prune).lower()}`",
        f"- Cleanup node image scope: `{cleanup_node_image_scope}`",
        f"- Node archive retention: `{args.node_archive_retention_hours}h`",
        f"- Operator archive budget: `{max_operator_archive_gi}Gi`",
        f"- Operator cache budget: `{max_operator_cache_gi}Gi`",
        f"- Result: `{result}`",
        "",
        "## Recommended Flow",
        "",
    ]
    if image_mode == "registry":
        lines.extend(
            [
                "1. Build or retag each import candidate on the operator.",
                "2. Push the promoted tag to the private registry.",
                "3. Deploy workloads with normal Kubernetes image pulls and imagePullSecrets when required.",
                "4. Remove temporary operator tags and prune dangling build cache after successful promotion.",
            ]
        )
    elif image_mode == "preload":
        lines.extend(
            [
                "1. Build or retag one import candidate on the operator.",
                "2. Save it as a short-lived tar archive in the private image output directory.",
                "3. Stream the archive to every configured RKE2 node.",
                "4. Import the archive into the running RKE2 containerd socket when available.",
                "5. Remove the remote archive after import and remove local operator tags/archives after success.",
            ]
        )
    else:
        lines.extend(
            [
                "1. Skip image movement inside the migration run.",
                "2. Keep the existing Compose deployment or provide images through a separate approved path.",
                "3. Re-run image migration later with `registry` or `preload` before rolling Kubernetes workloads.",
            ]
        )

    lines.extend(
        [
            "",
            "## Cleanup Contract",
            "",
            "- operator cache cleanup is part of the preload contract and should stay enabled for small lab disks.",
            f"- `MIGRATION_CLEANUP_OPERATOR_IMAGES={str(cleanup_operator_images).lower()}` controls generated import tags and local preload archive cleanup.",
            f"- `MIGRATION_PRUNE_OPERATOR_CACHE={str(prune_operator_cache).lower()}` controls dangling Docker/Podman image and builder cache pruning.",
            f"- `MIGRATION_RKE2_IMPORT_IMAGES={str(rke2_import_images).lower()}` controls running RKE2 containerd import for preload archives.",
            f"- `MIGRATION_CLEANUP_NODE_IMPORT_IMAGES={str(cleanup_node_import_images).lower()}` controls stale `urban-platform-import/...` ref cleanup on RKE2 nodes.",
            f"- `MIGRATION_CLEANUP_NODE_CRI_IMAGES={str(cleanup_node_cri_images).lower()}` removes stale imported refs through the RKE2 CRI image service before falling back to raw containerd refs.",
            f"- `MIGRATION_CLEANUP_NODE_CONTENT_PRUNE={str(cleanup_node_content_prune).lower()}` controls node-side containerd content pruning after stale refs are removed.",
            f"- `MIGRATION_CLEANUP_NODE_IMAGE_SCOPE={cleanup_node_image_scope}` controls whether node cleanup preserves all desired imported images on every node or only imported images used by pods scheduled on that node.",
            f"- `MIGRATION_NODE_ARCHIVE_RETENTION_HOURS={args.node_archive_retention_hours}` controls how long staged node tar archives are retained before cleanup.",
            "- Keep cleanup enabled for constrained labs. Disable it only when you are debugging image builds or preserving offline evidence.",
            "",
            "## RKE2 Preload Contract",
            "",
            "- `MIGRATION_RKE2_NODES` should include every RKE2 node that can schedule imported workloads.",
            "- RKE2 preload mode imports archives into `/run/k3s/containerd/containerd.sock` when the socket is available.",
            "- If containerd is not running, archives are left in the RKE2 image directory for startup import.",
            "- Node names or addresses are intentionally not listed in this public report.",
            "",
            "## Required Checks",
            "",
        ]
    )
    for check in checks:
        lines.append(f"- {check}")

    lines.extend(["", "## Guardrails", ""])
    for guardrail in guardrails:
        lines.append(f"- {guardrail}")

    lines.extend(["", "## Findings", ""])
    for finding in findings:
        lines.append(f"- {finding}")

    lines.extend(
        [
            "",
            "## Example Commands",
            "",
            "```bash",
            "make image-cache-plan IMAGE_CACHE_PROFILE=lab-preload MIGRATION_IMAGE_MODE=preload MIGRATION_RKE2_NODES=node-01,node-02,node-03",
            "make import-auto PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true MIGRATION_IMAGE_MODE=preload MIGRATION_RKE2_NODES=node-01,node-02,node-03",
            "make image-cache-plan IMAGE_CACHE_PROFILE=production-registry MIGRATION_IMAGE_MODE=registry MIGRATION_REGISTRY=private-registry.example.invalid/platform",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe image cache, preload, and cleanup plan.")
    parser.add_argument("--config", default=str(ROOT / "config/image-cache.yaml"))
    parser.add_argument("--profile", default="")
    parser.add_argument("--output", default=str(ROOT / "reports/image-cache-plan.md"))
    parser.add_argument("--image-mode", choices=["registry", "preload", "skip"], default="")
    parser.add_argument("--private-dir", default="/var/lib/urban-platform/private")
    parser.add_argument("--image-output-dir", default="/var/lib/urban-platform/private/images")
    parser.add_argument("--rke2-image-dir", default="/var/lib/rancher/rke2/agent/images")
    parser.add_argument("--rke2-nodes", default="")
    parser.add_argument("--registry", default="")
    parser.add_argument("--container-tool", default="auto")
    parser.add_argument("--image-tag", default="imported-0.1.0")
    parser.add_argument("--cleanup-operator-images", default="")
    parser.add_argument("--prune-operator-cache", default="")
    parser.add_argument("--rke2-import-images", default="")
    parser.add_argument("--cleanup-node-import-images", default="")
    parser.add_argument("--cleanup-node-cri-images", default="")
    parser.add_argument("--cleanup-node-content-prune", default="")
    parser.add_argument("--cleanup-node-image-scope", default="")
    parser.add_argument("--node-archive-retention-hours", default="1")
    parser.add_argument("--redact-sensitive", action="store_true")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = (ROOT / config_path).resolve()
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (ROOT / output_path).resolve()
    config = load_yaml_file(config_path)
    report = generate_report(args, config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Image cache plan written: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
