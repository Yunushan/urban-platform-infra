#!/usr/bin/env python3
"""Exercise the production private-overlay preflight with temporary values."""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import validate_production_private_overlay as validator
from scripts.images import promotion_plan


DIGEST = "sha256:" + ("a" * 64)


def write_yaml(path: Path, value: dict) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def make_private_overlay(base: dict, production: dict) -> dict:
    merged = promotion_plan.merge_values(base, production)
    counter = 0

    def transform(value):
        nonlocal counter
        if isinstance(value, dict):
            result = {key: transform(child) for key, child in value.items()}
            if "repository" in result and ("tag" in result or "digest" in result) and str(result.get("repository", "")).strip():
                result["digest"] = DIGEST
            if isinstance(result.get("remoteRef"), dict):
                counter += 1
                result["remoteRef"] = dict(result["remoteRef"])
                result["remoteRef"]["key"] = f"production/test-secret-{counter}"
            image = result.get("image")
            if isinstance(image, str) and image.strip():
                repository, _, _ = promotion_plan.parse_image_ref(image)
                result["image"] = f"{repository}@{DIGEST}"
            return result
        if isinstance(value, list):
            return [transform(child) for child in value]
        return copy.deepcopy(value)

    private = transform(merged)
    private["global"]["imageRegistry"] = "registry.internal.corp/platform"
    private["global"]["imagePullSecrets"] = ["registry-credentials"]
    private["global"]["cluster"]["vip"] = "198.18.0.194"
    private["global"]["cluster"]["domain"] = "platform.internal"
    private["ingress"]["host"] = "platform.internal"
    private["global"]["releaseIdentity"] = {
        "enabled": True,
        "tag": "v1.2.3",
        "sourceRevision": "0123456789abcdef0123456789abcdef01234567",
        "deploymentId": "123e4567-e89b-42d3-a456-426614174000",
    }
    return private


def main() -> int:
    base = yaml.safe_load((ROOT / "helm/urban-platform-infra/values.yaml").read_text(encoding="utf-8"))
    production = yaml.safe_load((ROOT / "helm/urban-platform-infra/values-production.yaml").read_text(encoding="utf-8"))
    assert isinstance(base, dict) and isinstance(production, dict)

    image_inventory = promotion_plan.images_from_loaded_yaml(
        "synthetic",
        {"messaging": {"connect": {"build": {"output": {"image": ""}}}}},
    )
    assert not image_inventory, "empty optional image slots must not enter the production inventory"

    with tempfile.TemporaryDirectory(prefix="urban-production-private-") as directory:
        root = Path(directory)
        base_path = root / "base.yaml"
        production_path = root / "production.yaml"
        private_path = root / "private.yaml"
        profiles_path = ROOT / "config/environment-profiles.yaml"
        write_yaml(base_path, base)
        write_yaml(production_path, production)
        private = make_private_overlay(base, production)
        write_yaml(private_path, private)

        errors = validator.validate_private_overlay(
            base_values=base_path,
            production_values=production_path,
            private_values=private_path,
            environment_profiles=profiles_path,
        )
        assert not errors, errors

        private["global"]["imageRegistry"] = "registry.example.invalid/platform"
        write_yaml(private_path, private)
        errors = validator.validate_private_overlay(
            base_values=base_path,
            production_values=production_path,
            private_values=private_path,
            environment_profiles=profiles_path,
        )
        assert any("non-placeholder registry" in error for error in errors), errors

        private = make_private_overlay(base, production)
        private["global"]["cluster"]["vip"] = "192.0.2.10"
        private["global"]["cluster"]["domain"] = "urban-platform.example"
        private["ingress"]["host"] = "urban-platform.example"
        write_yaml(private_path, private)
        errors = validator.validate_private_overlay(
            base_values=base_path,
            production_values=production_path,
            private_values=private_path,
            environment_profiles=profiles_path,
        )
        assert any("cluster VIP" in error for error in errors), errors
        assert any("ingress host" in error for error in errors), errors

        private = make_private_overlay(base, production)
        for value in private["workloads"].values():
            if isinstance(value, dict) and isinstance(value.get("image"), dict):
                value["image"].pop("digest", None)
                break
        write_yaml(private_path, private)
        errors = validator.validate_private_overlay(
            base_values=base_path,
            production_values=production_path,
            private_values=private_path,
            environment_profiles=profiles_path,
        )
        assert any("sha256 digest" in error for error in errors), errors

    print("Production private overlay preflight tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
