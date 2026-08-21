# Load Testing

The repository provides an optional, protected load-testing capability. It is never executed by push or pull-request CI. Normal CI only validates the repository and generates a no-traffic plan.

## Runner Selection

`k6` is the default runner. The ten supported runner options are registered in [`config/load-test.yaml`](../config/load-test.yaml):

| Runner | Best fit | Execution contract |
|---|---|---|
| `k6` | HTTP/API, WebSocket, SignalR, and threshold gates | Built-in default adapter |
| `locust` | Python user journeys and distributed tests | Optional external tool |
| `jmeter` | Protocol-rich enterprise plans | Optional external tool |
| `gatling` | Code-defined high-throughput HTTP tests | Optional external tool |
| `artillery` | Node.js/TypeScript API and WebSocket scenarios | Optional external tool |
| `fortio` | Lightweight HTTP/gRPC checks near Kubernetes | Optional external tool |
| `vegeta` | Constant-rate HTTP benchmarking | Optional external tool |
| `wrk2` | High-throughput constant-rate HTTP benchmarks | Optional external tool |
| `kafka` | Apache Kafka producer/consumer throughput tests | Optional external tool |
| `pgbench` | PostgreSQL and TimescaleDB transaction benchmarks | Optional external tool |

The native Python runner remains an explicit low-dependency fallback with `LOAD_TEST_RUNNER=python`. External runners remain optional host tools and are not added to CI images or deployment prerequisites.

List the available runners from the operator host:

```bash
make load-test-runners
```

## Profiles

Profiles are in [`config/load-test.yaml`](../config/load-test.yaml):

- `smoke`: short, low-rate endpoint validation.
- `baseline`: representative sustained traffic for capacity evidence.
- `soak`: long-running stability testing.
- `spike`: short burst testing during an approved rollback window.
- `stress`: an explicitly approved saturation profile.

The runner records aggregate HTTP status and latency, and when Kubernetes access permits it also samples pod CPU, memory, and Linux cgroup-v2 I/O counters. I/O cost is reported as total and per-request bytes and operations. It is not a cloud billing estimate.

## Plan First

Generate a public-safe plan without sending traffic. Private target URLs should be supplied only on the operator host or through protected workflow secrets:

```bash
make load-test-plan \
  LOAD_TEST_RUNNER=k6 \
  LOAD_TEST_PROFILE=smoke \
  LOAD_TEST_TARGET_URL=https://<private-host>/healthz \
  LOAD_TEST_NAMESPACE=<namespace> \
  LOAD_TEST_SELECTOR='app.kubernetes.io/name=<service>' \
  IMPORT_REDACT=true
```

To plan another registered runner:

```bash
make load-test-plan LOAD_TEST_RUNNER=pgbench LOAD_TEST_PROFILE=baseline IMPORT_REDACT=true
```

Plans do not contact the target. For external runners, the plan records the selected tool and its execution requirements; the native tool must be installed and run from an approved staging runner with its own protocol-specific configuration.

Make variables left empty inherit the selected profile. This keeps the profile's duration, rate, concurrency, and request cap intact.

## Execute

After reviewing the plan, execute the default k6 profile manually from a protected staging or operator host:

```bash
make load-test \
  LOAD_TEST_RUNNER=k6 \
  LOAD_TEST_EXECUTE=true \
  LOAD_TEST_CONFIRM=true \
  LOAD_TEST_ENV=staging \
  LOAD_TEST_PROFILE=baseline \
  LOAD_TEST_TARGET_URL=https://<private-host>/healthz \
  LOAD_TEST_NAMESPACE=<namespace> \
  LOAD_TEST_SELECTOR='app.kubernetes.io/name=<service>' \
  LOAD_TEST_MAX_REQUESTS=10000 \
  IMPORT_REDACT=true
```

The Make target requires both `LOAD_TEST_EXECUTE=true` and `LOAD_TEST_CONFIRM=true`. `LOAD_TEST_ENV` identifies the approved environment. The bounded k6 adapter applies HTTP error, expected-status, and p95 latency thresholds and writes only aggregate evidence to the report.

## Protected GitHub Workflow

The [`load-test.yml`](../.github/workflows/load-test.yml) workflow is `workflow_dispatch` only. It defaults to plan mode and k6. Execute mode requires the protected `staging-load-test` environment, a self-hosted runner labeled `urban-platform-load-test`, the `LOAD_TEST_TARGET_URL` secret, and explicit confirmation. It is not referenced by push or pull-request CI.

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

## Safety Rules

- Never place credentials, cookies, authorization headers, private hostnames, or response bodies in Git or reports.
- Use synthetic data and non-destructive endpoints. The built-in runner accepts only `GET`, `HEAD`, and `OPTIONS`.
- Run baseline, soak, spike, and stress profiles only against an approved staging environment or maintenance window.
- Use Kafka-native performance tools for broker throughput and `pgbench` against a disposable or isolated database.
- Missing Kubernetes CPU, memory, or I/O metrics is an evidence gap, not a capacity pass.
