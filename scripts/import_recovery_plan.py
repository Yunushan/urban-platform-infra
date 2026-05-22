#!/usr/bin/env python3
"""Generate a public-safe import resume, rollback, and cleanup recovery plan."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATEFUL_STAGES = ["secrets", "images", "databases", "manifests"]


def bool_text(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def display_path(path: str, placeholder: str, redact: bool) -> str:
    if redact and path:
        return placeholder
    return path or "-"


def strip_quotes(value: str) -> str:
    text = value.strip()
    if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')):
        return text[1:-1]
    return text


def parse_simple_state(path: Path) -> tuple[bool, str, list[dict[str, str]]]:
    if not path.exists():
        return False, "", []
    entries: list[dict[str, str]] = []
    updated_at = ""
    in_completed = False
    current: dict[str, str] | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if indent == 0:
            in_completed = stripped == "completed:"
            if stripped.startswith("updatedAt:"):
                updated_at = strip_quotes(stripped.split(":", 1)[1])
            continue
        if not in_completed:
            continue
        if indent == 2 and stripped.endswith(":"):
            if current:
                entries.append(current)
            current = {"key": strip_quotes(stripped[:-1])}
            continue
        if indent == 4 and current is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            current[key.strip()] = strip_quotes(value)
    if current:
        entries.append(current)
    return True, updated_at, entries


def report_presence(base: Path) -> list[tuple[str, bool]]:
    files = [
        "migration-automation.md",
        "import-profile.md",
        "import-preflight.md",
        "import-capacity.md",
        "import-batches.md",
        "import-resume.md",
        "post-migration-check.md",
        "manifests/imported-workloads.yaml",
        "manifests/traefik-ingress-candidates.yaml",
    ]
    return [(item, (base / item).exists()) for item in files]


def stage_status(entries: list[dict[str, str]]) -> dict[str, int]:
    return Counter(str(item.get("stage", "")).strip() for item in entries)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe import recovery plan.")
    parser.add_argument("--output", default="reports/import-migration/import-recovery-plan.md")
    parser.add_argument("--migration-output", default="reports/import-migration")
    parser.add_argument("--private-dir", default="/var/lib/urban-platform/private")
    parser.add_argument("--state-file", default="")
    parser.add_argument("--namespace", default="urban-platform")
    parser.add_argument("--profile", default="lab")
    parser.add_argument("--image-mode", default="preload")
    parser.add_argument("--import-batch", default="auto")
    parser.add_argument("--resume", default="true")
    parser.add_argument("--force-rerun", default="false")
    parser.add_argument("--cleanup-operator-images", default="true")
    parser.add_argument("--prune-operator-cache", default="true")
    parser.add_argument("--rke2-import-images", default="true")
    parser.add_argument("--redact-sensitive", action="store_true")
    args = parser.parse_args()

    migration_output = Path(args.migration_output).expanduser()
    state_file = args.state_file or str(Path(args.private_dir).expanduser() / "migration-state.yaml")
    state_path = Path(state_file).expanduser()
    state_exists, updated_at, entries = parse_simple_state(state_path)
    counts = stage_status(entries)
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)

    resume = bool_text(args.resume)
    force_rerun = bool_text(args.force_rerun)
    cleanup_operator_images = bool_text(args.cleanup_operator_images)
    prune_operator_cache = bool_text(args.prune_operator_cache)
    rke2_import_images = bool_text(args.rke2_import_images)

    findings: list[tuple[str, str]] = []
    if not state_exists:
        findings.append(("WARN", "Private migration state file was not found. The next run will not skip completed mutation stages unless another state file is selected."))
    if force_rerun:
        findings.append(("WARN", "`MIGRATION_FORCE_RERUN=true` will rerun stateful stages even when the state file marks them completed."))
    if not resume:
        findings.append(("WARN", "`MIGRATION_RESUME=false` ignores the private state file for this run."))
    if args.profile == "lab" and str(args.import_batch).strip().lower() == "all":
        findings.append(("WARN", "Lab import batch is `all`; use `auto` or a numbered batch unless capacity is already proven."))
    if args.image_mode == "preload" and not cleanup_operator_images:
        findings.append(("WARN", "Operator image/archive cleanup is disabled; monitor operator disk before retrying large imports."))
    if args.image_mode == "preload" and not prune_operator_cache:
        findings.append(("WARN", "Operator container cache pruning is disabled; this is useful for debugging but risky on small disks."))
    if args.image_mode == "preload" and not rke2_import_images:
        findings.append(("WARN", "RKE2 containerd import is disabled; copied archives may require an RKE2 restart or manual import before pods can start."))
    if not findings:
        findings.append(("OK", "Recovery controls are internally consistent."))

    status = "WARN" if any(level == "WARN" for level, _ in findings) else "PASS"
    state_display = display_path(str(state_path), "<private-state-file>", args.redact_sensitive)
    private_dir_display = display_path(str(Path(args.private_dir).expanduser()), "<private-operator-dir>", args.redact_sensitive)

    lines = [
        "# Import Recovery Plan",
        "",
        "This report is public-safe when redaction is enabled. It does not print project paths, node names, image names, database DSNs, registry credentials, secret values, or raw migration state keys.",
        "",
        f"- Result: `{status}`",
        f"- Namespace: `{args.namespace}`",
        f"- Migration profile: `{args.profile}`",
        f"- Image mode: `{args.image_mode}`",
        f"- Import batch: `{args.import_batch}`",
        f"- Resume enabled: `{str(resume).lower()}`",
        f"- Force rerun: `{str(force_rerun).lower()}`",
        f"- State file: `{state_display}`",
        f"- State file present: `{str(state_exists).lower()}`",
        f"- State updated at: `{updated_at or '-'}`",
        f"- Private operator directory: `{private_dir_display}`",
        f"- Cleanup operator images: `{str(cleanup_operator_images).lower()}`",
        f"- Prune operator cache: `{str(prune_operator_cache).lower()}`",
        f"- RKE2 containerd import: `{str(rke2_import_images).lower()}`",
        "",
        "## Resume Status",
        "",
        "| Stage | Completed scopes | Normal rerun behavior |",
        "|---|---:|---|",
    ]
    for stage in STATEFUL_STAGES:
        completed = counts.get(stage, 0)
        behavior = "skipped when scope matches" if resume and not force_rerun and completed else "runs when selected"
        lines.append(f"| `{stage}` | `{completed}` | {behavior} |")

    lines.extend(
        [
            "",
            "## Public Artifacts",
            "",
            "| Artifact | Present |",
            "|---|---|",
        ]
    )
    for artifact, present in report_presence(migration_output):
        lines.append(f"| `{artifact}` | `{str(present).lower()}` |")

    lines.extend(
        [
            "",
            "## Safe Retry Controls",
            "",
            "- Re-run the same `make import-auto ...` command first. With `MIGRATION_RESUME=true`, completed stateful stages are skipped when their scope still matches.",
            "- Use `MIGRATION_FORCE_RERUN=true` only when you intentionally need to rebuild images, reapply secrets/manifests, or rerun database restore for the same scope.",
            "- Use a separate private `MIGRATION_STATE_FILE` for rehearsals that should not share resume history.",
            "- Keep preflight and validation enabled on every retry; cluster readiness can change between runs.",
            "",
            "## Cleanup Boundaries",
            "",
            "- Operator image tags, local preload archives, and dangling build cache are safe to clean automatically when `MIGRATION_CLEANUP_OPERATOR_IMAGES=true` and `MIGRATION_PRUNE_OPERATOR_CACHE=true`.",
            "- Node-side RKE2 containerd images should not be pruned automatically; running or pending pods may still need them.",
            "- Private database dumps under the dump directory are recovery evidence. Archive or expire them through the backup policy, not ad hoc cleanup.",
            "- Do not delete the private state file to retry; prefer `MIGRATION_FORCE_RERUN=true` or a new private state file.",
            "",
            "## Rollback Boundaries",
            "",
            "- Imported workload manifests are generated under `manifests/imported-workloads.yaml`; review the file before deleting any applied resources.",
            "- Imported Traefik route candidates are generated under `manifests/traefik-ingress-candidates.yaml`; route rollback should not delete backend Services blindly.",
            "- Direct Kubernetes Secret rollback should be handled by reapplying the intended secret provider state or deleting reviewed generated resources only.",
            "- Database dump/restore is not automatically rolled back. Restore from a known backup/snapshot or rerun restore against a reviewed target map.",
            "- Helm release rollback remains the break-glass path for chart-managed platform resources; direct import manifests are separate from the Helm release.",
            "",
            "## Operator Commands",
            "",
            "```bash",
            "make import-recovery-plan IMPORT_REDACT=true",
            "make import-auto PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true",
            "make import-auto PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true MIGRATION_FORCE_RERUN=true",
            "make import-auto PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true MIGRATION_STATE_FILE=/path/to/private/rehearsal-state.yaml",
            "```",
            "",
            "## Findings",
            "",
        ]
    )
    lines.extend(f"- **{level}** - {message}" for level, message in findings)
    lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Import recovery plan written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
