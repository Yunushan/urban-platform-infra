#!/usr/bin/env python3
"""Run a bounded HTTP load test and collect public-safe resource/I/O evidence."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import shutil
import statistics
import subprocess
import threading
import tempfile
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
FALLBACK_RUNNER = "python"


def resolve_runner(config: dict[str, Any], requested: str) -> tuple[str, dict[str, Any]]:
    runners = config.get("runners", {})
    if not isinstance(runners, dict):
        raise SystemExit("Load-test configuration must define a runners mapping.")
    default_runner = str(config.get("defaultRunner", "k6")).strip() or "k6"
    selected = (requested or "auto").strip().lower()
    if selected in {"", "auto"}:
        selected = default_runner
    if selected == FALLBACK_RUNNER:
        return selected, {
            "displayName": "Native Python runner",
            "kind": "http",
            "tool": "python",
            "enabled": True,
            "execution": "native",
            "description": "Dependency-light HTTP fallback with Kubernetes resource sampling.",
        }
    runner = runners.get(selected)
    if not isinstance(runner, dict):
        available = ", ".join(sorted([str(name) for name in runners] + [FALLBACK_RUNNER]))
        raise SystemExit(f"Unknown load-test runner {selected!r}; choose one of: {available}.")
    return selected, runner


def load_yaml(path: Path) -> dict[str, Any]:
    if importlib.util.find_spec("yaml") is None:
        raise SystemExit("PyYAML is required to read the load-test profile.")
    import yaml

    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise SystemExit(f"Load-test configuration must be a mapping: {path}")
    return value


def positive_int(value: str, name: str, maximum: int) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer") from exc
    if number < 1 or number > maximum:
        raise SystemExit(f"{name} must be between 1 and {maximum}")
    return number


def nonnegative_float(value: str, name: str, maximum: float) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be numeric") from exc
    if number < 0 or number > maximum:
        raise SystemExit(f"{name} must be between 0 and {maximum}")
    return number


def parse_cpu_millicores(value: str | int | float | None) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("m"):
            return float(text[:-1])
        if text.endswith("n"):
            return float(text[:-1]) / 1_000_000
        return float(text) * 1000
    except ValueError:
        return None


def parse_memory_mi(value: str | int | float | None) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    units = {
        "Ki": 1 / 1024,
        "Mi": 1,
        "Gi": 1024,
        "Ti": 1024 * 1024,
        "K": 1 / 1000,
        "M": 1,
        "G": 1000,
        "T": 1_000_000,
    }
    for suffix, multiplier in units.items():
        if text.endswith(suffix):
            try:
                return float(text[: -len(suffix)]) * multiplier
            except ValueError:
                return None
    try:
        return float(text) / (1024 * 1024)
    except ValueError:
        return None


def parse_counter(value: str | int | float | None) -> int | None:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return None


def merge_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    defaults = config.get("defaults", {}) if isinstance(config.get("defaults"), dict) else {}
    profiles = config.get("profiles", {}) if isinstance(config.get("profiles"), dict) else {}
    profile = profiles.get(profile_name, {})
    if not isinstance(profile, dict):
        raise SystemExit(f"Unknown load-test profile: {profile_name}")
    merged = dict(defaults)
    for key, value in profile.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def build_target(base: str, path: str) -> str:
    if not base:
        raise SystemExit("A target URL is required for an executed load test.")
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return urljoin(base.rstrip("/") + "/", path.lstrip("/"))


def display_target(url: str, redact: bool) -> str:
    parsed = urlsplit(url)
    if not redact:
        return url
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme, "<target-host>", path, "", ""))


@dataclass
class RequestResult:
    status: int | None
    latency_ms: float
    error: str = ""


def request_once(url: str, method: str, timeout: float, headers: dict[str, str]) -> RequestResult:
    started = time.perf_counter()
    try:
        request = Request(url, method=method, headers=headers)
        with urlopen(request, timeout=timeout) as response:
            response.read(1)
            status = int(response.status)
        return RequestResult(status, (time.perf_counter() - started) * 1000)
    except HTTPError as exc:
        return RequestResult(int(exc.code), (time.perf_counter() - started) * 1000, f"HTTP {exc.code}")
    except (URLError, OSError, TimeoutError) as exc:
        return RequestResult(None, (time.perf_counter() - started) * 1000, type(exc).__name__)


def kubectl_run(arguments: list[str], timeout: float = 15) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            ["kubectl", *arguments],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return completed.returncode, completed.stdout.strip()


def parse_io_stat(text: str) -> dict[str, int]:
    totals = {"read_bytes": 0, "write_bytes": 0, "read_ops": 0, "write_ops": 0}
    for line in text.splitlines():
        for key, output_key in (
            ("rbytes", "read_bytes"),
            ("wbytes", "write_bytes"),
            ("rios", "read_ops"),
            ("wios", "write_ops"),
            ("read_bytes", "read_bytes"),
            ("write_bytes", "write_bytes"),
            ("read_ops", "read_ops"),
            ("write_ops", "write_ops"),
        ):
            marker = key + "="
            if marker not in line:
                continue
            raw = line.split(marker, 1)[1].split()[0]
            number = parse_counter(raw)
            if number is not None:
                totals[output_key] += number
    return totals


def parse_top(text: str) -> tuple[float | None, float | None]:
    cpu = 0.0
    memory = 0.0
    found = False
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        cpu_value = parse_cpu_millicores(fields[-2])
        memory_value = parse_memory_mi(fields[-1])
        if cpu_value is None or memory_value is None:
            continue
        cpu += cpu_value
        memory += memory_value
        found = True
    return (cpu if found else None, memory if found else None)


class KubernetesSampler:
    def __init__(self, namespace: str, selector: str, interval: float, io_enabled: bool) -> None:
        self.namespace = namespace
        self.selector = selector
        self.interval = interval
        self.io_enabled = io_enabled
        self.samples: list[dict[str, Any]] = []
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.available = bool(shutil.which("kubectl"))

    def pod_names(self) -> list[str]:
        if not self.available or not self.namespace or not self.selector:
            return []
        rc, output = kubectl_run(["-n", self.namespace, "get", "pods", "-l", self.selector, "-o", "json"])
        if rc != 0:
            return []
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return []
        return [str(item.get("metadata", {}).get("name")) for item in data.get("items", []) if item.get("metadata", {}).get("name")][:20]

    def snapshot(self) -> dict[str, Any]:
        sample: dict[str, Any] = {"time": time.time(), "cpu_m": None, "memory_mi": None}
        if not self.available:
            sample["io"] = None
            return sample
        rc, top = kubectl_run(["-n", self.namespace, "top", "pods", "-l", self.selector, "--no-headers"])
        if rc == 0:
            sample["cpu_m"], sample["memory_mi"] = parse_top(top)
        io_total = {"read_bytes": 0, "write_bytes": 0, "read_ops": 0, "write_ops": 0}
        io_seen = False
        if self.io_enabled:
            for pod in self.pod_names():
                rc, output = kubectl_run(
                    ["-n", self.namespace, "exec", pod, "--", "sh", "-c", "cat /sys/fs/cgroup/io.stat 2>/dev/null || true"],
                    timeout=10,
                )
                if rc != 0 or not output:
                    continue
                counters = parse_io_stat(output)
                if any(counters.values()):
                    io_seen = True
                    for key in io_total:
                        io_total[key] += counters[key]
        sample["io"] = io_total if io_seen else None
        return sample

    def _run(self) -> None:
        while not self.stop_event.is_set():
            self.samples.append(self.snapshot())
            self.stop_event.wait(self.interval)

    def start(self) -> None:
        if not self.available:
            return
        self.thread = threading.Thread(target=self._run, name="load-test-resource-sampler", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.thread is None:
            return
        self.stop_event.set()
        self.thread.join(timeout=max(self.interval + 2, 5))
        self.samples.append(self.snapshot())


def run_load(
    url: str,
    method: str,
    duration: int,
    concurrency: int,
    rate: float,
    max_requests: int,
    timeout: float,
    expected_status: set[int],
    headers: dict[str, str],
) -> tuple[list[RequestResult], float]:
    results: list[RequestResult] = []
    lock = threading.Lock()
    started = time.perf_counter()

    def execute() -> None:
        result = request_once(url, method, timeout, headers)
        with lock:
            results.append(result)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = set()
        end_time = time.monotonic() + duration
        if rate > 0:
            target_count = min(max_requests, max(1, math.ceil(rate * duration)))
            next_due = time.monotonic()
            submitted = 0
            while submitted < target_count and time.monotonic() < end_time:
                now = time.monotonic()
                if now < next_due:
                    time.sleep(min(next_due - now, 0.05))
                    continue
                while len(futures) >= concurrency:
                    done, futures = wait(futures, return_when=FIRST_COMPLETED)
                    for future in done:
                        future.result()
                futures.add(executor.submit(execute))
                submitted += 1
                next_due += 1 / rate
        else:
            submitted_count = 0

            def worker() -> None:
                nonlocal submitted_count
                while time.monotonic() < end_time:
                    with lock:
                        if submitted_count >= max_requests:
                            return
                        submitted_count += 1
                    execute()

            futures = {executor.submit(worker) for _ in range(concurrency)}
        for future in futures:
            future.result()
    elapsed = max(time.perf_counter() - started, 0.001)
    return results, elapsed


def metric_summary(results: list[RequestResult], elapsed: float, expected_status: set[int]) -> dict[str, Any]:
    latencies = sorted(result.latency_ms for result in results)
    counts: dict[str, int] = {}
    for result in results:
        key = str(result.status) if result.status is not None else "error"
        counts[key] = counts.get(key, 0) + 1

    def percentile(fraction: float) -> float:
        if not latencies:
            return 0.0
        index = min(len(latencies) - 1, max(0, math.ceil(len(latencies) * fraction) - 1))
        return latencies[index]

    failed = [result for result in results if result.status not in expected_status]
    return {
        "requests": len(results),
        "errors": len(failed),
        "errorRate": (len(failed) / len(results)) if results else 1.0,
        "rps": len(results) / elapsed,
        "latencyMs": {
            "min": min(latencies) if latencies else 0.0,
            "avg": statistics.mean(latencies) if latencies else 0.0,
            "p50": percentile(0.50),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
            "max": max(latencies) if latencies else 0.0,
        },
        "statusCounts": counts,
        "errorSamples": sorted({result.error for result in failed if result.error})[:10],
    }


def io_summary(samples: list[dict[str, Any]], requests: int, elapsed: float) -> dict[str, Any]:
    available = [sample["io"] for sample in samples if isinstance(sample.get("io"), dict)]
    if len(available) < 2:
        return {"available": False, "reason": "cgroup I/O counters were unavailable or not exposed by the selected pods."}
    first = available[0]
    last = available[-1]
    delta = {key: max(0, int(last.get(key, 0)) - int(first.get(key, 0))) for key in first}
    total_bytes = delta["read_bytes"] + delta["write_bytes"]
    total_ops = delta["read_ops"] + delta["write_ops"]
    return {
        "available": True,
        **delta,
        "elapsedSeconds": elapsed,
        "readBytesPerSecond": delta["read_bytes"] / elapsed,
        "writeBytesPerSecond": delta["write_bytes"] / elapsed,
        "bytesPerRequest": total_bytes / requests if requests else 0,
        "opsPerRequest": total_ops / requests if requests else 0,
        "ioCostBytes": total_bytes,
        "ioCostOps": total_ops,
    }


def resource_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    cpu = [float(item["cpu_m"]) for item in samples if item.get("cpu_m") is not None]
    memory = [float(item["memory_mi"]) for item in samples if item.get("memory_mi") is not None]
    return {
        "available": bool(cpu or memory),
        "cpu": {"averageMillicores": statistics.mean(cpu), "maxMillicores": max(cpu)} if cpu else {},
        "memory": {"averageMi": statistics.mean(memory), "maxMi": max(memory)} if memory else {},
    }


def format_number(value: Any, digits: int = 2) -> str:
    if isinstance(value, (float, int)):
        return f"{value:.{digits}f}"
    return str(value)


def k6_script(profile: dict[str, Any], target: str, expected_status: set[int]) -> str:
    duration = int(profile["durationSeconds"])
    concurrency = int(profile["concurrency"])
    rate = float(profile["ratePerSecond"])
    max_requests = int(profile["maxRequests"])
    method = json.dumps(str(profile["method"]).upper())
    target_literal = json.dumps(target)
    expected_literal = json.dumps(sorted(expected_status))
    thresholds = profile.get("thresholds", {}) if isinstance(profile.get("thresholds"), dict) else {}
    error_rate = float(thresholds.get("errorRate", 0.01))
    p95_ms = int(thresholds.get("p95Ms", 1000))

    if rate > 0:
        effective_rate = min(rate, max_requests / max(duration, 1))
        scenario = {
            "executor": "constant-arrival-rate",
            "rate": max(1, math.floor(effective_rate)),
            "timeUnit": "1s",
            "duration": f"{duration}s",
            "preAllocatedVUs": max(1, concurrency),
            "maxVUs": max(1, concurrency),
            "gracefulStop": "0s",
        }
    else:
        scenario = {
            "executor": "constant-vus",
            "vus": max(1, concurrency),
            "duration": f"{duration}s",
            "gracefulStop": "0s",
        }
    scenario_literal = json.dumps(scenario, indent=2)
    return f"""import http from 'k6/http';
