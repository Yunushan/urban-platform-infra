#!/usr/bin/env python3
"""Fail closed before a production Helm deployment uses private values.

This check validates the effective production values without printing private
values, endpoints, secret references, or registry credentials. The signed
operational evidence gate still verifies the private overlay checksum and live
cluster after deployment; this preflight prevents an unsafe deployment from
starting before that gate can run.
"""
from __future__ import annotations

import argparse
import ipaddress
import re
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - operator environments install PyYAML.
    raise SystemExit("PyYAML is required to validate the production private overlay.") from exc


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts" / "images") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "images"))

from scripts import validate_production_profile as profile_validator  # noqa: E402
from scripts.images import promotion_plan  # noqa: E402


DIGEST_RE = re.compile(r"^sha256:[A-Fa-f0-9]{64}$")
RELEASE_TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")
SOURCE_REVISION_RE = re.compile(r"^(?:[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})$")
MUTABLE_TAGS = frozenset({"latest", "latest-pg16", "latest-pg17", "latest-pg18"})
PLACEHOLDER_SUFFIXES = (".example", ".invalid", ".localhost", ".test")
PLACEHOLDER_HOSTS = frozenset(
    {
        "example.com",
        "example.net",
        "example.org",
        "localhost",
        "registry.example.com",
        "registry.example.net",
        "registry.example.org",
    }
)
DOCUMENTATION_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")
)


def mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def get(value: Any, *keys: str, default: Any = None) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


