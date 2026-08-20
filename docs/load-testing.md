# Load Testing

The repository includes a bounded, dependency-light HTTP load-test runner. It is intended for deployment evidence and capacity decisions, not uncontrolled traffic generation.

## Profiles

Profiles are in [`config/load-test.yaml`](../config/load-test.yaml):

- `smoke`: short, low-rate endpoint validation.
- `baseline`: representative sustained traffic for capacity evidence.
- `stress`: an explicitly approved saturation profile.

The runner records aggregate HTTP status and latency, and when Kubernetes access permits it also samples pod CPU, memory, and Linux cgroup-v2 I/O counters. I/O cost is reported as total and per-request bytes and operations. It is not a cloud billing estimate.

## Plan First

Generate a public-safe plan without sending traffic:

```bash
make load-test-plan \
  LOAD_TEST_PROFILE=smoke \
  LOAD_TEST_TARGET_URL=https://<private-host>/healthz \
  LOAD_TEST_NAMESPACE=<namespace> \
  LOAD_TEST_SELECTOR='app.kubernetes.io/name=<service>' \
  IMPORT_REDACT=true
```

Make variables left empty inherit the selected profile. This keeps the profile's duration, rate, concurrency, and request cap intact.

## Execute

After reviewing the plan and approving the target environment, execute a bounded test:

```bash
make load-test \
  LOAD_TEST_EXECUTE=true \
  LOAD_TEST_PROFILE=baseline \
  LOAD_TEST_TARGET_URL=https://<private-host>/healthz \
  LOAD_TEST_NAMESPACE=<namespace> \
  LOAD_TEST_SELECTOR='app.kubernetes.io/name=<service>' \
  LOAD_TEST_MAX_REQUESTS=10000 \
  IMPORT_REDACT=true
```

Only `GET`, `HEAD`, and `OPTIONS` are accepted by the native runner. It never prints response bodies, cookies, authorization headers, or supplied host values when redaction is enabled. The Make target refuses to execute unless `LOAD_TEST_EXECUTE=true` is set explicitly.

## Resource And I/O Budgets

Kubernetes CPU, memory, and ephemeral-storage requests/limits are configured through `global.resourceDefaults` and service-specific `resources` blocks. The Make deployment variables are:

```text
DEPLOY_CPU_REQUEST
DEPLOY_MEMORY_REQUEST
DEPLOY_CPU_LIMIT
DEPLOY_MEMORY_LIMIT
DEPLOY_EPHEMERAL_STORAGE_REQUEST
DEPLOY_EPHEMERAL_STORAGE_LIMIT
```

I/O budgets are represented as annotations and measured as evidence because standard Kubernetes does not enforce arbitrary bytes-per-second or IOPS limits. The related variables are `DEPLOY_IO_READ_BPS`, `DEPLOY_IO_WRITE_BPS`, `DEPLOY_IO_READ_IOPS`, and `DEPLOY_IO_WRITE_IOPS`. Use a storage class or node-level device policy when hard I/O enforcement is required.

The load-test overrides `LOAD_TEST_CPU_LIMIT`, `LOAD_TEST_MEMORY_LIMIT`, `LOAD_TEST_IO_READ_BPS`, `LOAD_TEST_IO_WRITE_BPS`, `LOAD_TEST_IO_READ_IOPS`, and `LOAD_TEST_IO_WRITE_IOPS` document the expected test budget in the evidence report.

## Interpreting Missing Metrics

Missing CPU or memory data normally means Metrics Server or Prometheus Adapter is unavailable, or the selector matches no pods. Missing I/O data normally means the selected image does not expose `/sys/fs/cgroup/io.stat`, the node is not using cgroup v2, or pod exec permissions are unavailable. The test still records HTTP results, but production capacity decisions should not treat incomplete evidence as a pass.

Use `k6`, Vegeta, or hey only when the team standardizes on one of them and the tool is approved. The native runner remains the default so planning and basic evidence work on a minimal operator host.
