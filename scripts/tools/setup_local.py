#!/usr/bin/env python3
"""Create a repository virtualenv and install pinned local validation deps."""

from __future__ import annotations

import argparse
import subprocess
import sys
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def venv_python(venv_path: Path) -> Path:
    if sys.platform == "win32":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python3"


def choose_requirements(python_path: Path) -> Path:
    code = "import sys; print('requirements-ci-modern.txt' if sys.version_info >= (3, 12) else 'requirements-ci.txt')"
    completed = subprocess.run(
        [str(python_path), "-c", code],
        text=True,
        capture_output=True,
        check=True,
    )
    return ROOT / completed.stdout.strip()


def run(command: list[str]) -> None:
    print("+ " + " ".join(command))
    subprocess.run(command, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare the local Python toolchain for this repository.")
    parser.add_argument("--venv", default=".venv", help="Virtualenv path to create or update.")
    parser.add_argument("--requirements", default="", help="Override requirements file.")
    parser.add_argument("--upgrade-pip", action="store_true", help="Upgrade pip before installing requirements.")
    args = parser.parse_args(argv)

    if sys.version_info < (3, 11):
        print("Python 3.11 or newer is required for the local operator toolchain.", file=sys.stderr)
        return 2

    venv_path = Path(args.venv)
    if not venv_path.is_absolute():
        venv_path = ROOT / venv_path

    python_path = venv_python(venv_path)
    if not python_path.exists():
        print(f"Creating virtualenv: {venv_path}")
        venv.EnvBuilder(with_pip=True).create(venv_path)
    else:
        print(f"Using existing virtualenv: {venv_path}")

    requirements = Path(args.requirements) if args.requirements else choose_requirements(python_path)
    if not requirements.is_absolute():
        requirements = ROOT / requirements
    if not requirements.exists():
        print(f"Missing requirements file: {requirements}", file=sys.stderr)
        return 2

    if args.upgrade_pip:
        run([str(python_path), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(python_path), "-m", "pip", "install", "-r", str(requirements)])

    print("")
    print(f"Local Python toolchain ready: {python_path}")
    print("Next: make doctor-local")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
