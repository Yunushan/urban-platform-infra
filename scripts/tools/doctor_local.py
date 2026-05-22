#!/usr/bin/env python3
"""Check local operator/developer tooling without mutating the machine."""

from __future__ import annotations

import argparse
import importlib.util
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str
    blocking: bool = False


def run(command: list[str]) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    output = "\n".join(
        part.strip()
        for part in [completed.stdout, completed.stderr]
        if part and part.strip()
    )
    return completed.returncode, output


def command_check(
    name: str,
    executable: str,
    version_args: list[str],
    *,
    fix: str,
    blocking: bool = False,
) -> Check:
    path = shutil.which(executable)
    if not path:
        return Check(
            name=name,
            status="MISSING" if blocking else "WARN",
            detail=f"`{executable}` is not on PATH.",
            fix=fix,
            blocking=blocking,
        )
    rc, output = run([path, *version_args])
    first_line = output.splitlines()[0] if output else "installed"
    if rc != 0:
        return Check(
            name=name,
            status="WARN",
            detail=f"`{path}` exists, but version check failed: {first_line}",
            fix=fix,
            blocking=blocking,
        )
    return Check(
        name=name,
        status="OK",
        detail=f"`{path}` - {first_line}",
        fix="",
        blocking=False,
    )


def command_presence_check(
    name: str,
    executable: str,
    *,
    fix: str,
    blocking: bool = False,
) -> Check:
    path = shutil.which(executable)
    if not path:
        return Check(
            name=name,
            status="MISSING" if blocking else "WARN",
            detail=f"`{executable}` is not on PATH.",
            fix=fix,
            blocking=blocking,
        )
    return Check(
        name=name,
        status="OK",
        detail=f"`{path}` is on PATH.",
        fix="",
        blocking=False,
    )


def module_check(name: str, module: str, *, fix: str, blocking: bool = False) -> Check:
    if importlib.util.find_spec(module) is None:
        return Check(
            name=name,
            status="MISSING" if blocking else "WARN",
            detail=f"Python module `{module}` is not importable from `{sys.executable}`.",
            fix=fix,
            blocking=blocking,
        )
    return Check(
        name=name,
        status="OK",
        detail=f"Python module `{module}` is importable from `{sys.executable}`.",
        fix="",
    )


