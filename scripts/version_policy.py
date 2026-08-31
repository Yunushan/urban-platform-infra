#!/usr/bin/env python3
"""Validate and gate manual platform-version update requests.

This tool deliberately has no automatic update mode. A plan is read-only, a
request creates evidence, and apply requires an explicit manual request,
approval reference, change ticket, rollback plan, and --execute. Apply updates
the committed policy pin only; deployment remains a separate reviewed action.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - CI installs PyYAML.
    raise SystemExit("PyYAML is required for version policy checks.") from exc


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/version-policy.yaml"
VALID_STATUSES = {"supported", "maintenance", "externally-managed", "obsolete", "eol", "unknown"}
VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+][0-9A-Za-z.-]+)?$")


def load_mapping(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping.")
    return value


def parse_version(value: str) -> tuple[int, int, int] | None:
    match = VERSION_RE.fullmatch(value.strip())
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def update_type(current: str, target: str) -> str | None:
    current_parts = parse_version(current)
    target_parts = parse_version(target)
    if not current_parts or not target_parts or target_parts <= current_parts:
        return None
    if target_parts[0] != current_parts[0]:
        return "major"
    if target_parts[1] != current_parts[1]:
        return "minor"
    return "patch"


def bool_value(value: Any) -> bool:
    return value is True


def validate_policy(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    warnings: list[str] = []
    update = policy.get("updatePolicy")
    if not isinstance(update, dict):
        return ["updatePolicy must be a mapping."]
    required_false = ("autoPatch", "autoMinor", "autoMajor", "allowDirectProductionMutation")
    for key in required_false:
        if update.get(key) is not False:
            errors.append(f"updatePolicy.{key} must be false")
    required_true = (
        "requireManualRequest",
        "requireApprovalForApply",
        "requirePullRequest",
        "requireCi",
        "requireChangeTicket",
        "requireRollbackPlan",
        "requirePinnedVersion",
        "rejectEol",
        "rejectObsolete",
        "productionApproval",
    )
    for key in required_true:
        if update.get(key) is not True:
            errors.append(f"updatePolicy.{key} must be true")
    if update.get("mode") != "approval-only":
        errors.append("updatePolicy.mode must be approval-only")
    channels = policy.get("channels")
    if not isinstance(channels, dict):
        errors.append("channels must be a mapping")
    else:
        expected_channels = {"lts", "stable", "mainline", "edge"}
        missing = sorted(expected_channels - set(channels))
        if missing:
            errors.append(f"channels missing: {', '.join(missing)}")
        for name, channel in channels.items():
            if not isinstance(channel, dict) or not channel.get("allowedUpdateTypes"):
                errors.append(f"channel {name} must declare allowedUpdateTypes")
            elif not set(channel["allowedUpdateTypes"]) <= {"patch", "minor", "major"}:
                errors.append(f"channel {name} has an invalid update type")
    lifecycle = policy.get("lifecycle")
    if not isinstance(lifecycle, dict) or not lifecycle.get("reviewCadence"):
        errors.append("lifecycle must declare a reviewCadence")
    lifecycle_policy = lifecycle.get("policy", {}) if isinstance(lifecycle, dict) else {}
    for lifecycle_key in ("eolOrObsoleteBlocksApply", "missingLifecycleBlocksApply"):
        if lifecycle_policy.get(lifecycle_key) is not True:
            errors.append(f"lifecycle.policy.{lifecycle_key} must be true")
    try:
        review_max_age_days = int(lifecycle_policy.get("reviewMaxAgeDays", 0))
    except (TypeError, ValueError):
        review_max_age_days = 0
    if lifecycle_policy.get("requireFreshReview") is True and review_max_age_days < 1:
        errors.append("lifecycle.policy.reviewMaxAgeDays must be positive when fresh review is required")
    today = dt.date.today()
    components = policy.get("components")
    if not isinstance(components, dict) or not components:
        errors.append("components must be a non-empty mapping")
    else:
        for name, component in components.items():
            if not isinstance(component, dict):
                errors.append(f"component {name} must be a mapping")
                continue
            current = str(component.get("currentVersion", ""))
            component_lifecycle = component.get("lifecycle", {}) if isinstance(component.get("lifecycle"), dict) else {}
            status = str(component_lifecycle.get("status", ""))
            component_channel = component.get("channel")
            if update.get("requirePinnedVersion") and name != "rke2" and not current:
                errors.append(f"component {name} must have a pinned currentVersion")
            if current and not parse_version(current):
                errors.append(f"component {name} has an invalid currentVersion: {current}")
            if not isinstance(channels, dict) or component_channel not in channels:
                errors.append(f"component {name} must use a declared lifecycle channel")
            if status not in VALID_STATUSES:
                errors.append(f"component {name} must declare a valid lifecycle status")
            if status in {"eol", "obsolete"} and (update.get("rejectEol") or update.get("rejectObsolete")):
                errors.append(f"component {name} is marked {status}")
            if not component.get("source"):
                errors.append(f"component {name} must declare a lifecycle/version source")
            source_files = component.get("sourceFiles")
            if not source_files or not isinstance(source_files, list):
                errors.append(f"component {name} must declare sourceFiles")
            else:
                source_files_optional = component.get("sourceFilesOptional") is True
                if source_files_optional and status != "externally-managed":
                    errors.append(f"component {name} may mark sourceFilesOptional only when externally-managed")
                for source_file in source_files:
                    if not isinstance(source_file, str) or not (ROOT / source_file).is_file():
                        if not source_files_optional:
                            errors.append(f"component {name} references missing sourceFile: {source_file}")
            last_reviewed = component_lifecycle.get("lastReviewed") if isinstance(component_lifecycle, dict) else None
            if lifecycle_policy.get("requireFreshReview") is True:
                try:
                    review_date = dt.date.fromisoformat(str(last_reviewed))
                except (TypeError, ValueError):
                    review_date = None
                if review_date is None:
                    errors.append(f"component {name} must declare a valid lifecycle lastReviewed date")
                elif review_date > today:
                    errors.append(f"component {name} lifecycle lastReviewed date is in the future")
                elif (today - review_date).days > review_max_age_days:
                    errors.append(f"component {name} lifecycle review is older than {review_max_age_days} days")
            eol_date = component_lifecycle.get("eolDate") if isinstance(component_lifecycle, dict) else None
            if eol_date:
                try:
                    if dt.date.fromisoformat(str(eol_date)) <= today:
                        errors.append(f"component {name} reached its declared EOL date")
                except ValueError:
                    errors.append(f"component {name} has an invalid lifecycle eolDate")
            if status == "unknown" and lifecycle_policy.get("unknownLifecycleWarns", True):
                warnings.append(f"component {name} has unknown lifecycle status")
    return errors + [f"WARN: {warning}" for warning in warnings]


def display(value: str, redact: bool) -> str:
    return "<redacted>" if redact and value else value


def write_report(path: Path, title: str, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# " + title + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8")


def policy_report(policy: dict[str, Any], errors: list[str], title: str) -> list[str]:
    update = policy.get("updatePolicy", {})
    lines = [
        "This report is public-safe. It contains policy and version metadata only.",
        "",
        f"- Generated: `{dt.datetime.now(dt.timezone.utc).isoformat()}`",
        f"- Mode: `{update.get('mode', '<missing>')}`",
        f"- Channel: `{update.get('channel', '<missing>')}`",
        f"- Automatic patch updates: `{str(update.get('autoPatch')).lower()}`",
        f"- Automatic minor updates: `{str(update.get('autoMinor')).lower()}`",
        f"- Automatic major updates: `{str(update.get('autoMajor')).lower()}`",
        f"- Direct production mutation: `{str(update.get('allowDirectProductionMutation')).lower()}`",
        "",
        "## Components",
        "",
    ]
    for name, component in sorted((policy.get("components") or {}).items()):
        if not isinstance(component, dict):
            continue
        lifecycle = component.get("lifecycle", {}) if isinstance(component.get("lifecycle"), dict) else {}
        lines.append(
            f"- `{name}`: `{component.get('currentVersion') or '<externally managed>'}`, "
            f"channel `{component.get('channel')}`, lifecycle `{lifecycle.get('status', '<missing>')}`"
        )
    lines.extend(["", "## Findings", ""])
    if errors:
        lines.extend(f"- {error}" for error in errors)
    else:
        lines.append("- OK: automatic updates are disabled and approval-only controls are present.")
    return lines


def request_details(policy: dict[str, Any], args: argparse.Namespace) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    components = policy.get("components", {})
    component = components.get(args.component) if isinstance(components, dict) else None
    if not isinstance(component, dict):
        return {}, [f"unknown component: {args.component}"]
    current = args.current_version or str(component.get("currentVersion", ""))
    target = args.target_version.strip()
    if not current:
        errors.append(f"component {args.component} has no current version; provide --current-version")
    if not parse_version(target):
        errors.append(f"target version is not a supported numeric version: {target}")
    change = update_type(current, target) if current else None
    if not change:
        errors.append(f"target {target} must be newer than current {current}")
    channel = args.channel or str(component.get("channel", policy.get("updatePolicy", {}).get("channel", "stable")))
    channel_config = policy.get("channels", {}).get(channel, {})
    allowed = set(channel_config.get("allowedUpdateTypes", [])) if isinstance(channel_config, dict) else set()
    if channel not in policy.get("channels", {}):
        errors.append(f"unknown channel: {channel}")
    elif change and change not in allowed:
        errors.append(f"channel {channel} does not allow {change} updates")
    lifecycle = component.get("lifecycle", {}) if isinstance(component.get("lifecycle"), dict) else {}
    status = str(lifecycle.get("status", "unknown"))
    if status in {"eol", "obsolete"}:
        errors.append(f"component {args.component} is marked {status}; refresh lifecycle metadata first")
    details = {
        "component": args.component,
        "currentVersion": current,
        "targetVersion": target,
        "updateType": change or "invalid",
        "channel": channel,
        "lifecycleStatus": status,
        "manualRequest": bool(args.manual_request),
        "approvalReference": args.approval_reference,
        "changeTicket": args.change_ticket,
        "rollbackPlan": args.rollback_plan,
        "sourceFiles": component.get("sourceFiles", []),
        "source": component.get("source", ""),
    }
    return details, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and gate approval-only version updates.")
    parser.add_argument("command", choices=["check", "plan", "request", "apply"])
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output", default="reports/version-policy.md")
    parser.add_argument("--component", default="")
    parser.add_argument("--current-version", default="")
    parser.add_argument("--target-version", default="")
    parser.add_argument("--channel", default="")
    parser.add_argument("--manual-request", action="store_true")
    parser.add_argument("--approval-reference", default="")
    parser.add_argument("--change-ticket", default="")
    parser.add_argument("--rollback-plan", default="")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    try:
        policy = load_mapping(config_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    policy_errors = validate_policy(policy)
    blocking_policy_errors = [error for error in policy_errors if not error.startswith("WARN:")]
    if args.command == "check":
        write_report(Path(args.output), "Version Policy Check", policy_report(policy, policy_errors, "Version Policy Check"))
        if blocking_policy_errors:
            print("Version policy check failed.", file=sys.stderr)
            return 1
        print(f"Version policy report written: {args.output}")
        return 0

    if blocking_policy_errors:
        print("Version policy is invalid; refusing update request.", file=sys.stderr)
        for error in blocking_policy_errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    if not args.component or not args.target_version:
        print("--component and --target-version are required for update requests.", file=sys.stderr)
        return 2
    details, errors = request_details(policy, args)
    if args.command in {"request", "apply"} and not args.manual_request:
        errors.append("an explicit --manual-request is required; automatic updates are disabled")
    if args.command == "apply":
        if not args.approval_reference:
            errors.append("--approval-reference is required for apply")
        if not args.change_ticket:
            errors.append("--change-ticket is required for apply")
        if not args.rollback_plan:
            errors.append("--rollback-plan is required for apply")
        if not args.execute:
            errors.append("--execute is required for apply")
    title = f"Version Update {args.command.title()}"
    lines = policy_report(policy, errors, title)
    lines.extend([
        "",
        "## Request",
        "",
        f"- Component: `{details.get('component', args.component)}`",
        f"- Current version: `{details.get('currentVersion', args.current_version)}`",
        f"- Target version: `{details.get('targetVersion', args.target_version)}`",
        f"- Update type: `{details.get('updateType', 'invalid')}`",
        f"- Manual request: `{str(args.manual_request).lower()}`",
        f"- Approval reference supplied: `{str(bool(args.approval_reference)).lower()}`",
        f"- Change ticket supplied: `{str(bool(args.change_ticket)).lower()}`",
        f"- Rollback plan supplied: `{str(bool(args.rollback_plan)).lower()}`",
        "",
        "No cluster deployment is performed by this tool.",
    ])
    if details.get("sourceFiles"):
        lines.extend(["", "Source files to review in the approved pull request:", ""])
        lines.extend(f"- `{path}`" for path in details["sourceFiles"])
    if not errors and args.command == "apply":
        components = policy["components"]
        components[args.component]["currentVersion"] = args.target_version
        config_path.write_text(yaml.safe_dump(policy, sort_keys=False, default_flow_style=False, width=120), encoding="utf-8")
        lines.append("\n- Applied: policy pin updated after explicit approval evidence.")
        print(f"Updated approved policy pin in {config_path}")
    elif not errors and args.command == "request":
        lines.append("\n- Ready: request evidence generated; submit/review the pull request before apply.")
    elif not errors:
        lines.append("\n- Plan only: no request or file mutation was performed.")
    if errors:
        lines.extend(["", "## Blocking Findings", ""])
        lines.extend(f"- {error}" for error in errors)
    write_report(Path(args.output), title, lines)
    print(f"Version update report written: {args.output}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