def load_mapping(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError("values input must be a YAML mapping")
    return loaded


def resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def outside_repository(path: Path) -> bool:
    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        return True
    return False


def canonical_uuid_v4(value: Any) -> str | None:
    candidate = str(value).strip().lower()
    try:
        parsed = uuid.UUID(candidate)
    except (AttributeError, TypeError, ValueError):
        return None
    if parsed.version != 4 or str(parsed) != candidate:
        return None
    return candidate


def is_ip_literal(value: Any) -> bool:
    try:
        ipaddress.ip_address(str(value).strip())
    except ValueError:
        return False
    return True


def registry_host(value: str) -> str:
    try:
        return (urlsplit(f"//{value}").hostname or "").strip().lower().rstrip(".")
    except ValueError:
        return ""


def valid_private_registry(value: Any) -> bool:
    registry = str(value).strip().rstrip("/")
    if not registry or "://" in registry or any(char.isspace() for char in registry):
        return False
    host = registry_host(registry)
    if not host or host in PLACEHOLDER_HOSTS or is_ip_literal(host):
        return False
    if host.startswith("example.") or any(host.endswith(suffix) for suffix in PLACEHOLDER_SUFFIXES):
        return False
    return True


def valid_cluster_ip(value: Any) -> bool:
    try:
        address = ipaddress.ip_address(str(value).strip())
    except ValueError:
        return False
    return not (
        address.is_loopback
        or address.is_unspecified
        or address.is_multicast
        or address.is_link_local
        or address.is_reserved
        or any(address in network for network in DOCUMENTATION_NETWORKS)
    )


def valid_endpoint_host(value: Any) -> bool:
    candidate = str(value).strip()
    if not candidate or "://" in candidate or "/" in candidate or any(char.isspace() for char in candidate):
        return False
    if is_ip_literal(candidate):
        return valid_cluster_ip(candidate)
    host = registry_host(candidate)
    if not host or host in PLACEHOLDER_HOSTS or host.startswith("example."):
        return False
    return not any(host.endswith(suffix) for suffix in PLACEHOLDER_SUFFIXES)


def placeholder_secret_reference(value: Any) -> bool:
    reference = str(value).strip().lower()
    if not reference:
        return True
    if reference.startswith(("example/", "changeme", "placeholder")):
        return True
    if "<" in reference or ">" in reference:
        return True
    return any(reference.endswith(suffix) or suffix in reference for suffix in PLACEHOLDER_SUFFIXES)


def validate_private_overlay(
    *,
    base_values: Path,
    production_values: Path,
    private_values: Path,
    environment_profiles: Path,
    ingress_host: str = "",
    cluster_domain: str = "",
    cluster_vip: str = "",
) -> list[str]:
    errors: list[str] = []
    try:
        base_path = resolved(base_values)
        production_path = resolved(production_values)
        private_path = resolved(private_values)
        profiles_path = resolved(environment_profiles)
    except (OSError, ValueError):
        return ["production values input paths are invalid"]

    if not private_path.is_file() or private_path.stat().st_size == 0:
        errors.append("private production values overlay is missing or empty")
    if private_path == production_path:
        errors.append("private production values overlay must not be the public production values file")
    if not outside_repository(private_path):
        errors.append("private production values overlay must be outside the repository checkout")
    if errors:
        return errors

    try:
        base = load_mapping(base_path)
        production = load_mapping(production_path)
        private = load_mapping(private_path)
        profiles = load_mapping(profiles_path)
    except (OSError, UnicodeError, ValueError, TypeError, yaml.YAMLError):
        return ["production values or environment profile input is invalid"]

    merged = promotion_plan.merge_values(
        promotion_plan.merge_values(base, production),
        private,
    )
    if not isinstance(merged, dict):
        return ["effective production values are not a mapping"]

    try:
        errors.extend(profile_validator.validate_values(merged))
        errors.extend(profile_validator.validate_environment_profile(profiles))
    except (TypeError, ValueError, KeyError):
        errors.append("effective production values failed structural validation")

    private_global = mapping(private.get("global"))
    global_values = mapping(merged.get("global"))
    image_registry = str(global_values.get("imageRegistry", "")).strip()
    if not private_global.get("imageRegistry") or not valid_private_registry(image_registry):
        errors.append("private production values must configure a non-placeholder registry host")
    pull_secrets = global_values.get("imagePullSecrets")
    if not isinstance(pull_secrets, list) or not pull_secrets or not all(str(item).strip() for item in pull_secrets):
        errors.append("private production values must configure a registry image pull Secret")

    configured_ingress_host = str(ingress_host).strip() or str(get(merged, "ingress", "host", default="")).strip()
    configured_cluster_domain = str(cluster_domain).strip() or str(get(global_values, "cluster", "domain", default="")).strip()
    configured_cluster_vip = str(cluster_vip).strip() or str(get(global_values, "cluster", "vip", default="")).strip()
    if not valid_endpoint_host(configured_ingress_host):
        errors.append("production ingress host must be a real DNS name or a non-reserved IP address")
    if not valid_endpoint_host(configured_cluster_domain):
        errors.append("production cluster domain must be a real DNS name or a non-reserved IP address")
    if not valid_cluster_ip(configured_cluster_vip):
        errors.append("production cluster VIP must be a non-reserved IP address")

    identity = mapping(global_values.get("releaseIdentity"))
    if not isinstance(private_global.get("releaseIdentity"), dict):
        errors.append("private production values must carry the release identity")
    tag = str(identity.get("tag", "")).strip()
    source_revision = str(identity.get("sourceRevision", "")).strip()
    if identity.get("enabled") is not True or not RELEASE_TAG_RE.fullmatch(tag) or tag.lower().lstrip("v") == "0.0.0":
        errors.append("private production release identity must contain a real release tag")
    if not SOURCE_REVISION_RE.fullmatch(source_revision) or len(set(source_revision.lower())) < 4:
        errors.append("private production release identity must contain an immutable source revision")
    if canonical_uuid_v4(identity.get("deploymentId")) is None:
        errors.append("private production release identity must contain a UUIDv4 deployment ID")

    image_objects = promotion_plan.images_from_loaded_yaml("production-values", merged)
    unique_images = {
        (image.path, image.repository, image.tag, image.digest): image
        for image in image_objects
    }
    if not unique_images:
        errors.append("effective production values contain no runtime image inventory")
    for image in unique_images.values():
        if not image.repository:
            errors.append("every effective production image must have a repository")
        if not image.digest or not DIGEST_RE.fullmatch(image.digest):
            errors.append("every effective production image must be pinned by a sha256 digest")
        if image.tag and image.tag.strip().lower() in MUTABLE_TAGS:
            errors.append("effective production images must not retain mutable tags")

    external_secrets = mapping(get(merged, "secretManagement", "externalSecrets", default={}))
    for secret in external_secrets.values():
        if not isinstance(secret, dict) or secret.get("enabled") is not True:
            continue
        data = secret.get("data")
        if not isinstance(data, list) or not data:
            errors.append("every enabled production ExternalSecret must define remote data mappings")
            continue
        for item in data:
            if not isinstance(item, dict) or placeholder_secret_reference(get(item, "remoteRef", "key", default="")):
                errors.append("production ExternalSecret remote references must be replaced with real secret paths")

    # De-duplicate repeated image/profile findings while preserving review order.
    return list(dict.fromkeys(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the private production overlay before deployment.")
    parser.add_argument("--base-values", default=str(ROOT / "helm/urban-platform-infra/values.yaml"))
    parser.add_argument("--production-values", default=str(ROOT / "helm/urban-platform-infra/values-production.yaml"))
    parser.add_argument("--private-values", required=True)
    parser.add_argument("--environment-profiles", default=str(ROOT / "config/environment-profiles.yaml"))
    parser.add_argument("--ingress-host", default="")
    parser.add_argument("--cluster-domain", default="")
    parser.add_argument("--cluster-vip", default="")
    args = parser.parse_args(argv)

    try:
        errors = validate_private_overlay(
            base_values=Path(args.base_values),
            production_values=Path(args.production_values),
            private_values=Path(args.private_values),
            environment_profiles=Path(args.environment_profiles),
            ingress_host=args.ingress_host,
            cluster_domain=args.cluster_domain,
            cluster_vip=args.cluster_vip,
        )
    except (OSError, TypeError, ValueError, KeyError):
        errors = ["production private overlay validation could not be completed"]

    if errors:
        for error in errors:
            print(f"PRODUCTION-PRIVATE: {error}")
        print(f"Production private overlay validation failed with {len(errors)} error(s).")
        return 1
    print("Production private overlay contract passed: release identity, external secret references, and digest-pinned image inventory are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
