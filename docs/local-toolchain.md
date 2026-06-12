# Local Toolchain

This repository now has a small, public-safe local setup and doctor workflow for operator laptops, CI runners, and lab machines. It does not print private inventories, node names, registry names, kubeconfigs, or secrets.

## Recommended First Run

```bash
make operator-ready
```

`make operator-ready` runs the local setup, local doctor, CI contract check,
private-data audit, capacity preflight, repository validation, and lint in
order.

`make setup-local` creates or updates `.venv` and installs the pinned Python requirements for the current interpreter. Python 3.11 uses the legacy CI pins, while Python 3.12 and newer use the modern pins.

`make doctor-local` checks the workstation for the tools used by the static gates and operator workflows. The report is written to `reports/local-doctor.md`, which is safe to share because it contains only tool names, versions, and generic remediation guidance.

## Windows Notes

Native Windows is useful for repository inspection, documentation, local Python validation, and planning reports. Cluster mutation should run from WSL or a Linux operator host because Ansible, SSH, RKE2, Helm, kubectl, and container tooling behave most predictably from a Linux control node.

If `make` or `python3` is not available yet, install the Windows prerequisites first:

```powershell
powershell -ExecutionPolicy Bypass -File platform/windows/install-prereqs.ps1
```

If your Windows Python launcher is `py`, you can bootstrap directly:

```powershell
py -3 scripts/tools/setup_local.py
.\.venv\Scripts\python.exe scripts\tools\doctor_local.py --report reports/local-doctor.md
```

## Tooling Expectations

Required for validation and lint:

- Python 3.11 or newer
- PyYAML, yamllint, and Ansible Python packages from the pinned requirements
- Git, GNU Make, Bash, yamllint, and ShellCheck

Required for cluster deployment or project import execution:

- Ansible CLI tools
- Helm `v4.2.1` by default through `scripts/tools/install-helm.sh`
- Helmfile `v1.5.3` by default through `scripts/tools/install-helmfile.sh`
- kubectl with a reachable kubeconfig
- Docker or Podman for image build, tag, save, push, or preload workflows
- OpenSSH client and `scp` for RKE2 image preload and kubeconfig repair
- OpenSSL for lab TLS fallback

The doctor marks validation/lint prerequisites as blocking. Cluster tools are warnings until you run mutating targets such as `make bootstrap`, `make install-cluster`, `make deploy`, or `make import-auto`.
