#!/usr/bin/env python3
"""Boundary tests for lifecycle freshness and approval-only version policy."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "version_policy.py"
SPEC = importlib.util.spec_from_file_location("version_policy", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load version policy module")
version_policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(version_policy)


def blocking(errors: list[str]) -> list[str]:
    return [error for error in errors if not error.startswith("WARN:")]


policy = version_policy.load_mapping(ROOT / "config/version-policy.yaml")
current_errors = blocking(version_policy.validate_policy(policy))
if current_errors:
    raise SystemExit(f"current version policy is invalid: {current_errors}")

future_policy = copy.deepcopy(policy)
future_policy["components"]["helm"]["lifecycle"]["lastReviewed"] = "2999-01-01"
future_errors = blocking(version_policy.validate_policy(future_policy))
expected = "component helm lifecycle lastReviewed date is in the future"
if expected not in future_errors:
    raise SystemExit("future lifecycle review date was not rejected")

print("Version policy lifecycle boundary tests passed.")
