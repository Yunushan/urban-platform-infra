#!/usr/bin/env python3
"""Reconcile and prove the private Kafka-to-ClickHouse production profile.

The command is intentionally dry-run by default. Applying requires an explicit
flag, a non-empty private values file, an authenticated kubeconfig, a complete
operator/CRD preflight, and a fully passing 84-point static contract. It never
prints values, Secret data, remote secret references, private endpoints, or
kubeconfig content.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kafka_clickhouse_readiness as readiness  # noqa: E402


HELM_VERSION_RE = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?")
HELM_DURATION_RE = re.compile(r"^(\d+)([smh])$")
STATIC_TOTAL = 84
REQUIRED_MINIMUM = 92
REQUIRED_CRDS = {
    "kafkas.kafka.strimzi.io": "v1",
    "kafkanodepools.kafka.strimzi.io": "v1",
    "kafkatopics.kafka.strimzi.io": "v1",
    "kafkausers.kafka.strimzi.io": "v1",
    "kafkaconnects.kafka.strimzi.io": "v1",
    "kafkaconnectors.kafka.strimzi.io": "v1",
    "externalsecrets.external-secrets.io": "v1",
    "podmonitors.monitoring.coreos.com": "v1",
    "prometheusrules.monitoring.coreos.com": "v1",
}
HELM_API_VERSIONS = (
    "kafka.strimzi.io/v1/Kafka",
    "kafka.strimzi.io/v1/KafkaNodePool",
    "kafka.strimzi.io/v1/KafkaTopic",
    "kafka.strimzi.io/v1/KafkaUser",
    "kafka.strimzi.io/v1/KafkaConnect",
    "kafka.strimzi.io/v1/KafkaConnector",
    "external-secrets.io/v1/ExternalSecret",
    "monitoring.coreos.com/v1/PodMonitor",
    "monitoring.coreos.com/v1/PrometheusRule",
)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class Stage:
    name: str
    passed: bool
    detail: str


Runner = Callable[[list[str], int], CommandResult]


def run_command(command: list[str], timeout: int) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        return CommandResult(127)
    except subprocess.TimeoutExpired:
        return CommandResult(124)
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def run_with_heartbeat(
    command: list[str],
    timeout: int,
    label: str,
    heartbeat_seconds: int = 30,
) -> CommandResult:
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return CommandResult(127)
    started = time.monotonic()
    next_heartbeat = started + heartbeat_seconds
    while process.poll() is None:
        now = time.monotonic()
        if now - started >= timeout:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            return CommandResult(124)
        if now >= next_heartbeat:
            print(
                f"{label} is still running ({int(now - started)}s elapsed; {timeout}s limit).",
                flush=True,
            )
            next_heartbeat = now + heartbeat_seconds
        time.sleep(min(1.0, max(0.0, timeout - (now - started))))
    return CommandResult(int(process.returncode or 0))


def nonempty_file(path: Path | None) -> bool:
    return path is not None and path.is_file() and path.stat().st_size > 0


def parse_json(value: str) -> dict[str, Any] | None:
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def ready_condition(resource: dict[str, Any]) -> bool:
    return any(
        isinstance(condition, dict)
        and condition.get("type") in {"Ready", "Established", "Available"}
        and str(condition.get("status", "")).lower() == "true"
        for condition in readiness.get(resource, "status", "conditions", default=[])
    )


def static_score(checks: list[readiness.Check]) -> int:
    return sum(check.weight for check in checks if check.passed)


def score_passes(checks: list[readiness.Check], minimum: int) -> bool:
    return (
        static_score(checks) >= minimum
        and not any(check.critical and not check.passed for check in checks)
    )


def enabled_placeholder_secrets(values: dict[str, Any]) -> list[str]:
    external_secrets = readiness.get(
        values,
        "secretManagement",
        "externalSecrets",
        default={},
    )
    invalid: list[str] = []
    for name, definition in readiness.mapping(external_secrets).items():
        secret = readiness.mapping(definition)
        if secret.get("enabled") is not True:
            continue
        data = secret.get("data", [])
        if not isinstance(data, list) or not data:
            invalid.append(str(name))
            continue
        for item in data:
            key = str(readiness.get(item, "remoteRef", "key", default="")).strip()
            if not key or key.startswith("example/"):
                invalid.append(str(name))
                break
    return sorted(set(invalid))


def load_inputs(
    base_values: Path,
    production_values: Path,
    private_values: Path,
) -> tuple[dict[str, Any] | None, list[Stage]]:
    stages: list[Stage] = []
    if not nonempty_file(base_values) or not nonempty_file(production_values):
        stages.append(Stage("Values inputs", False, "base or production values are unavailable"))
        return None, stages
    if not nonempty_file(private_values):
        stages.append(Stage("Private values", False, "a non-empty private values file is required"))
        return None, stages
    try:
        values = readiness.merge(
            readiness.merge(readiness.load_yaml(base_values), readiness.load_yaml(production_values)),
            readiness.load_yaml(private_values),
        )
    except (OSError, ValueError, readiness.yaml.YAMLError) as exc:
        stages.append(Stage("Values inputs", False, f"values YAML is invalid ({type(exc).__name__})"))
        return None, stages

    checks = readiness.static_checks(values)
    failed = [check.name for check in checks if not check.passed]
    contract_ok = static_score(checks) == STATIC_TOTAL and not failed
    detail = f"{static_score(checks)}/{STATIC_TOTAL} static points"
    if failed:
        detail += "; failed: " + ", ".join(failed)
    stages.append(Stage("Static production contract", contract_ok, detail))

    placeholder_secrets = enabled_placeholder_secrets(values)
    stages.append(
        Stage(
            "Private secret references",
            not placeholder_secrets,
            "all enabled ExternalSecret references are private"
            if not placeholder_secrets
            else "replace enabled placeholder references for: " + ", ".join(placeholder_secrets),
        )
    )
    return values, stages


def helm_major(helm: str, runner: Runner = run_command) -> int | None:
    result = runner([helm, "version", "--short"], 20)
    if result.returncode != 0:
        return None
    match = HELM_VERSION_RE.search(result.stdout)
    return int(match.group(1)) if match else None


def helm_duration_seconds(value: str) -> int | None:
    match = HELM_DURATION_RE.fullmatch(str(value).strip())
    if not match:
        return None
    amount = int(match.group(1))
    multiplier = {"s": 1, "m": 60, "h": 3600}[match.group(2)]
    return amount * multiplier if amount > 0 else None


def common_helm_values_args(
    base_values: Path,
    production_values: Path,
    private_values: Path,
) -> list[str]:
    return [
        "--values",
        str(base_values),
        "--values",
        str(production_values),
        "--values",
        str(private_values),
    ]


def build_template_command(
    helm: str,
    release: str,
    chart: Path,
    namespace: str,
    base_values: Path,
    production_values: Path,
    private_values: Path,
) -> list[str]:
    command = [
        helm,
        "template",
        release,
        str(chart),
        "--namespace",
        namespace,
        "--skip-tests",
    ]
    command.extend(common_helm_values_args(base_values, production_values, private_values))
    for api_version in HELM_API_VERSIONS:
        command.extend(["--api-versions", api_version])
    return command


def build_upgrade_command(
    helm: str,
    helm_version_major: int,
    release: str,
    chart: Path,
    namespace: str,
    kubeconfig: Path,
    timeout: str,
    base_values: Path,
    production_values: Path,
    private_values: Path,
) -> list[str]:
    command = [
        helm,
        "upgrade",
        "--install",
        release,
        str(chart),
        "--namespace",
        namespace,
        "--create-namespace",
        "--kubeconfig",
        str(kubeconfig),
        "--timeout",
        timeout,
        "--cleanup-on-fail",
        "--reset-values",
        "--wait",
        "--wait-for-jobs",
    ]
    if helm_version_major >= 4:
        command.append("--rollback-on-failure")
    else:
        command.append("--atomic")
    command.extend(common_helm_values_args(base_values, production_values, private_values))
    return command


def render_validation(
    helm: str,
    release: str,
    chart: Path,
    namespace: str,
    base_values: Path,
    production_values: Path,
    private_values: Path,
    runner: Runner = run_command,
) -> Stage:
    if not chart.is_dir():
        return Stage("Helm render", False, "chart directory is unavailable")
    command = build_template_command(
        helm,
        release,
        chart,
        namespace,
        base_values,
        production_values,
        private_values,
    )
    result = runner(command, 180)
    return Stage(
        "Helm render",
        result.returncode == 0,
        "private production manifests render successfully"
        if result.returncode == 0
        else "private production manifests did not render",
    )


def kubectl_command(kubectl: str, kubeconfig: Path, *arguments: str) -> list[str]:
    return [kubectl, "--kubeconfig", str(kubeconfig), *arguments]


def cluster_ready(
    kubectl: str,
    kubeconfig: Path,
    runner: Runner,
) -> Stage:
    result = runner(
        kubectl_command(
            kubectl,
            kubeconfig,
            "get",
            "--raw=/readyz",
            "--request-timeout=15s",
        ),
        30,
    )
    return Stage(
        "Kubernetes API",
        result.returncode == 0 and result.stdout.strip().lower() == "ok",
        "authenticated API readyz passed"
        if result.returncode == 0 and result.stdout.strip().lower() == "ok"
        else "authenticated API readyz failed",
    )


def crd_preflight(
    kubectl: str,
    kubeconfig: Path,
    runner: Runner,
) -> Stage:
    result = runner(
        kubectl_command(
            kubectl,
            kubeconfig,
            "get",
            "customresourcedefinitions.apiextensions.k8s.io",
            "-o",
            "json",
            "--request-timeout=15s",
        ),
        30,
    )
    loaded = parse_json(result.stdout) if result.returncode == 0 else None
    resources = {
        str(readiness.get(item, "metadata", "name", default="")): item
        for item in readiness.mapping(loaded).get("items", [])
        if isinstance(item, dict)
    }
    missing: list[str] = []
    unready: list[str] = []
    for name, required_version in REQUIRED_CRDS.items():
        resource = resources.get(name)
        if not resource:
            missing.append(name)
            continue
        served_versions = {
            str(version.get("name"))
            for version in readiness.get(resource, "spec", "versions", default=[])
            if isinstance(version, dict) and version.get("served") is True
        }
        if required_version not in served_versions or not ready_condition(resource):
            unready.append(name)
    passed = result.returncode == 0 and not missing and not unready
    details: list[str] = []
    if missing:
        details.append("missing: " + ", ".join(missing))
    if unready:
        details.append("not established/served: " + ", ".join(unready))
    return Stage(
        "Required CRDs",
        passed,
        "all required operator APIs are established" if passed else "; ".join(details) or "CRD discovery failed",
    )


def storage_preflight(
    values: dict[str, Any],
    kubectl: str,
    kubeconfig: Path,
    runner: Runner,
) -> Stage:
    class_name = str(
        readiness.get(values, "messaging", "kafka", "storage", "className", default="")
    ).strip()
    if not class_name:
        return Stage("Kafka durable storage", False, "Kafka StorageClass is not configured")
    result = runner(
        kubectl_command(
            kubectl,
            kubeconfig,
            "get",
            "storageclass",
            class_name,
            "-o",
            "json",
            "--request-timeout=15s",
        ),
        30,
    )
    resource = parse_json(result.stdout) if result.returncode == 0 else None
    resource = readiness.mapping(resource)
    passed = all(
        (
            result.returncode == 0,
            bool(resource.get("provisioner")),
            resource.get("allowVolumeExpansion") is True,
            resource.get("reclaimPolicy") == "Retain",
        )
    )
    return Stage(
        "Kafka durable storage",
        passed,
        "StorageClass exists, expands volumes, and retains released data"
        if passed
        else "StorageClass must exist with expansion enabled and reclaimPolicy Retain",
    )


def node_preflight(
    values: dict[str, Any],
    kubectl: str,
    kubeconfig: Path,
    runner: Runner,
) -> Stage:
    replicas = int(readiness.get(values, "messaging", "kafka", "replicas", default=3) or 3)
    topology_key = str(
        readiness.get(
            values,
            "messaging",
            "kafka",
            "strimzi",
            "rack",
            "topologyKey",
            default="topology.kubernetes.io/zone",
        )
    )
    result = runner(
        kubectl_command(
            kubectl,
            kubeconfig,
            "get",
            "nodes",
            "-o",
            "json",
            "--request-timeout=15s",
        ),
        30,
    )
    loaded = parse_json(result.stdout) if result.returncode == 0 else None
    ready_nodes: list[dict[str, Any]] = []
    for item in readiness.mapping(loaded).get("items", []):
        if not isinstance(item, dict):
            continue
        unschedulable = readiness.get(item, "spec", "unschedulable", default=False) is True
        ready = any(
            isinstance(condition, dict)
            and condition.get("type") == "Ready"
            and str(condition.get("status", "")).lower() == "true"
            for condition in readiness.get(item, "status", "conditions", default=[])
        )
        if ready and not unschedulable:
            ready_nodes.append(item)
    domains = {
        str(readiness.get(node, "metadata", "labels", topology_key, default="")).strip()
        for node in ready_nodes
    }
    domains.discard("")
    passed = result.returncode == 0 and len(ready_nodes) >= replicas and len(domains) >= replicas
    return Stage(
        "Failure-domain capacity",
        passed,
        f"at least {replicas} Ready schedulable nodes in {replicas} distinct failure domains"
        if passed
        else f"requires {replicas} Ready schedulable nodes with distinct {topology_key} labels",
    )


def strimzi_operator_preflight(
    values: dict[str, Any],
    kubectl: str,
    kubeconfig: Path,
    namespace: str,
    operator_namespace: str,
    runner: Runner,
) -> Stage:
    result = runner(
        kubectl_command(
            kubectl,
            kubeconfig,
            "-n",
            operator_namespace,
            "get",
            "deployment/strimzi-cluster-operator",
            "-o",
            "json",
            "--request-timeout=15s",
        ),
        30,
    )
    deployment = readiness.mapping(parse_json(result.stdout) if result.returncode == 0 else None)
    desired_version = str(
        readiness.get(values, "messaging", "kafka", "strimzi", "operatorVersion", default="")
    )
    containers = readiness.get(deployment, "spec", "template", "spec", "containers", default=[])
    images = [str(item.get("image", "")) for item in containers if isinstance(item, dict)]
    namespace_values = {
        str(env.get("value", ""))
        for container in containers
        if isinstance(container, dict)
        for env in container.get("env", [])
        if isinstance(env, dict) and env.get("name") == "STRIMZI_NAMESPACE"
    }
    watches_target = not namespace_values or any(
        value == "*" or namespace in {part.strip() for part in value.split(",")}
        for value in namespace_values
    )
    passed = all(
        (
            result.returncode == 0,
            int(readiness.get(deployment, "status", "availableReplicas", default=0) or 0) >= 1,
            bool(desired_version) and any(desired_version in image for image in images),
            watches_target,
        )
    )
    return Stage(
        "Strimzi operator",
        passed,
        "matching operator is available and watches the target namespace"
        if passed
        else "matching Strimzi operator must be available and watch the target namespace",
    )


def secret_store_preflight(
    values: dict[str, Any],
    kubectl: str,
    kubeconfig: Path,
    namespace: str,
    runner: Runner,
) -> Stage:
    name = str(readiness.get(values, "secretManagement", "secretStoreRef", "name", default="")).strip()
    kind = str(readiness.get(values, "secretManagement", "secretStoreRef", "kind", default="")).strip()
    if not name or kind not in {"SecretStore", "ClusterSecretStore"}:
        return Stage("External secret store", False, "SecretStore reference is incomplete")
    resource = "secretstore" if kind == "SecretStore" else "clustersecretstore"
    arguments = ["get", f"{resource}/{name}", "-o", "json", "--request-timeout=15s"]
    if kind == "SecretStore":
        arguments[0:0] = ["-n", namespace]
    result = runner(kubectl_command(kubectl, kubeconfig, *arguments), 30)
    loaded = readiness.mapping(parse_json(result.stdout) if result.returncode == 0 else None)
    passed = result.returncode == 0 and ready_condition(loaded)
    return Stage(
        "External secret store",
        passed,
        "referenced secret store reports Ready"
        if passed
        else "referenced secret store is missing or not Ready",
    )


def cluster_preflight(
    values: dict[str, Any],
    kubectl: str,
    kubeconfig: Path,
    namespace: str,
    operator_namespace: str,
    runner: Runner = run_command,
) -> list[Stage]:
    stages = [cluster_ready(kubectl, kubeconfig, runner)]
    if not stages[-1].passed:
        return stages
    stages.extend(
        [
            crd_preflight(kubectl, kubeconfig, runner),
            storage_preflight(values, kubectl, kubeconfig, runner),
            node_preflight(values, kubectl, kubeconfig, runner),
            strimzi_operator_preflight(
                values,
                kubectl,
                kubeconfig,
                namespace,
                operator_namespace,
                runner,
            ),
            secret_store_preflight(values, kubectl, kubeconfig, namespace, runner),
        ]
    )
    return stages


def write_plan(
    path: Path,
    apply: bool,
    release: str,
    namespace: str,
    minimum: int,
    stages: list[Stage],
) -> None:
    result = "PASS" if stages and all(stage.passed for stage in stages) else "FAIL"
    lines = [
        "# Kafka to ClickHouse Reconciliation",
        "",
        "This report is sanitized. It does not contain values, credentials, endpoints, remote secret references, or kubeconfig content.",
        "",
        f"- Mode: `{'APPLY' if apply else 'PLAN'}`",
        f"- Result: `{result}`",
        f"- Release: `{release}`",
        f"- Namespace: `{namespace}`",
        f"- Required live score: `{minimum}/100`",
        "",
        "| Stage | Status | Detail |",
        "|---|---|---|",
    ]
    for stage in stages:
        lines.append(f"| {stage.name} | {'PASS' if stage.passed else 'FAIL'} | {stage.detail} |")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_readiness_report(
    values: dict[str, Any],
    kubeconfig: Path,
    namespace: str,
    minimum: int,
    output: Path,
) -> tuple[list[readiness.Check], int]:
    checks = readiness.static_checks(values) + readiness.live_checks(
        values,
        kubeconfig,
        namespace,
        True,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(readiness.render_report(checks, minimum), encoding="utf-8")
    return checks, static_score(checks)


def wait_for_readiness(
    values: dict[str, Any],
    kubeconfig: Path,
    namespace: str,
    minimum: int,
    output: Path,
    timeout_seconds: int,
    poll_interval_seconds: int,
    stable_passes: int,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[bool, int]:
    deadline = monotonic() + timeout_seconds
    started = monotonic()
    consecutive = 0
    last_score = 0
    while True:
        checks, last_score = write_readiness_report(
            values,
            kubeconfig,
            namespace,
            minimum,
            output,
        )
        passed = score_passes(checks, minimum)
        consecutive = consecutive + 1 if passed else 0
        elapsed = int(monotonic() - started)
        failed = ", ".join(check.name for check in checks if not check.passed) or "none"
        print(
            f"Readiness {last_score}/100 after {elapsed}s; "
            f"stable passes {consecutive}/{stable_passes}; pending: {failed}",
            flush=True,
        )
        if consecutive >= stable_passes:
            return True, last_score
        if monotonic() >= deadline:
            return False, last_score
        sleep(min(poll_interval_seconds, max(0.0, deadline - monotonic())))


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Plan or apply the private Kafka-to-ClickHouse production profile and prove its live score."
    )
    value.add_argument("--base-values", default=str(ROOT / "helm/urban-platform-infra/values.yaml"))
    value.add_argument(
        "--production-values",
        default=str(ROOT / "helm/urban-platform-infra/values-production.yaml"),
    )
    value.add_argument("--private-values", required=True)
    value.add_argument("--chart", default=str(ROOT / "helm/urban-platform-infra"))
    value.add_argument("--release", default="urban-platform-infra")
    value.add_argument("--namespace", default="urban-platform")
    value.add_argument("--strimzi-namespace", default="strimzi-system")
    value.add_argument("--kubeconfig", default="")
    value.add_argument("--minimum", type=int, default=REQUIRED_MINIMUM)
    value.add_argument("--helm-timeout", default="20m")
    value.add_argument("--readiness-timeout-seconds", type=int, default=1200)
    value.add_argument("--poll-interval-seconds", type=int, default=10)
    value.add_argument("--stable-passes", type=int, default=2)
    value.add_argument("--output", default=str(ROOT / "reports/kafka-clickhouse-readiness.md"))
    value.add_argument("--plan-output", default=str(ROOT / "reports/kafka-clickhouse-reconcile.md"))
    value.add_argument("--apply", action="store_true")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not REQUIRED_MINIMUM <= args.minimum <= 100:
        print(f"--minimum must be between {REQUIRED_MINIMUM} and 100", file=sys.stderr)
        return 2
    if args.readiness_timeout_seconds <= 0 or args.poll_interval_seconds <= 0:
        print("readiness timeout and poll interval must be positive", file=sys.stderr)
        return 2
    if not 1 <= args.stable_passes <= 10:
        print("--stable-passes must be between 1 and 10", file=sys.stderr)
        return 2
    helm_timeout_seconds = helm_duration_seconds(args.helm_timeout)
    if helm_timeout_seconds is None:
        print("--helm-timeout must be a positive duration such as 20m", file=sys.stderr)
        return 2

    base_values = Path(args.base_values).expanduser().resolve()
    production_values = Path(args.production_values).expanduser().resolve()
    private_values = Path(args.private_values).expanduser().resolve()
    chart = Path(args.chart).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    plan_output = Path(args.plan_output).expanduser().resolve()
    stages: list[Stage] = []

    values, input_stages = load_inputs(base_values, production_values, private_values)
    stages.extend(input_stages)
    if values is None or not all(stage.passed for stage in input_stages):
        write_plan(plan_output, args.apply, args.release, args.namespace, args.minimum, stages)
        print(f"Reconciliation stopped before cluster mutation. Sanitized plan: {plan_output}", file=sys.stderr)
        return 1

    helm = shutil.which("helm")
    kubectl = shutil.which("kubectl")
    tools_ok = bool(helm) and (bool(kubectl) if args.apply else True)
    stages.append(
        Stage(
            "Operator tools",
            tools_ok,
            "required Helm and kubectl clients are available"
            if tools_ok
            else "Helm is required; kubectl is additionally required for apply mode",
        )
    )
    if not tools_ok:
        write_plan(plan_output, args.apply, args.release, args.namespace, args.minimum, stages)
        print(f"Reconciliation prerequisites failed. Sanitized plan: {plan_output}", file=sys.stderr)
        return 1

    assert helm is not None
    version_major = helm_major(helm)
    stages.append(
        Stage(
            "Helm compatibility",
            version_major is not None and version_major >= 3,
            "supported Helm client detected"
            if version_major is not None and version_major >= 3
            else "Helm 3 or newer is required",
        )
    )
    stages.append(
        render_validation(
            helm,
            args.release,
            chart,
            args.namespace,
            base_values,
            production_values,
            private_values,
        )
    )
    if not all(stage.passed for stage in stages):
        write_plan(plan_output, args.apply, args.release, args.namespace, args.minimum, stages)
        print(f"Reconciliation validation failed. Sanitized plan: {plan_output}", file=sys.stderr)
        return 1

    if not args.apply:
        stages.append(Stage("Cluster mutation", True, "not requested; rerun with --apply after review"))
        write_plan(plan_output, False, args.release, args.namespace, args.minimum, stages)
        print(f"Dry-run reconciliation plan passed: {plan_output}")
        print("No cluster resources were changed.")
        return 0

    kubeconfig = Path(args.kubeconfig).expanduser().resolve() if args.kubeconfig else None
    if not nonempty_file(kubeconfig):
        stages.append(Stage("Private kubeconfig", False, "a non-empty authenticated kubeconfig is required"))
        write_plan(plan_output, True, args.release, args.namespace, args.minimum, stages)
        print(f"Reconciliation stopped before cluster mutation. Sanitized plan: {plan_output}", file=sys.stderr)
        return 1
    assert kubectl is not None and kubeconfig is not None and version_major is not None

    preflight = cluster_preflight(
        values,
        kubectl,
        kubeconfig,
        args.namespace,
        args.strimzi_namespace,
    )
    stages.extend(preflight)
    if not all(stage.passed for stage in preflight):
        write_plan(plan_output, True, args.release, args.namespace, args.minimum, stages)
        print(f"Cluster preflight failed before mutation. Sanitized plan: {plan_output}", file=sys.stderr)
        return 1

    print("Cluster preflight passed. Reconciling the reviewed production release.", flush=True)
    helm_command = build_upgrade_command(
        helm,
        version_major,
        args.release,
        chart,
        args.namespace,
        kubeconfig,
        args.helm_timeout,
        base_values,
        production_values,
        private_values,
    )
    helm_result = run_with_heartbeat(
        helm_command,
        helm_timeout_seconds + 60,
        "Helm reconciliation",
    )
    stages.append(
        Stage(
            "Helm reconciliation",
            helm_result.returncode == 0,
            "upgrade/install completed with rollback protection"
            if helm_result.returncode == 0
            else "upgrade/install failed or timed out; Helm rollback protection was requested",
        )
    )
    if helm_result.returncode != 0:
        write_plan(plan_output, True, args.release, args.namespace, args.minimum, stages)
        print(f"Helm reconciliation failed. Sanitized plan: {plan_output}", file=sys.stderr)
        return 1

    print("Helm reconciliation completed. Measuring stable live readiness.", flush=True)
    try:
        ready, score = wait_for_readiness(
            values,
            kubeconfig,
            args.namespace,
            args.minimum,
            output,
            args.readiness_timeout_seconds,
            args.poll_interval_seconds,
            args.stable_passes,
        )
    except KeyboardInterrupt:
        stages.append(Stage("Stable live readiness", False, "interrupted while observing live readiness"))
        write_plan(plan_output, True, args.release, args.namespace, args.minimum, stages)
        print(f"Readiness observation interrupted. Sanitized plan: {plan_output}", file=sys.stderr)
        return 130

    stages.append(
        Stage(
            "Stable live readiness",
            ready,
            f"stable live gate passed at {score}/100"
            if ready
            else f"live gate remained below the required state at {score}/100",
        )
    )
    write_plan(plan_output, True, args.release, args.namespace, args.minimum, stages)
    print(f"Kafka-to-ClickHouse readiness report: {output}")
    print(f"Sanitized reconciliation report: {plan_output}")
    if not ready:
        print(f"Live readiness did not reach the required {args.minimum}/100 state.", file=sys.stderr)
        return 1
    print(f"Kafka-to-ClickHouse reached a stable {score}/100 live score.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
