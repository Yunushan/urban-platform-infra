#!/usr/bin/env python3
"""Exercise release evidence generation and fail-closed verification offline."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    generator = load_module(ROOT / "scripts/release/generate_sbom.py", "release_generator")
    verifier = load_module(ROOT / "scripts/release/verify_release_evidence.py", "release_verifier")

    with tempfile.TemporaryDirectory(prefix="urban-release-evidence-") as directory:
        root = Path(directory)
        chart = root / "helm/urban-platform-infra"
        dist = root / "dist"
        config = root / "config"
        chart.mkdir(parents=True)
        dist.mkdir()
        config.mkdir()
        (chart / "Chart.yaml").write_text(
            "apiVersion: v2\nname: urban-platform-infra\nversion: 0.1.0\nappVersion: 0.1.0\n",
            encoding="utf-8",
        )
        (config / "supply-chain-policy.yaml").write_text(
            """policy:
  releaseVerification:
    verifyTagMatchesChartVersion: true
  releaseArtifacts:
    chartPackage: dist/urban-platform-infra-<version>.tgz
    renderedManifest: dist/rendered.yaml
    productionRenderedManifest: dist/production-rendered.yaml
    sbom: dist/urban-platform-infra.spdx.json
    releaseManifest: dist/release-evidence.json
    checksums: dist/SHA256SUMS
""",
            encoding="utf-8",
        )
        chart_package = dist / "urban-platform-infra-0.1.0.tgz"
        rendered = dist / "rendered.yaml"
        production_rendered = dist / "production-rendered.yaml"
        sbom = dist / "urban-platform-infra.spdx.json"
        manifest = dist / "release-evidence.json"
        checksums = dist / "SHA256SUMS"
        chart_package.write_bytes(b"synthetic chart package")
        rendered.write_text("apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: default\n", encoding="utf-8")
        production_rendered.write_text("apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: production\n", encoding="utf-8")

        generator.ROOT = root
        generator.build_sbom(chart, dist, rendered, sbom, checksums, manifest, [production_rendered])
        generator.build_release_manifest(chart, dist, rendered, sbom, checksums, manifest, [production_rendered])
        artifacts = generator.release_artifacts(
            dist, rendered, sbom, checksums, manifest, [production_rendered]
        )
        generator.write_checksums(artifacts, sbom, manifest, checksums)

        verifier.ROOT = root
        arguments = [
            "verify_release_evidence.py",
            "--chart",
            "helm/urban-platform-infra",
            "--policy",
            "config/supply-chain-policy.yaml",
            "--tag",
            "v0.1.0",
            "--report",
            "reports/verification.md",
        ]
        with patch.object(sys, "argv", arguments):
            if verifier.main() != 0:
                raise SystemExit("valid release evidence was rejected")

        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        production_record = next(
            record
            for record in manifest_data["artifacts"]
            if record["path"] == "dist/production-rendered.yaml"
        )
        if production_record["kind"] != "productionRenderedManifest":
            raise SystemExit("production render was not classified in release evidence")

        production_rendered.write_text(production_rendered.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
        with patch.object(sys, "argv", arguments):
            if verifier.main() == 0:
                raise SystemExit("drifted production render passed release evidence verification")

    print("Release evidence generation and verification tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
