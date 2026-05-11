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
- `validate`: repository structure, YAML parsing, sanitized examples, and workflow-generation checks.
- `render`: Helm lint, manifest rendering, policy checks, and rendered manifest upload.
- `security`: Trivy filesystem scan.

## Enforcement model

The current baseline is intentionally strict for syntax, rendering, repository hygiene, high-confidence secret/disclosure checks, release evidence, image mutability, and SLO/runbook coverage. Runtime-hardening policies such as mandatory read-only root filesystems and signed image admission should become blocking gates as the chart is hardened in later articles.
