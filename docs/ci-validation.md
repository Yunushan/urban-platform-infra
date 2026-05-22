# CI Validation

The CI workflow is intentionally split into small gates so failures point to a specific class of problem.

## Contract Gate

Run the contract gate before the broader repository validator:

```bash
make ci-contract
```

The gate is implemented in `scripts/tools/validate_ci_contract.py` and uses only the Python standard library. It validates public workflow structure, not private infrastructure:

- GitHub static matrix keeps the legacy Python 3.11 / ansible-core 2.14 lane.
- GitHub static matrix keeps modern Python 3.12, 3.13, and 3.14 / ansible-core 2.20 lanes.
- GitHub validate matrix keeps Python 3.11 through 3.14 coverage.
- Pip cache keys follow each matrix requirements file.
- Ansible collection installs follow each matrix collection file.
- GitHub Actions refs are version-pinned and never use `main` or `master`.
- Dependency review stays optional unless the repository enables Dependency Graph.
- GitLab validation uses pinned requirements rather than ad hoc package installs.

The optional report is written to `reports/ci-contract.md` and is safe to share.

## GitHub Jobs

- `static`: yamllint, Ansible syntax checks, and shellcheck across the legacy and modern Ansible lanes.
- `dependency-review`: pull-request dependency review when repository settings allow it.
- `validate`: CI contract, private-data audit, repository validation, and image-policy validation across Python 3.11 through 3.14.
- `render`: Helm lint, Helm template rendering, rendered-manifest policy checks, and rendered manifest artifact upload.
- `security`: Trivy filesystem scan with non-blocking findings by default.

## Local Equivalent

Use the same order locally:

```bash
make setup-local
make doctor-local
make ci-contract
make private-data-audit
make validate
make lint
```

`make validate` also runs the CI contract gate before the repository validator. `make lint` uses the repository virtualenv tools when they exist, so local results match CI more closely.

## When A Lane Fails

- If `ci-contract` fails, fix workflow structure, lane pins, dependency cache settings, or action refs first.
- If `static` fails, fix YAML formatting, Ansible syntax, or shell portability.
- If `private-data-audit` fails, remove the private material from the working tree and rotate exposed values if they were real.
- If `validate` fails, read the exact token message from `scripts/validate.py`; those messages are intended to name the missing repository contract.
- If `render` fails, run `helm lint` and `helm template` with the same chart and values file.
- If `security` reports findings, triage the Trivy output and decide whether to fix, suppress with documented rationale, or keep as advisory.
