"""Policy tests for the optional management-tool integrations."""
from __future__ import annotations

from pathlib import Path
import copy
import tempfile
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import management_tools


EXPECTED_MODELS = {
    "rancher": "in-cluster-helm",
    "portainer": "in-cluster-helm",
    "headlamp": "in-cluster-helm",
    "devtron": "in-cluster-helm",
    "freelens": "desktop",
    "k9s": "cli",
    "komodo": "external-docker-compose",
    "arcane": "external-docker-compose",
}


def load(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    assert isinstance(value, dict)
    return value


def main() -> int:
    catalog = load(ROOT / "config/management-tools.yaml")
    assert management_tools.validate_catalog(catalog) == []
    assert set(catalog["tools"]) == set(EXPECTED_MODELS)
    for name, model in EXPECTED_MODELS.items():
        tool = catalog["tools"][name]
        assert tool["deploymentModel"] == model
        assert "latest" not in str(tool).lower().replace("https://headlamp.dev/docs/latest", "")
    assert catalog["selection"]["requireDigestPins"] is True
    assert catalog["tools"]["rancher"]["helmMajor"] == 3
    assert catalog["tools"]["devtron"]["helmMajor"] == 3
    assert catalog["tools"]["devtron"]["minHelmVersion"] == "3.8.0"
    assert management_tools.parse_chart_versions("headlamp=0.32.0,rancher=2.11.4") == {
        "headlamp": "0.32.0",
        "rancher": "2.11.4",
    }
    assert management_tools.is_digest_pinned_image(
        "ghcr.io/example/management@sha256:" + "a" * 64
    )
    assert not management_tools.is_digest_pinned_image("ghcr.io/example/management:1.0.0")
    assert management_tools.is_version_pin("1.0.0")
    assert not management_tools.is_version_pin("1.0")
    assert management_tools.detected_workstation_version("k9s version v0.51.0") == "0.51.0"
    assert management_tools.version_at_least((3, 8, 0), "3.8.0")
    assert not management_tools.version_at_least((3, 7, 9), "3.8.0")

    for values_path in [
        ROOT / "helm/urban-platform-infra/values.yaml",
        ROOT / "helm/urban-platform-infra/values-production.yaml",
    ]:
        values = load(values_path)
        block = values["managementTools"]
        assert block["enabled"] is False
        assert block["requireExplicitSelection"] is True
        assert block["requirePinnedVersions"] is True
        assert block["requireDigestPins"] is True
        assert block["allowMutableTags"] is False
        assert block["allowDockerSocket"] is False
        assert block["requirePrivateEnvironmentFile"] is True
        for name in EXPECTED_MODELS:
            assert block[name]["enabled"] is False

    invalid = copy.deepcopy(catalog)
    invalid["enabledByDefault"] = True
    invalid["tools"]["arcane"]["version"] = "latest"
    errors = management_tools.validate_catalog(invalid)
    assert any("enabledByDefault" in error for error in errors)
    assert any("mutable version" in error for error in errors)

    compose_text = "\n".join(
        (ROOT / compose_path).read_text(encoding="utf-8")
        for compose_path in [
            "compose/management-tools-komodo.yml",
            "compose/management-tools-arcane.yml",
        ]
    )
    for token in [
        "profiles: [komodo]",
        "profiles: [arcane]",
        "KOMODO_MONGO_IMAGE:?",
        "KOMODO_CORE_IMAGE:?",
        "KOMODO_PERIPHERY_IMAGE:?",
        "ARCANE_IMAGE:?",
        "KOMODO_DATABASE_PASSWORD:?",
        "KOMODO_INIT_ADMIN_PASSWORD:?",
        "KOMODO_JWT_SECRET:?",
        "ARCANE_ENCRYPTION_KEY:?",
        "ARCANE_JWT_SECRET:?",
        "/var/run/docker.sock:/var/run/docker.sock",
        "cgroup: host",
    ]:
        assert token in compose_text, token
    assert ":latest" not in compose_text
    assert "image: latest" not in compose_text

    with tempfile.TemporaryDirectory() as temporary:
        values_file = Path(temporary) / "portainer.values.yaml"
        values_file.write_text(
            "enterpriseEdition:\n  enabled: false\npersistence:\n  enabled: true\n",
            encoding="utf-8",
        )
        management_tools.validate_private_values(
            "portainer", catalog["tools"]["portainer"], values_file
        )

        env_file = Path(temporary) / "compose.env"
        env_file.write_text(
            "KOMODO_DATABASE_PASSWORD=private-value\n"
            "KOMODO_CORE_IMAGE=ghcr.io/example/core:2@sha256:"
            + "b" * 64
            + "\n",
            encoding="utf-8",
        )
        args = type("Args", (), {"env_file": str(env_file)})()
        values = {
            "managementTools": {
                "komodo": {
                    "externalHost": "https://komodo.example.invalid",
                    "mongoImage": "docker.io/library/mongo:8@sha256:" + "a" * 64,
                },
                "arcane": {
                    "image": "ghcr.io/getarcaneapp/manager:2.8.1@sha256:" + "c" * 64,
                    "projectsDirectory": str(Path(temporary) / "arcane-projects"),
                    "buildsDirectory": str(Path(temporary) / "arcane-builds"),
                },
            }
        }
        contexts, aggregate = management_tools.compose_context(
            args, catalog, values, ["komodo", "arcane"]
        )
        assert contexts["komodo"][0]["KOMODO_HOST"] == "https://komodo.example.invalid"
        assert contexts["komodo"][0]["KOMODO_DATABASE_PASSWORD"] == "private-value"
        assert contexts["komodo"][0]["KOMODO_MONGO_IMAGE"].endswith("@sha256:" + "a" * 64)
        assert contexts["komodo"][0]["KOMODO_ENV_FILE"] == str(env_file)
        assert contexts["arcane"][0]["ARCANE_IMAGE"].endswith("@sha256:" + "c" * 64)
        assert contexts["arcane"][0]["ARCANE_ENV_FILE"] == str(env_file)
        assert aggregate["KOMODO_CORE_IMAGE"].endswith("@sha256:" + "b" * 64)
        assert management_tools.missing_compose_environment(
            ["arcane"], catalog, contexts["arcane"][0]
        ) == [
            "ARCANE_ENCRYPTION_KEY",
            "ARCANE_JWT_SECRET",
        ]
        no_file_contexts = {"arcane": ({}, None)}
        assert management_tools.missing_compose_environment(
            ["arcane"], catalog, {}, no_file_contexts
        ) == [
            "ARCANE_BUILDS_DIRECTORY",
            "ARCANE_ENCRYPTION_KEY",
            "ARCANE_IMAGE",
            "ARCANE_JWT_SECRET",
            "ARCANE_PROJECTS_DIRECTORY",
            "arcane.environmentFile",
        ]
    print("Management-tool integration policy tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