def venv_python(venv: Path) -> Path | None:
    candidates = [
        venv / "bin" / "python3",
        venv / "bin" / "python",
        venv / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def venv_check(venv: Path) -> Check:
    python_path = venv_python(venv)
    if not python_path:
        return Check(
            name="Repository virtualenv",
            status="WARN",
            detail=f"No Python virtualenv was found at `{venv}`.",
            fix="Run `make setup-local` or `python scripts/tools/setup_local.py`.",
            blocking=False,
        )
    rc, output = run([str(python_path), "--version"])
    detail = output.splitlines()[0] if output else str(python_path)
    if rc != 0:
        return Check(
            name="Repository virtualenv",
            status="WARN",
            detail=f"`{python_path}` exists, but it did not run correctly.",
            fix="Recreate the virtualenv with `make setup-local`.",
            blocking=False,
        )
    return Check(
        name="Repository virtualenv",
        status="OK",
        detail=f"`{python_path}` - {detail}",
        fix="",
    )


def python_check() -> Check:
    version = sys.version_info
    detail = f"`{sys.executable}` - Python {version.major}.{version.minor}.{version.micro}"
    if version < (3, 11):
        return Check(
            name="Current Python",
            status="MISSING",
            detail=detail,
            fix="Install Python 3.11 or newer, then run `make setup-local`.",
            blocking=True,
        )
    return Check(name="Current Python", status="OK", detail=detail, fix="")


def workspace_check() -> Check:
    required = ["Makefile", "scripts/validate.py", "helm/urban-platform-infra/Chart.yaml"]
    missing = [path for path in required if not (ROOT / path).exists()]
    if missing:
        return Check(
            name="Repository root",
            status="MISSING",
            detail=f"Missing expected files: {', '.join(missing)}",
            fix="Run the doctor from the repository root or repair the checkout.",
            blocking=True,
        )
    return Check(
        name="Repository root",
        status="OK",
        detail=f"Detected repository root `{ROOT}`.",
        fix="",
    )


def collect_checks(args: argparse.Namespace) -> list[Check]:
    checks = [
        workspace_check(),
        python_check(),
        venv_check(ROOT / args.venv),
        module_check(
            "PyYAML",
            "yaml",
            fix="Run `make setup-local` or `python -m pip install -r requirements-ci.txt`.",
            blocking=True,
        ),
        module_check(
            "yamllint Python package",
            "yamllint",
            fix="Run `make setup-local`.",
            blocking=True,
        ),
        module_check(
            "Ansible Python package",
            "ansible",
            fix="Run `make setup-local`; use WSL/Linux for Ansible control-node operations on Windows.",
        ),
        command_check("Git", "git", ["--version"], fix="Install Git.", blocking=True),
        command_check("Make", "make", ["--version"], fix="Install GNU Make.", blocking=True),
        command_check("Bash", "bash", ["--version"], fix="Install Git Bash, WSL, or bash.", blocking=True),
        command_check("yamllint command", "yamllint", ["--version"], fix="Run `make setup-local`.", blocking=True),
        command_check("ShellCheck", "shellcheck", ["--version"], fix="Install ShellCheck for `make lint`.", blocking=True),
        command_check("Ansible playbook", "ansible-playbook", ["--version"], fix="Run `make setup-local`; prefer WSL/Linux for cluster mutation."),
        command_check("Ansible Galaxy", "ansible-galaxy", ["--version"], fix="Run `make setup-local`; prefer WSL/Linux for cluster mutation."),
        command_check("Helm", "helm", ["version", "--short"], fix="Run `make install-helm` on Linux/WSL or install Helm on Windows."),
        command_check("Helmfile", "helmfile", ["--version"], fix="Run `make install-helmfile` on Linux/WSL or install Helmfile."),
        command_check("kubectl", "kubectl", ["version", "--client=true"], fix="Install kubectl and configure kubeconfig before deploy/import."),
        command_check("Docker", "docker", ["version", "--format", "{{.Client.Version}}"], fix="Install Docker/Podman for image import or registry promotion."),
        command_check("Podman", "podman", ["--version"], fix="Install Docker or Podman for image import or registry promotion."),
        command_check("OpenSSH client", "ssh", ["-V"], fix="Install OpenSSH client for RKE2 node access."),
        command_presence_check("SCP", "scp", fix="Install OpenSSH scp for RKE2 preload mode."),
        command_check("OpenSSL", "openssl", ["version"], fix="Install OpenSSL for self-signed lab TLS fallback."),
    ]
    if platform.system().lower() == "windows":
        checks.append(
            Check(
                name="Windows operator note",
                status="WARN",
                detail="Native Windows can inspect and render parts of the repo, but Ansible control-node operations are best run from WSL or a Linux operator host.",
                fix="Use WSL/Linux for `make bootstrap`, `make install-cluster`, `make deploy`, and mutating import runs.",
            )
        )
    return checks


def render_markdown(checks: list[Check]) -> str:
    lines = [
        "# Local Toolchain Doctor",
        "",
        "This report is public-safe. It contains tool names, versions, and generic remediation guidance only.",
        "",
        "| Check | Status | Detail | Remediation |",
        "|---|---|---|---|",
    ]
    for check in checks:
        detail = check.detail.replace("|", "\\|")
        fix = check.fix.replace("|", "\\|") if check.fix else "-"
        lines.append(f"| {check.name} | `{check.status}` | {detail} | {fix} |")
    return "\n".join(lines) + "\n"


def print_console(checks: list[Check]) -> None:
    width = max(len(check.name) for check in checks)
    for check in checks:
        marker = {
            "OK": "[OK]",
            "WARN": "[WARN]",
            "MISSING": "[MISSING]",
        }.get(check.status, "[INFO]")
        print(f"{marker:<10} {check.name:<{width}}  {check.detail}")
        if check.fix:
            print(f"{'':<10} {'':<{width}}  fix: {check.fix}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose local operator/developer toolchain readiness.")
    parser.add_argument("--venv", default=".venv", help="Repository virtualenv path to check.")
    parser.add_argument("--report", default="", help="Optional Markdown report path.")
    parser.add_argument("--no-fail", action="store_true", help="Always exit 0 after printing the report.")
    args = parser.parse_args(argv)

    checks = collect_checks(args)
    print_console(checks)

    if args.report:
        report_path = Path(args.report)
        if not report_path.is_absolute():
            report_path = ROOT / report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_markdown(checks), encoding="utf-8")
        print(f"\nWrote local toolchain report: {report_path}")

    blocking = [check for check in checks if check.blocking and check.status != "OK"]
    if blocking and not args.no_fail:
        print("\nLocal toolchain is missing required validation/lint dependencies.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
