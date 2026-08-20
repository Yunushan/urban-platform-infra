#!/usr/bin/env python3
"""Exercise the private production evidence gate with synthetic local evidence."""
from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import production_evidence_gate as gate


DIGEST = "sha256:" + ("a" * 64)


def write_yaml(path: Path, value: dict) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="urban-production-evidence-") as directory:
        root = Path(directory)
        evidence_root = root / "images"
        dr_root = root / "dr"
        evidence_root.mkdir()
        dr_root.mkdir()
        for name in gate.REQUIRED_DR_ARTIFACTS:
            (dr_root / f"{name}.txt").write_text("synthetic evidence\n", encoding="utf-8")
        base_values = root / "values.yaml"
        public_values = root / "values-production.yaml"
        private_values = root / "values-private.yaml"
        write_yaml(base_values, {"global": {"imageRegistry": ""}, "workloads": {"demo": {"image": {"repository": "example-app-demo", "tag": "0.1.0"}}}})
        write_yaml(public_values, {})
        write_yaml(private_values, {"global": {"imageRegistry": "registry.internal/platform"}, "workloads": {"demo": {"image": {"repository": "demo", "tag": "1.0.0", "digest": DIGEST}}}})
        index = evidence_root / "index.yaml"
        write_yaml(
            index,
            {
                "version": 1,
                "images": [
                    {
                        "path": "workloads.demo.image",
                        "reference": f"registry.internal/platform/demo:1.0.0@{DIGEST}",
                        "digest": DIGEST,
                        "vulnerabilityScan": "scan.txt",
                        "sbom": "sbom.txt",
                        "signatureOrAttestation": "signature.txt",
                        "promotionRecord": "promotion.txt",
                    }
                ],
            },
        )
        for name in ("scan.txt", "sbom.txt", "signature.txt", "promotion.txt"):
            (evidence_root / name).write_text("synthetic evidence\n", encoding="utf-8")
        config_path = root / "evidence.yaml"
        config = {
            "version": 1,
            "release": {"tag": "v1.2.3", "owner": "test-owner", "valuesOverlay": str(private_values)},
            "registry": {"privateRegistry": "registry.internal/platform", "evidenceRoot": str(evidence_root), "imageEvidenceIndex": "index.yaml"},
            "disasterRecovery": {"evidenceRoot": str(dr_root), "artifacts": {name: f"{name}.txt" for name in gate.REQUIRED_DR_ARTIFACTS}},
            "liveCluster": {"required": False},
        }
        write_yaml(config_path, config)
        loaded = gate.load_yaml(config_path)
        release_ok, _, private_overlay = gate.validate_release(loaded, root)
        image_ok, _, image_count = gate.validate_registry(loaded, root, base_values, public_values, private_overlay)
        dr_ok, _, dr_count = gate.validate_dr(loaded, root)
        live_ok, _ = gate.validate_live(loaded, run_live=False)
        if not (release_ok and image_ok and dr_ok and live_ok and image_count == 1 and dr_count == len(gate.REQUIRED_DR_ARTIFACTS)):
            raise SystemExit("synthetic production evidence gate test failed")
    print("Production evidence gate synthetic pass-path test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
