#!/usr/bin/env python3
"""Boundary tests for mandatory tool semantic-version enforcement."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "tools" / "tool_inventory.py"
SPEC = importlib.util.spec_from_file_location("tool_inventory", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load tool inventory module")
tool_inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool_inventory)


def check(version_output: str) -> dict[str, str]:
    contract = {
        "displayName": "Cosign 3.1.3+",
        "commands": ["cosign"],
        "versionArgs": ["version", "--json"],
        "minimumVersion": "3.1.3",
    }
    with (
        patch.object(tool_inventory, "command_for", return_value=("cosign", "/usr/bin/cosign")),
        patch.object(tool_inventory, "run_version", return_value=(True, version_output)),
    ):
        return tool_inventory.check_tool("cosign", contract, True)


def check_expected(version_output: str) -> dict[str, str]:
    contract = {
        "displayName": "Helm 4.2.1",
        "commands": ["helm"],
        "versionArgs": ["version", "--short"],
        "expectedVersion": "4.2.1",
    }
    with (
        patch.object(tool_inventory, "command_for", return_value=("helm", "/usr/bin/helm")),
        patch.object(tool_inventory, "run_version", return_value=(True, version_output)),
    ):
        return tool_inventory.check_tool("helm", contract, True)


def main() -> int:
    if check('{"gitVersion":"v3.1.3"}')["status"] != "OK":
        raise AssertionError("minimum Cosign version must be accepted")
    if check('{"gitVersion":"v3.1.4"}')["status"] != "OK":
        raise AssertionError("newer Cosign patch version must be accepted")
    if check('{"gitVersion":"v4.0.0"}')["status"] != "OK":
        raise AssertionError("newer Cosign major version must be accepted")
    if check('{"gitVersion":"v3.1.2"}')["status"] != "VERSION-MISMATCH":
        raise AssertionError("vulnerable Cosign version must be rejected")
    if check("unparseable")["status"] != "VERSION-MISMATCH":
        raise AssertionError("unparseable mandatory version must fail closed")
    if check_expected("v4.2.1+gd591a19")["status"] != "OK":
        raise AssertionError("exact expected version must accept build metadata")
    if check_expected("v4.2.10")["status"] != "VERSION-MISMATCH":
        raise AssertionError("exact expected version must reject a later patch")
    if check_expected("v14.2.1")["status"] != "VERSION-MISMATCH":
        raise AssertionError("exact expected version must reject a different major")
    print("Tool inventory semantic-version boundary tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
