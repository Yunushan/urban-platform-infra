# Quality Gates

This repository uses layered checks so infrastructure changes fail early, before a cluster is touched.

## Local developer gates

Run these before opening a pull request:

```bash
pip install -r requirements-ci.txt
make lint
make validate
make bootstrap-check ENV=prod ENGINE=rke2
make install-cluster-check ENV=prod ENGINE=rke2
make deploy-dry-run
make policy
```

For the modern control-node lane, use Python 3.12, 3.13, or 3.14 and install the modern pins:

```bash
pip install -r requirements-ci-modern.txt
make ansible-collections ANSIBLE_COLLECTION_REQUIREMENTS=ansible/requirements-modern.yml
```

The local gates cover:

- YAML style and parse checks for repository configuration.
- Ansible preflight and check-mode dry runs for bootstrap changes.
- Shell script linting for portable helper scripts.
- Repository structure validation and sanitized example-data checks.
- Secret hygiene checks for ignored sensitive directories, plain Kubernetes Secret manifests, and decrypted secret artifacts.
- Release integrity checks for checksum/SBOM generation, GitHub artifact attestations, and non-floating action refs.
- Image governance checks for explicit tags or digests, blocked mutable tags, and approved runtime-image references.
- Observability checks for SLO contract files, runbooks, and PrometheusRule alert coverage.
- Helm linting and manifest rendering.
- Rendered-manifest policy checks.

## CI gates

The GitHub Actions workflow separates concerns into these jobs:

- `static`: yamllint, Ansible syntax checks, and shellcheck.
- `static (ansible-2.20-py312/py313/py314)`: modern Ansible syntax checks through Python 3.14.
- `validate`: repository structure, YAML parsing, sanitized examples, and workflow-generation checks on Python 3.11 through 3.14.
- `render`: Helm lint, manifest rendering, policy checks, and rendered manifest upload.
- `security`: Trivy filesystem scan.

## Enforcement model

The current baseline is intentionally strict for syntax, rendering, repository hygiene, high-confidence secret/disclosure checks, release evidence, image mutability, and SLO/runbook coverage. Runtime-hardening policies such as mandatory read-only root filesystems and signed image admission should become blocking gates as the chart is hardened in later articles.
