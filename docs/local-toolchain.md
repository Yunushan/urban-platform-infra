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

For the complete execution-scope contract, run `make tool-inventory TOOL_INVENTORY_SCOPE=validation`, `deployment`, `import`, or `load-test`. See [`tool-inventory.md`](tool-inventory.md) for the mandatory/optional distinction and the Docker/Podman and native load-runner alternatives.

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

Required for the private operational production gate:

- Cosign `3.1.3` or newer
- Git, Python, kubectl, and authenticated cluster access

The Helm and Helmfile bootstrap scripts verify their downloaded archives
against checksums pinned from the official releases before extraction. The
local-path installer downloads an immutable upstream commit and verifies its
pinned manifest digest before applying it. A version override fails closed
unless its corresponding `HELM_ARCHIVE_SHA256`, `HELMFILE_ARCHIVE_SHA256`, or
`LOCAL_PATH_PROVISIONER_MANIFEST_SHA256` is supplied from a trusted release.

For bounded capacity evidence, k6 is the default optional runner and the built-in Python load runner is the explicit fallback. Locust, JMeter, Gatling, Artillery, Fortio, Vegeta, wrk2, Kafka performance tools, and `pgbench` are optional protocol-specific tools. Kubernetes access, `kubectl`, and cgroup-v2 visibility are optional measurements: HTTP results remain available when CPU, memory, or I/O telemetry cannot be sampled. See [`load-testing.md`](load-testing.md).

The doctor marks validation/lint prerequisites as blocking. Cluster tools are warnings until you run mutating targets such as `make bootstrap`, `make install-cluster`, `make deploy`, or `make import-auto`.