import {{ check }} from 'k6';

const target = {target_literal};
const expectedStatuses = new Set({expected_literal});

export const options = {{
  scenarios: {{
    default: {scenario_literal}
  }},
  thresholds: {{
    http_req_failed: ['rate<{error_rate}'],
    http_req_duration: ['p(95)<{p95_ms}'],
    checks: ['rate>0.99'],
  }},
}};

export default function () {{
  const response = http.request({method}, target, null, {{ tags: {{ component: 'urban-platform' }} }});
  check(response, {{ 'expected status': (value) => expectedStatuses.has(value.status) }});
}}
"""


def empty_k6_summary() -> dict[str, Any]:
    return {
        "requests": 0,
        "errors": 1,
        "errorRate": 1.0,
        "rps": 0.0,
        "latencyMs": {"min": 0.0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0},
        "statusCounts": {},
        "errorSamples": ["k6 did not produce a summary"],
    }


def k6_metric(summary: dict[str, Any], metric_name: str, value_name: str, default: float = 0.0) -> float:
    metrics = summary.get("metrics", {})
    metric = metrics.get(metric_name, {}) if isinstance(metrics, dict) else {}
    values = metric.get("values", {}) if isinstance(metric, dict) else {}
    try:
        return float(values.get(value_name, default))
    except (TypeError, ValueError):
        return default


def parse_k6_summary(summary: dict[str, Any]) -> dict[str, Any]:
    requests = int(k6_metric(summary, "http_reqs", "count", 0))
    http_failed_rate = k6_metric(summary, "http_req_failed", "rate", 0.0)
    checks_rate = k6_metric(summary, "checks", "rate", 1.0)
    error_rate = max(http_failed_rate, 1.0 - checks_rate)
    errors = min(requests, max(0, math.ceil(requests * error_rate)))
    return {
        "requests": requests,
        "errors": errors,
        "errorRate": error_rate,
        "rps": k6_metric(summary, "http_reqs", "rate", 0.0),
        "latencyMs": {
            "min": k6_metric(summary, "http_req_duration", "min", 0.0),
            "avg": k6_metric(summary, "http_req_duration", "avg", 0.0),
            "p50": k6_metric(summary, "http_req_duration", "med", 0.0),
            "p95": k6_metric(summary, "http_req_duration", "p(95)", 0.0),
            "p99": k6_metric(summary, "http_req_duration", "p(99)", 0.0),
            "max": k6_metric(summary, "http_req_duration", "max", 0.0),
        },
        "statusCounts": {"external-runner": requests},
        "errorSamples": ["k6 threshold failure"] if errors else [],
    }


def run_k6(
    profile: dict[str, Any],
    target: str,
    expected_status: set[int],
    command: str,
) -> tuple[dict[str, Any], list[str], bool]:
    executable = shutil.which(command)
    if not executable:
        raise SystemExit(f"Selected load-test runner requires `{command}` on PATH. Install it or use LOAD_TEST_RUNNER=python.")
    findings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="urban-platform-k6-") as temporary_dir:
        working_dir = Path(temporary_dir)
        script_path = working_dir / "load-test.js"
        summary_path = working_dir / "summary.json"
        script_path.write_text(k6_script(profile, target, expected_status), encoding="utf-8")
        timeout = int(profile["durationSeconds"]) + max(60, int(profile["timeoutSeconds"]))
        try:
            completed = subprocess.run(
                [executable, "run", "--summary-export", str(summary_path), str(script_path)],
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            findings.append(f"{command} exceeded the bounded execution timeout of {timeout}s.")
            return empty_k6_summary(), findings, True
        try:
            raw_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw_summary = {}
        summary = parse_k6_summary(raw_summary) if raw_summary else empty_k6_summary()
        if completed.returncode != 0:
            findings.append(f"{command} exited with status {completed.returncode}; inspect the protected runner logs.")
        return summary, findings, completed.returncode != 0 or bool(summary["errors"])


def render_report(
    *,
    profile_name: str,
    runner_name: str,
    runner: dict[str, Any],
    profile: dict[str, Any],
    target: str,
    redacted_target: str,
    executed: bool,
    summary: dict[str, Any] | None,
    resources: dict[str, Any],
    io: dict[str, Any],
    findings: list[str],
    evidence: str,
) -> str:
    lines = [
        "# Load Test Evidence",
        "",
        "This report is public-safe. It records bounded test settings and aggregate metrics only. Do not place credentials, cookies, authorization headers, private hostnames, or response bodies in the report.",
        "",
        f"- Profile: `{profile_name}`",
        f"- Runner: `{runner_name}` ({runner.get('displayName', runner_name)})",
        f"- Runner kind: `{runner.get('kind', 'http')}`",
        f"- Runner tool: `{runner.get('tool', 'not specified')}`",
        f"- Environment: `{profile.get('environment', 'staging')}`",
        f"- Mode: `{'executed' if executed else 'plan-only'}`",
        f"- Target: `{redacted_target}`",
        f"- Method: `{profile.get('method', 'GET')}`",
        f"- Duration: `{profile.get('durationSeconds', 0)}s`",
        f"- Concurrency: `{profile.get('concurrency', 0)}`",
        f"- Rate: `{profile.get('ratePerSecond', 0)} requests/s`",
        f"- Evidence reference: `{evidence or 'not supplied'}`",
        "",
    ]
    if summary is not None:
        latency = summary["latencyMs"]
        lines.extend(
            [
                "## HTTP Results",
                "",
                f"- Requests: `{summary['requests']}`",
                f"- Effective rate: `{format_number(summary['rps'])} requests/s`",
                f"- Errors outside expected status set: `{summary['errors']}` (`{format_number(summary['errorRate'] * 100)}%`)",
                f"- Latency: min `{format_number(latency['min'])}ms`, avg `{format_number(latency['avg'])}ms`, p50 `{format_number(latency['p50'])}ms`, p95 `{format_number(latency['p95'])}ms`, p99 `{format_number(latency['p99'])}ms`, max `{format_number(latency['max'])}ms`",
                f"- Status counts: `{json.dumps(summary['statusCounts'], sort_keys=True)}`",
                "",
            ]
        )
    else:
        lines.extend(["## HTTP Results", "", "Traffic was not sent. Run with the explicit execute flag after reviewing the profile.", ""])

    lines.extend(["## CPU And Memory", ""])
    if resources.get("available"):
        lines.extend(
            [
                f"- CPU: average `{format_number(resources['cpu'].get('averageMillicores'))}m`, max `{format_number(resources['cpu'].get('maxMillicores'))}m`",
                f"- Memory: average `{format_number(resources['memory'].get('averageMi'))}Mi`, max `{format_number(resources['memory'].get('maxMi'))}Mi`",
            ]
        )
    else:
        lines.append("- Kubernetes Metrics API data was unavailable; CPU and memory could not be sampled.")
    lines.extend([f"- Configured CPU limit: `{profile.get('resourceBudget', {}).get('cpuLimit', 'not set')}`", f"- Configured memory limit: `{profile.get('resourceBudget', {}).get('memoryLimit', 'not set')}`", ""])

    lines.extend(["## I/O Cost", ""])
    if io.get("available"):
        lines.extend(
            [
                f"- Read bytes: `{io['read_bytes']}` (`{format_number(io['readBytesPerSecond'])} B/s`)",
                f"- Write bytes: `{io['write_bytes']}` (`{format_number(io['writeBytesPerSecond'])} B/s`)",
                f"- Read/write operations: `{io['read_ops']}` / `{io['write_ops']}`",
                f"- I/O cost bytes: `{io['ioCostBytes']}` total, `{format_number(io['bytesPerRequest'])}` per request",
                f"- I/O cost operations: `{io['ioCostOps']}` total, `{format_number(io['opsPerRequest'])}` per request",
            ]
        )
    else:
        lines.append(f"- Not measured: {io.get('reason', 'I/O sampling was disabled.')}")
    lines.extend(
        [
            "- I/O cost is reported as bytes and operations per test/request; it is not a cloud-provider billing estimate.",
            "",
            "## Findings",
            "",
        ]
    )
    lines.extend(f"- {finding}" for finding in findings or ["No additional findings."])
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- The runner never prints response bodies or supplied header values.",
            "- The Make target requires `LOAD_TEST_EXECUTE=true` and `LOAD_TEST_CONFIRM=true` before it can generate traffic.",
            "- Stress profiles must use an approved test environment, maintenance window, and rollback owner.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a bounded HTTP load test with Kubernetes resource/I/O evidence.")
    parser.add_argument("--config", default="config/load-test.yaml")
    parser.add_argument("--profile", default="smoke")
    parser.add_argument("--environment", default="")
    parser.add_argument("--target-url", default="")
    parser.add_argument("--namespace", default="")
    parser.add_argument("--selector", default="app.kubernetes.io/part-of=urban-platform-infra")
    parser.add_argument("--method", default="")
    parser.add_argument("--path", default="")
    parser.add_argument("--duration", default="")
    parser.add_argument("--concurrency", default="")
    parser.add_argument("--rate", default="")
    parser.add_argument("--max-requests", default="")
    parser.add_argument("--timeout", default="")
    parser.add_argument("--sample-interval", default="")
    parser.add_argument("--runner", default="")
    parser.add_argument("--io-enabled", choices=["true", "false"], default="")
    parser.add_argument("--cpu-limit", default="")
    parser.add_argument("--memory-limit", default="")
    parser.add_argument("--max-read-bps", default="")
    parser.add_argument("--max-write-bps", default="")
    parser.add_argument("--max-read-iops", default="")
    parser.add_argument("--max-write-iops", default="")
    parser.add_argument("--evidence", default="")
    parser.add_argument("--output", default="reports/load-test.md")
    parser.add_argument("--redact-sensitive", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--list-runners", action="store_true")
    args = parser.parse_args(argv)

    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    config = load_yaml(config_path)
    if args.list_runners:
        runners = config.get("runners", {})
        print(f"Default runner: {config.get('defaultRunner', 'k6')}")
        for name, runner in runners.items():
            if isinstance(runner, dict):
                print(f"{name}: {runner.get('displayName', name)} [{runner.get('kind', 'unknown')}] - {runner.get('description', '')}")
        print(f"{FALLBACK_RUNNER}: Native Python runner [http] - explicit low-dependency fallback")
        return 0
    runner_name, runner = resolve_runner(config, args.runner)
    profile = merge_profile(config, args.profile)
    profile["runner"] = runner_name
    profile["environment"] = args.environment or str(profile.get("environment", "staging"))

    target_base = args.target_url or str(profile.get("targetUrl", ""))
    path = args.path or str(profile.get("path", "/"))
    target = build_target(target_base, path)
    try:
        parsed = urlsplit(target)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError
    except ValueError as exc:
        raise SystemExit("Target URL must use http:// or https:// and include a host.") from exc

    profile["method"] = (args.method or profile.get("method", "GET")).upper()
    profile["durationSeconds"] = positive_int(args.duration or str(profile.get("durationSeconds", 60)), "duration", 3600)
    profile["concurrency"] = positive_int(args.concurrency or str(profile.get("concurrency", 10)), "concurrency", 1000)
    profile["ratePerSecond"] = nonnegative_float(args.rate or str(profile.get("ratePerSecond", 0)), "rate", 10000)
    profile["maxRequests"] = positive_int(args.max_requests or str(profile.get("maxRequests", 10000)), "max-requests", 1_000_000)
    profile["timeoutSeconds"] = nonnegative_float(args.timeout or str(profile.get("timeoutSeconds", 10)), "timeout", 300)
    sample_interval = nonnegative_float(args.sample_interval or str(profile.get("sampleIntervalSeconds", 5)), "sample-interval", 300)
    if sample_interval <= 0:
        raise SystemExit("sample-interval must be greater than zero")
    io_config = profile.get("io", {}) if isinstance(profile.get("io"), dict) else {}
    io_enabled = (args.io_enabled or str(io_config.get("enabled", True))).lower() == "true"
    profile["io"] = dict(io_config)
    profile["io"]["enabled"] = io_enabled
    for argument_name, config_name in (
        ("max_read_bps", "maxReadBytesPerSecond"),
        ("max_write_bps", "maxWriteBytesPerSecond"),
        ("max_read_iops", "maxReadIops"),
        ("max_write_iops", "maxWriteIops"),
    ):
        value = getattr(args, argument_name)
        if value != "":
            if not value.isdigit():
                raise SystemExit(f"{config_name} must be a non-negative integer")
            profile["io"][config_name] = int(value)
    resource_budget = profile.get("resourceBudget", {}) if isinstance(profile.get("resourceBudget"), dict) else {}
    profile["resourceBudget"] = dict(resource_budget)
    if args.cpu_limit:
        profile["resourceBudget"]["cpuLimit"] = args.cpu_limit
    if args.memory_limit:
        profile["resourceBudget"]["memoryLimit"] = args.memory_limit
    expected_status = {int(value) for value in profile.get("expectedStatus", [200])}
    namespace = args.namespace or str(profile.get("namespace", ""))

    output = Path(args.output).expanduser()
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    redacted_target = display_target(target, args.redact_sensitive)
    findings: list[str] = []

    if not args.execute:
        plan_findings = ["Plan only: no traffic was sent."]
        if runner_name not in {"k6", FALLBACK_RUNNER}:
            plan_findings.append(
                f"{runner.get('displayName', runner_name)} is an optional external runner; install `{runner.get('tool', runner_name)}` and execute it only from the protected manual load-test workflow."
            )
        report = render_report(
            profile_name=args.profile,
            runner_name=runner_name,
            runner=runner,
            profile=profile,
            target=target,
            redacted_target=redacted_target,
            executed=False,
            summary=None,
            resources={"available": False},
            io={"available": False, "reason": "Traffic was not executed."},
            findings=plan_findings,
            evidence=args.evidence,
        )
        output.write_text(report, encoding="utf-8")
        print(f"Load-test plan written: {output}")
        return 0

    if runner_name not in {"k6", FALLBACK_RUNNER}:
        raise SystemExit(
            f"Runner `{runner_name}` is catalogued for manual planning but has no built-in adapter in the bounded runner. "
            f"Use its native tool (`{runner.get('tool', runner_name)}`) from an approved staging runner, or choose k6/python."
        )
    if profile["method"] not in {"GET", "HEAD", "OPTIONS"}:
        raise SystemExit("Only GET, HEAD, and OPTIONS are supported by the safe native runner.")
    headers = {"User-Agent": "urban-platform-load-test/1"}
    sampler = KubernetesSampler(namespace, args.selector, sample_interval, io_enabled)
    sampler.start()
    runner_findings: list[str] = []
    runner_failed = False
    if runner_name == "k6":
        summary, runner_findings, runner_failed = run_k6(
            profile,
            target,
            expected_status,
            str(runner.get("command", "k6")),
        )
        elapsed = max(float(profile["durationSeconds"]), 0.001)
    else:
        results, elapsed = run_load(
            target,
            profile["method"],
            profile["durationSeconds"],
            profile["concurrency"],
            profile["ratePerSecond"],
            profile["maxRequests"],
            profile["timeoutSeconds"],
            expected_status,
            headers,
        )
        summary = metric_summary(results, elapsed, expected_status)
    sampler.stop()
    resources = resource_summary(sampler.samples)
    io = io_summary(sampler.samples, summary["requests"], elapsed)
    if summary["errors"]:
        findings.append(f"{summary['errors']} request(s) returned an error or an unexpected status.")
    findings.extend(runner_findings)
    if not resources["available"] and namespace:
        findings.append("CPU/memory metrics were unavailable; verify metrics-server or Prometheus Adapter and the selector.")
    if io_enabled and not io["available"] and namespace:
        findings.append("I/O counters were unavailable; verify cgroup-v2 visibility and pod exec permissions.")
    if not shutil.which("kubectl") and namespace:
        findings.append("kubectl is not available, so Kubernetes resource and I/O sampling was skipped.")

    report = render_report(
        profile_name=args.profile,
        runner_name=runner_name,
        runner=runner,
        profile=profile,
        target=target,
        redacted_target=redacted_target,
        executed=True,
        summary=summary,
        resources=resources,
        io=io,
        findings=findings,
        evidence=args.evidence,
    )
    output.write_text(report, encoding="utf-8")
    print(f"Load-test evidence written: {output}")
    print(f"Requests: {summary['requests']}; errors: {summary['errors']}; p95: {summary['latencyMs']['p95']:.2f}ms")
    return 1 if summary["errors"] or runner_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
