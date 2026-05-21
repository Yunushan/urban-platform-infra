#!/usr/bin/env python3
"""Generate a public-safe production image promotion plan."""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - fallback keeps the report usable on tiny operator hosts.
    yaml = None

ROOT = Path(__file__).resolve().parents[2]
DIGEST_RE = re.compile(r"^sha256:[A-Fa-f0-9]{64}$")


@dataclass(frozen=True)
class ImageObject:
    source: str
    path: str
    repository: str
    tag: str | None
    digest: str | None

    @property
    def reference(self) -> str:
        if self.digest:
            return f"{self.repository}@{self.digest}"
        if self.tag:
            return f"{self.repository}:{self.tag}"
        return self.repository


def load_yaml(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if yaml is None:
        return None
    return yaml.safe_load(text) or {}


def strip_quotes(value: str) -> str:
    return value.strip().strip("'\"")


def parse_scalar(line: str, key: str) -> str | None:
    match = re.match(rf"^\s*{re.escape(key)}:\s*(.*?)\s*$", line)
    if not match:
        return None
    value = match.group(1).split("#", 1)[0].strip()
    return strip_quotes(value) if value else None


def fallback_policy(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    blocked: list[str] = []
    approved: list[dict[str, str]] = []
    default_tag = "0.1.0"
    current: dict[str, str] | None = None
    section = ""
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("  disallowMutableTags:"):
            section = "blocked"
            continue
        if line.startswith("  approvedRuntimeImages:"):
            section = "approved"
            continue
        if re.match(r"^  [A-Za-z]", line) and not line.lstrip().startswith("-"):
            section = ""
        value = parse_scalar(line, "defaultApplicationTag")
        if value:
            default_tag = value
        if section == "blocked" and line.lstrip().startswith("- "):
            blocked.append(strip_quotes(line.split("- ", 1)[1]))
        if section == "approved":
            repo = parse_scalar(line.replace("- repository:", "repository:"), "repository")
            if repo:
                if current:
                    approved.append(current)
                current = {"repository": repo}
                continue
            if current is not None:
                tag = parse_scalar(line, "tag")
                owner = parse_scalar(line, "owner")
                if tag:
                    current["tag"] = tag
                if owner:
                    current["owner"] = owner
    if current:
        approved.append(current)
    return {
        "policy": {
            "defaultApplicationTag": default_tag,
            "disallowMutableTags": blocked,
            "approvedRuntimeImages": approved,
            "imagePromotion": {},
        }
    }


def read_policy(path: Path) -> dict[str, Any]:
    loaded = load_yaml(path)
    if isinstance(loaded, dict):
        return loaded
    return fallback_policy(path)


def walk(value: Any, path: str = ""):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield from walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")


def images_from_loaded_yaml(source: str, loaded: Any) -> list[ImageObject]:
    images: list[ImageObject] = []
    for path, value in walk(loaded):
        if not isinstance(value, dict):
            continue
        if "repository" in value and ("tag" in value or "digest" in value):
            images.append(
                ImageObject(
                    source=source,
                    path=path or ".",
                    repository=str(value.get("repository", "")).strip(),
                    tag=None if value.get("tag") is None else str(value.get("tag")).strip(),
                    digest=None if value.get("digest") is None else str(value.get("digest")).strip(),
                )
            )
        image = value.get("image")
        if isinstance(image, str):
            repository, tag, digest = parse_image_ref(image)
            images.append(ImageObject(source=source, path=f"{path}.image", repository=repository, tag=tag, digest=digest))
    return images


def images_from_text(source: str, path: Path) -> list[ImageObject]:
    lines = path.read_text(encoding="utf-8").splitlines()
    images: list[ImageObject] = []
    stack: list[tuple[int, str]] = []
    for index, raw_line in enumerate(lines):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        key_match = re.match(r"^\s*([A-Za-z0-9_.-]+):\s*(.*?)\s*$", raw_line)
        if key_match:
            key, value = key_match.groups()
            current_path = ".".join([item[1] for item in stack] + [key])
            if value == "":
                stack.append((indent, key))
            if key == "image" and value:
                repository, tag, digest = parse_image_ref(strip_quotes(value))
                images.append(ImageObject(source=source, path=current_path, repository=repository, tag=tag, digest=digest))
            if key == "repository" and value:
                tag = None
                digest = None
                for lookahead in lines[index + 1 : index + 8]:
                    if not lookahead.strip() or lookahead.lstrip().startswith("#"):
                        continue
                    next_indent = len(lookahead) - len(lookahead.lstrip(" "))
                    if next_indent < indent:
                        break
                    tag = tag or parse_scalar(lookahead, "tag")
                    digest = digest or parse_scalar(lookahead, "digest")
                if tag or digest:
                    images.append(ImageObject(source=source, path=current_path.rsplit(".", 1)[0], repository=strip_quotes(value), tag=tag, digest=digest))
    return images


def parse_image_ref(image: str) -> tuple[str, str | None, str | None]:
    value = image.replace("${REGISTRY_PREFIX:-}", "").strip()
    if "@" in value:
        repository, digest = value.rsplit("@", 1)
        return repository, None, digest
    slash = value.rfind("/")
    colon = value.rfind(":")
    if colon > slash:
        return value[:colon], value[colon + 1 :], None
    return value, None, None


def images_from_file(path: Path) -> list[ImageObject]:
    source = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()
    loaded = load_yaml(path)
    if loaded is not None:
        return images_from_loaded_yaml(source, loaded)
    return images_from_text(source, path)


def is_mutable_tag(tag: str | None, blocked: set[str]) -> bool:
    if not tag:
        return False
    value = tag.strip()
    return value in blocked or value.startswith("latest-") or value.endswith("-latest")


def target_reference(registry: str, image: ImageObject) -> str:
    tag = image.tag or "REPLACE_WITH_VERSION"
    return f"{registry.rstrip('/')}/{image.repository}:{tag}@sha256:REPLACE_WITH_PROMOTED_DIGEST"


def compact_rows(images: list[ImageObject], registry: str, limit: int = 80) -> list[str]:
    rows = [
        "| Source | Current image | Production target | Required evidence |",
        "|---|---|---|---|",
    ]
    for image in images[:limit]:
        rows.append(
            f"| `{image.source}:{image.path}` | `{image.reference}` | `{target_reference(registry, image)}` | SBOM, vulnerability scan, signature, promotion record |"
        )
    if len(images) > limit:
        rows.append(f"| `+{len(images) - limit} more` | `-` | `-` | `-` |")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe image promotion plan for production readiness.")
    parser.add_argument("--values", default="helm/urban-platform-infra/values.yaml")
    parser.add_argument("--policy", default="config/image-policy.yaml")
    parser.add_argument("--registry", default="private-registry.example.invalid/platform")
    parser.add_argument("--profile", choices=["lab", "production"], default="production")
    parser.add_argument("--output", default="reports/image-promotion-plan.md")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    policy = read_policy(ROOT / args.policy).get("policy", {})
    blocked = {str(tag).strip() for tag in policy.get("disallowMutableTags", [])}
    default_app_tag = str(policy.get("defaultApplicationTag", "0.1.0"))
    approved = {
        (str(item.get("repository", "")).strip(), str(item.get("tag", "")).strip())
        for item in policy.get("approvedRuntimeImages", [])
        if isinstance(item, dict)
    }
    values_path = ROOT / args.values
    images = images_from_file(values_path)
    unique_images = sorted({(image.source, image.path, image.reference): image for image in images}.values(), key=lambda item: (item.source, item.path))

    mutable = [image for image in unique_images if is_mutable_tag(image.tag, blocked)]
    missing_digest = [image for image in unique_images if not image.digest]
    placeholders = [image for image in unique_images if image.repository.startswith("example-app-") and image.tag == default_app_tag]
    unapproved_runtime = [
        image
        for image in unique_images
        if image.tag and not image.digest and not image.repository.startswith("example-app-") and (image.repository, image.tag) not in approved
    ]
    invalid_digest = [image for image in unique_images if image.digest and not DIGEST_RE.fullmatch(image.digest)]

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Image Promotion Plan",
        "",
        "This report is public-safe. It names image references from committed defaults and does not read registry credentials, image layers, kubeconfigs, or private inventories.",
        "",
        f"- Profile: `{args.profile}`",
        f"- Registry target: `{args.registry}`",
        f"- Values file: `{args.values}`",
        f"- Policy file: `{args.policy}`",
        f"- Images discovered: `{len(unique_images)}`",
        f"- Missing digest pins: `{len(missing_digest)}`",
        f"- Mutable tags: `{len(mutable)}`",
        f"- Placeholder application images: `{len(placeholders)}`",
        f"- Runtime images outside approved policy: `{len(unapproved_runtime)}`",
        "",
        "## Required Production Evidence",
        "",
        "- Vulnerability scan result for each promoted image.",
        "- SBOM for each promoted image.",
        "- Signature or attestation for each promoted digest.",
        "- Promotion record mapping source image, target private-registry image, digest, owner, and approval.",
        "- Production override that uses `digest: sha256:...` rather than mutable tag identity.",
        "",
        "## Promotion Candidates",
        "",
        *compact_rows(missing_digest, args.registry),
        "",
    ]
    if mutable or invalid_digest or unapproved_runtime:
        lines.extend(["## Policy Findings", ""])
        for image in mutable:
            lines.append(f"- ERROR: Mutable tag in `{image.source}:{image.path}` -> `{image.reference}`.")
        for image in invalid_digest:
            lines.append(f"- ERROR: Invalid digest in `{image.source}:{image.path}` -> `{image.reference}`.")
        for image in unapproved_runtime:
            lines.append(f"- WARN: Runtime image is not approved by policy: `{image.reference}` at `{image.source}:{image.path}`.")
        lines.append("")
    if placeholders:
        lines.extend(
            [
                "## Placeholder Images",
                "",
                "The following defaults are intentionally sanitized placeholders. Replace them with private application images before production.",
                "",
            ]
        )
        for image in placeholders[:40]:
            lines.append(f"- `{image.source}:{image.path}` -> `{image.reference}`")
        if len(placeholders) > 40:
            lines.append(f"- `+{len(placeholders) - 40} more`")
        lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Image promotion plan written to {args.output}")

    if args.strict and args.profile == "production" and (mutable or invalid_digest or placeholders or missing_digest):
        print("Image promotion strict mode failed: production images need immutable digest-pinned private-registry evidence.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
