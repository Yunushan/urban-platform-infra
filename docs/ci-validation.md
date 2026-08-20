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
- GitHub Actions refs are pinned to reviewed commit SHAs and never use `main` or `master`.
- Dependency review is required on pull requests.
- GitLab validation uses pinned requirements rather than ad hoc package installs.
- Production intent is validated against the public production overlay before rendering.

The optional report is written to `reports/ci-contract.md` and is safe to share.

## GitHub Jobs

- `static`: yamllint, Ansible syntax checks, and shellcheck across the legacy and modern Ansible lanes.
- `dependency-review`: required pull-request dependency review.
- `validate`: CI contract, private-data audit, repository validation, and image-policy validation across Python 3.11 through 3.14.
- `render`: Helm lint, Helm template rendering, rendered-manifest policy checks, and rendered manifest artifact upload.
- `production-contract`: production overlay validation, strict production rendering, HA/durability policy checks, and the repository readiness score.
- `security`: Trivy filesystem scan that fails on unresolved HIGH or CRITICAL findings.
- `version-update-request`: manually dispatched, read-only version request evidence; it has no repository write or cluster deployment permission.

## Local Equivalent

Use the same order locally:

```bash
make setup-local
make doctor-local
make ci-contract
make private-data-audit
make validate
make lint
python3 scripts/validate_production_profile.py
python3 scripts/production_readiness_score.py
helm template urban-platform-infra helm/urban-platform-infra \
  --namespace urban-platform \
  -f helm/urban-platform-infra/values.yaml \
  -f helm/urban-platform-infra/values-production.yaml
```

`make validate` also runs the CI contract gate before the repository validator. `make lint` uses the repository virtualenv tools when they exist, so local results match CI more closely.

The version lifecycle gate is intentionally fail-closed: `autoPatch`,
`autoMinor`, and `autoMajor` must remain false. Review
[`version-management.md`](version-management.md) for the manual request and
approval workflow.

## When A Lane Fails

- If `ci-contract` fails, fix workflow structure, lane pins, dependency cache settings, or action refs first.
- If `static` fails, fix YAML formatting, Ansible syntax, or shell portability.
- If `private-data-audit` fails, remove the private material from the working tree and rotate exposed values if they were real.
- If `validate` fails, read the exact token message from `scripts/validate.py`; those messages are intended to name the missing repository contract.
- If `render` fails, run `helm lint` and `helm template` with the same chart and values file.
- If `security` reports findings, fix them or document a narrowly scoped, time-bound exception before merging; unresolved HIGH or CRITICAL findings fail the gate.

## Production Contract

`helm/urban-platform-infra/values-production.yaml` is a public-safe baseline
that expresses the required production controls without customer addresses,
credentials, or private registry names. The production contract validator
checks HA replicas, restricted Pod Security, RuntimeDefault seccomp, default
deny networking, external secret management, backup and restore drills,
Strimzi-managed Apache Kafka, Redis Sentinel, smoke probes, and release
evidence requirements. Real production deployments must layer a private
environment overlay containing promoted image digests, real StorageClasses,
trusted issuer references, registry credentials, and tested backup targets.
The private operator/release-runner gate is documented in
[`production-readiness.md`](production-readiness.md); public CI validates its
code and contract but does not receive the private manifest or kubeconfig.
