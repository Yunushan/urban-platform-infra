#!/usr/bin/env python3
"""Run a public-safe private-data audit for repository content."""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXCLUDED_DIRS = {
    ".ansible",
    ".git",
    ".terraform",
    ".venv",
    "build",
    "charts",
    "coverage",
    "dist",
    "node_modules",
    "rendered",
    "reports",
    "venv",
}
DEFAULT_SKIPPED_FILES = {
    Path("scripts/validate.py"),
    Path("scripts/tools/private_data_audit.py"),
}
SENSITIVE_DIRS = {
    Path("secrets"),
    Path("inventories/prod"),
}
ALLOWED_SENSITIVE_FILES = {".gitkeep"}
DECRYPTED_MARKERS = [
    ".decrypted.",
    ".plain.",
    ".sops.dec.",
    ".unsealed.",
]
TEXT_SUFFIX_ALLOW = {
    "",
    ".cfg",
    ".conf",
    ".gotmpl",
    ".ini",
    ".j2",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".txt",
    ".yaml",
    ".yml",
}
SECRET_PATTERNS = {
    "github-token": re.compile(r"ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}"),
    "gitlab-token": re.compile(r"glpat-[A-Za-z0-9_-]{20,}"),
    "aws-access-key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "google-api-key": re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    "slack-token": re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),
    "openai-style-token": re.compile(r"sk-[A-Za-z0-9]{20,}"),
    "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
PRIVATE_LOOKING_IP_PATTERN = re.compile(
    r"\b(10\.10\.10\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3})\b"
)
DISCLOSURE_IDENTIFIER_PATTERN = re.compile(
    r"(istanbulkart|iett|vms|tsc2a9|smartflow|scm-|tsc-|camera-ttu|taxi-stand|car-park|"
    r"bicycle-road|pedestrian-button|tsd-junction|program-archive|camera-manager|ops-scm-log|"
    r"services-(?!networking))",
    re.IGNORECASE,
)
KUBECONFIG_PATTERN = re.compile(r"(?ms)kind:\s*Config\b.*\bclusters:\s*-\s*cluster:")


@dataclass(frozen=True)
class Finding:
    severity: str
    category: str
    path: str
    line: int
    detail: str


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def tracked_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return []
    return [ROOT / line.strip() for line in completed.stdout.splitlines() if line.strip()]


def repository_files(include_untracked: bool) -> list[Path]:
    files = set(tracked_files())
    if include_untracked or not files:
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT)
            if any(part in DEFAULT_EXCLUDED_DIRS for part in rel.parts):
                continue
            files.add(path)
    return sorted(
        path for path in files
        if path.exists() and path.relative_to(ROOT) not in DEFAULT_SKIPPED_FILES
    )


def is_text_candidate(path: Path) -> bool:
    if path.suffix.lower() not in TEXT_SUFFIX_ALLOW:
        return False
    try:
        path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    return True


def line_number_for(text: str, match: re.Match[str]) -> int:
    return text.count("\n", 0, match.start()) + 1


def audit_sensitive_dirs() -> list[Finding]:
    findings: list[Finding] = []
    for rel_dir in sorted(SENSITIVE_DIRS):
        path = ROOT / rel_dir
        if not path.exists():
            findings.append(
                Finding(
                    "ERROR",
                    "missing-sensitive-placeholder",
                    rel_dir.as_posix(),
                    0,
                    "Sensitive placeholder directory is missing.",
                )
            )
            continue
        for child in path.iterdir():
            if child.name not in ALLOWED_SENSITIVE_FILES:
                findings.append(
                    Finding(
                        "ERROR",
                        "sensitive-directory-content",
                        relative_path(child),
                        0,
                        "Sensitive directory must stay placeholder-only in Git.",
                    )
                )
    return findings


def audit_file(path: Path) -> list[Finding]:
    rel = relative_path(path)
    findings: list[Finding] = []
    if any(marker in path.name for marker in DECRYPTED_MARKERS):
        findings.append(
            Finding("ERROR", "decrypted-secret-artifact", rel, 0, "Decrypted secret artifact must not be committed.")
        )
    if not is_text_candidate(path):
        return findings
    text = path.read_text(encoding="utf-8")
    for category, pattern in SECRET_PATTERNS.items():
        match = pattern.search(text)
        if match:
            findings.append(
                Finding("ERROR", category, rel, line_number_for(text, match), "High-confidence secret token pattern.")
            )
    private_match = PRIVATE_LOOKING_IP_PATTERN.search(text)
    if private_match:
        findings.append(
            Finding(
                "ERROR",
                "private-infrastructure-address",
                rel,
                line_number_for(text, private_match),
                "Private-looking infrastructure address pattern.",
            )
        )
    disclosure_match = DISCLOSURE_IDENTIFIER_PATTERN.search(text)
    if disclosure_match:
        findings.append(
            Finding(
                "ERROR",
                "disclosure-prone-identifier",
                rel,
                line_number_for(text, disclosure_match),
                "Original disclosure-prone service identifier pattern.",
            )
        )
    kubeconfig_match = KUBECONFIG_PATTERN.search(text)
    if kubeconfig_match:
        findings.append(
            Finding("ERROR", "kubeconfig", rel, line_number_for(text, kubeconfig_match), "Kubeconfig-like document.")
        )
    return findings


def render_report(findings: list[Finding], scanned_count: int) -> str:
    lines = [
        "# Private Data Audit",
        "",
        "This report is public-safe. It reports categories, repository-relative paths, and line numbers only.",
        "",
        f"- Files scanned: `{scanned_count}`",
        f"- Findings: `{len(findings)}`",
        "",
        "| Severity | Category | Path | Line | Detail |",
        "|---|---|---|---|---|",
    ]
    if not findings:
        lines.append("| `OK` | `none` | `-` | `-` | No private-data findings. |")
    for finding in findings:
        line = str(finding.line) if finding.line else "-"
        lines.append(
            f"| `{finding.severity}` | `{finding.category}` | `{finding.path}` | `{line}` | {finding.detail} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit repository content for private data and secret-looking material.")
    parser.add_argument("--report", default="reports/private-data-audit.md", help="Markdown report path.")
    parser.add_argument("--include-untracked", action="store_true", help="Also scan untracked non-ignored files.")
    parser.add_argument("--no-fail", action="store_true", help="Always exit 0 after writing the report.")
    args = parser.parse_args(argv)

    files = repository_files(include_untracked=args.include_untracked)
    findings = audit_sensitive_dirs()
    for path in files:
        findings.extend(audit_file(path))
    findings = sorted(findings, key=lambda item: (item.severity, item.category, item.path, item.line))

    report = Path(args.report)
    if not report.is_absolute():
        report = ROOT / report
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(findings, len(files)), encoding="utf-8")
    print(f"Private data audit report written to {report}")
    if findings:
        for finding in findings:
            line = f":{finding.line}" if finding.line else ""
            print(f"{finding.severity}: {finding.category}: {finding.path}{line}")
        if not args.no_fail:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
