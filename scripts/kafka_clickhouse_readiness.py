#!/usr/bin/env python3
"""Score the production Kafka-to-ClickHouse path without reading secret values."""
from __future__ import annotations

import argparse
import base64
import binascii
import ipaddress
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DIGEST_RE = re.compile(r"^sha256:[A-Fa-f0-9]{64}$")
PLACEHOLDER_HOST_SUFFIXES = (".example", ".invalid", ".localhost", ".test")
PLACEHOLDER_HOSTS = {
    "example.com",
    "example.net",
    "example.org",
    "registry.example.com",
    "registry.example.net",
    "registry.example.org",
}
DOCUMENTATION_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")
)


@dataclass(frozen=True)
class Check:
    name: str
    weight: int
    passed: bool
    detail: str
    critical: bool = False


def mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return value


def merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def get(value: Any, *keys: str, default: Any = None) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


def is_ip_literal(value: Any) -> bool:
    try:
        ipaddress.ip_address(str(value).strip())
    except ValueError:
        return False
    return True


def is_placeholder_host(value: Any) -> bool:
    host = str(value).strip().lower().rstrip(".")
    if not host:
        return True
    host = host.split("/", 1)[0]
    if host.startswith("[") and "]" in host:
        host = host[1 : host.index("]")]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    return (
        host in PLACEHOLDER_HOSTS
        or host.startswith("example.")
        or any(host.endswith(suffix) for suffix in PLACEHOLDER_HOST_SUFFIXES)
        or any(host.endswith(f".{candidate}") for candidate in PLACEHOLDER_HOSTS)
    )


def valid_cidrs(values: Any) -> bool:
    if not isinstance(values, list) or not values:
        return False
    try:
        networks = [ipaddress.ip_network(str(value), strict=False) for value in values]
    except ValueError:
        return False
    for network in networks:
        if network.prefixlen == 0:
            return False
        if network.is_loopback or network.is_link_local or network.is_multicast or network.is_unspecified:
            return False
        if any(network.overlaps(documentation) for documentation in DOCUMENTATION_NETWORKS):
            return False
    return True


def topic_map(strimzi: dict[str, Any]) -> dict[str, dict[str, Any]]:
    definitions = get(strimzi, "topics", "definitions", default=[])
    return {
        str(item.get("name")): item
        for item in definitions
        if isinstance(item, dict) and item.get("name")
    }


def static_checks(values: dict[str, Any]) -> list[Check]:
    kafka = mapping(get(values, "messaging", "kafka", default={}))
    strimzi = mapping(kafka.get("strimzi"))
    connect = mapping(strimzi.get("connect"))
    connector = mapping(connect.get("connector"))
    errors = mapping(connector.get("errors"))
    consumer = mapping(connector.get("consumer"))
    clickhouse = mapping(connector.get("clickhouseSettings"))
    topics = topic_map(strimzi)
    source = topics.get(str(connector.get("topic", "")), {})
    dlq = topics.get(str(errors.get("deadLetterTopic", "")), {})
    operator_image = mapping(strimzi.get("operatorImage"))

    broker_ok = all(
        (
            kafka.get("provider") == "strimzi",
            int(kafka.get("replicas", 0) or 0) >= 3,
            strimzi.get("kafkaVersion") == "4.3.0",
            strimzi.get("operatorVersion") == "1.1.0",
            strimzi.get("operatorNamespace") == "strimzi-system",
            operator_image.get("tag") == strimzi.get("operatorVersion"),
            strimzi.get("useCustomKafkaImage") is True,
            get(strimzi, "listeners", "plain", "enabled") is False,
            get(strimzi, "listeners", "tls", "enabled") is True,
            get(strimzi, "listeners", "tls", "authentication") == "tls",
            get(strimzi, "authorization", "enabled") is True,
            get(strimzi, "authorization", "type") == "simple",
            get(strimzi, "rack", "enabled") is True,
            get(strimzi, "brokerConfig", "autoCreateTopics") is False,
            get(strimzi, "brokerConfig", "uncleanLeaderElection") is False,
            get(strimzi, "scheduling", "enabled") is True,
            get(strimzi, "deleteClaim") is False,
        )
    )

    topics_ok = all(
        (
            get(strimzi, "topics", "enabled") is True,
            int(source.get("partitions", 0) or 0) >= 6,
            int(source.get("replicas", 0) or 0) >= 3,
            int(get(source, "config", "min.insync.replicas", default=0) or 0) >= 2,
            int(dlq.get("partitions", 0) or 0) >= 3,
            int(dlq.get("replicas", 0) or 0) >= 3,
            int(get(dlq, "config", "min.insync.replicas", default=0) or 0) >= 2,
        )
    )

    broker_image = mapping(kafka.get("image"))
    image = mapping(connect.get("image"))
    connect_ok = all(
        (
            connect.get("enabled") is True,
            int(connect.get("replicas", 0) or 0) >= 3,
            get(connect, "build", "enabled") is False,
            image.get("tag") == "1.4.0" or bool(image.get("digest")),
            get(connect, "authentication", "type") == "tls",
            get(connect, "tls", "enabled") is True,
            bool(connect.get("groupId")),
            bool(connect.get("configStorageTopic")),
            bool(connect.get("offsetStorageTopic")),
            bool(connect.get("statusStorageTopic")),
            bool(get(connect, "credentialsSecret", "name")),
            get(connect, "metrics", "enabled") is True,
            get(connect, "networkPolicy", "enabled") is True,
        )
    )

    tasks_max = int(connector.get("tasksMax", 0) or 0)
    source_partitions = int(source.get("partitions", 0) or 0)
    sink_consumer_group = str(connector.get("consumerGroup", "")).strip()
    connector_ok = all(
        (
            connector.get("enabled") is True,
            connector.get("class") == "com.clickhouse.kafka.connect.ClickHouseSinkConnector",
            tasks_max > 0,
            source_partitions > 0 and tasks_max <= source_partitions,
            connector.get("ssl") is True,
            connector.get("jdbcConnectionProperties") == "?sslmode=STRICT",
            connector.get("exactlyOnce") is True,
            connector.get("ignorePartitionsWhenBatching") is False,
            int(connector.get("bufferCount", -1) or 0) == 0,
            int(connector.get("bufferFlushTimeMs", -1) or 0) == 0,
            int(errors.get("retryTimeoutMs", 0) or 0) >= 300000,
            int(errors.get("retryDelayMaxMs", 0) or 0) >= 10000,
            errors.get("tolerance") == "all",
            errors.get("logIncludeMessages") is False,
            errors.get("deadLetterTopic") in topics,
            int(errors.get("deadLetterReplicationFactor", 0) or 0) >= 3,
            get(connector, "autoRestart", "enabled") is True,
            0 < int(get(connector, "autoRestart", "maxRestarts", default=0) or 0) <= 10,
            bool(sink_consumer_group),
            sink_consumer_group != str(connect.get("groupId", "")).strip(),
            consumer.get("isolationLevel") == "read_committed",
            0 < int(consumer.get("maxPollRecords", 0) or 0) <= 10000,
            clickhouse.get("asyncInsert") is True,
            clickhouse.get("waitForAsyncInsert") is True,
        )
    )

    external_secrets = mapping(get(values, "secretManagement", "externalSecrets", default={}))
    credential_secret = mapping(external_secrets.get("clickhouseSinkCredentials"))
    registry_secret = mapping(external_secrets.get("registryCredentials"))
    secret_keys = {
        item.get("secretKey")
        for item in credential_secret.get("data", [])
        if isinstance(item, dict)
    }
    controls_ok = all(
        (
            get(values, "secretManagement", "enabled") is True,
            get(values, "secretManagement", "provider") == "external-secrets",
            get(values, "secretManagement", "providerAdapters", "externalSecrets", "enabled") is True,
            credential_secret.get("enabled") is True,
            credential_secret.get("targetName") == get(connect, "credentialsSecret", "name"),
            secret_keys >= {"username", "password"},
            get(strimzi, "kafkaExporter", "enabled") is True,
            get(strimzi, "cruiseControl", "enabled") is True,
            get(strimzi, "metrics", "enabled") is True,
            get(values, "monitoring", "prometheusRules", "kafkaClickhouse", "enabled") is True,
            get(values, "monitoring", "prometheusRules", "kafkaClickhouse", "consumerGroup") == sink_consumer_group,
        )
    )

    hostname = str(connector.get("hostname", "")).strip()
    image_registry = str(get(values, "global", "imageRegistry", default="")).strip()
    image_pull_secrets = get(values, "global", "imagePullSecrets", default=[])
    remote_keys = [
        str(get(item, "remoteRef", "key", default=""))
        for item in credential_secret.get("data", [])
        if isinstance(item, dict)
    ]
    registry_remote_keys = [
        str(get(item, "remoteRef", "key", default=""))
        for item in registry_secret.get("data", [])
        if isinstance(item, dict)
    ]
    deployment_inputs_ok = all(
        (
            bool(hostname),
            not is_placeholder_host(hostname),
            not is_ip_literal(hostname),
            int(connector.get("port", 0) or 0) not in {0, 8123},
            bool(image_registry),
            not is_placeholder_host(image_registry),
            isinstance(image_pull_secrets, list) and bool(image_pull_secrets),
            registry_secret.get("enabled") is True,
            registry_secret.get("targetName") in image_pull_secrets,
            bool(registry_remote_keys),
            all(key and not key.startswith("example/") for key in registry_remote_keys),
            bool(image.get("repository")),
            bool(DIGEST_RE.fullmatch(str(image.get("digest", "")))),
            bool(broker_image.get("repository")),
            bool(DIGEST_RE.fullmatch(str(broker_image.get("digest", "")))),
            bool(operator_image.get("repository")),
            bool(DIGEST_RE.fullmatch(str(operator_image.get("digest", "")))),
            bool(remote_keys),
            all(key and not key.startswith("example/") for key in remote_keys),
            valid_cidrs(get(connect, "networkPolicy", "egressCidrs", default=[])),
        )
    )

    return [
        Check("Broker HA, durability, TLS, and ACL policy", 18, broker_ok, "three-node TLS-only Strimzi/KRaft broker policy", True),
        Check("Managed source and DLQ topic durability", 12, topics_ok, "operator-managed RF=3 topics with min ISR 2", True),
        Check("Kafka Connect HA and broker authentication", 16, connect_ok, "three mTLS workers with durable internal topics", True),
        Check("ClickHouse delivery and failure controls", 20, connector_ok, "bounded batching, acknowledged async inserts, retries, and DLQ", True),
        Check("Credential delivery and observability", 10, controls_ok, "ExternalSecret, metrics, exporter, and Cruise Control"),
        Check("Private production endpoint and immutable images", 8, deployment_inputs_ok, "DNS/TLS endpoint, non-example secret refs, and digest-pinned operator, broker, and Connect images", True),
    ]


def condition_ready(resource: dict[str, Any]) -> bool:
    return any(
        isinstance(item, dict)
        and item.get("type") == "Ready"
        and str(item.get("status", "")).lower() == "true"
        for item in mapping(resource.get("status")).get("conditions", [])
    )


def has_active_warning(resource: dict[str, Any]) -> bool:
    return any(
        isinstance(item, dict)
        and item.get("type") == "Warning"
        and str(item.get("status", "")).lower() == "true"
        for item in mapping(resource.get("status")).get("conditions", [])
    )


def reconciled_ready(resource: dict[str, Any]) -> bool:
    generation = int(get(resource, "metadata", "generation", default=0) or 0)
    observed = int(get(resource, "status", "observedGeneration", default=0) or 0)
    return condition_ready(resource) and observed >= generation and not has_active_warning(resource)


def condition_ready_if_observed(resource: dict[str, Any]) -> bool:
    generation = int(get(resource, "metadata", "generation", default=0) or 0)
    observed_value = get(resource, "status", "observedGeneration")
    if observed_value is not None:
        try:
            if int(observed_value) < generation:
                return False
        except (TypeError, ValueError):
            return False
    return condition_ready(resource) and not has_active_warning(resource)


def valid_encoded_secret_data(value: Any) -> bool:
    """Check non-empty base64 Secret data without exposing its decoded value."""
    encoded = str(value or "").strip()
    if not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return False
    return bool(decoded)


def external_secret_resource_name(value: Any) -> str:
    """Mirror Helm's kebabcase naming for ExternalSecret metadata."""
    text = str(value).strip()
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", text)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", text)
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()


def external_secret_target_matches(
    external_secret: dict[str, Any] | None,
    target_name: str,
) -> bool:
    return (
        external_secret is not None
        and str(get(external_secret, "spec", "target", "name", default="")).strip()
        == target_name
    )


def target_secret_matches(
    secret: dict[str, Any] | None,
    target_name: str,
    target_type: str,
    required_keys: set[str],
) -> bool:
    if secret is None or str(get(secret, "metadata", "name", default="")).strip() != target_name:
        return False
    if secret.get("type") != target_type or not required_keys:
        return False
    data = mapping(secret.get("data"))
    return all(valid_encoded_secret_data(data.get(key)) for key in required_keys)


def kubernetes_name(value: Any) -> str:
    return str(value).strip().lower().replace(".", "-")


def scalar_equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return str(actual).strip().lower() == str(expected).lower()
    return str(actual).strip() == str(expected).strip()


def int_at_least(values: Any, key: str, minimum: int) -> bool:
    try:
        return int(mapping(values).get(key, 0)) >= minimum
    except (TypeError, ValueError):
        return False


def expected_connect_image(values: dict[str, Any], connect: dict[str, Any]) -> str:
    return expected_component_image(values, mapping(connect.get("image")))


def expected_component_image(values: dict[str, Any], image: dict[str, Any]) -> str:
    repository = str(image.get("repository", "")).strip()
    registry = str(get(values, "global", "imageRegistry", default="")).strip().rstrip("/")
    if registry:
        repository = f"{registry}/{repository}"
    digest = str(image.get("digest", "")).strip()
    if digest:
        return f"{repository}@{digest}"
    tag = str(image.get("tag", "")).strip()
    return f"{repository}:{tag}" if repository and tag else ""


def topic_spec_matches(resource: dict[str, Any], desired: dict[str, Any]) -> bool:
    spec = mapping(resource.get("spec"))
    actual_config = mapping(spec.get("config"))
    desired_config = mapping(desired.get("config"))
    return all(
        (
            int(spec.get("partitions", 0) or 0) == int(desired.get("partitions", 0) or 0),
            int(spec.get("replicas", 0) or 0) == int(desired.get("replicas", 0) or 0),
            scalar_equal(
                actual_config.get("min.insync.replicas"),
                desired_config.get("min.insync.replicas"),
            ),
        )
    )


def acl_allows(
    acls: Any,
    resource_type: str,
    resource_name: str | None,
    operations: set[str],
) -> bool:
    for acl in acls if isinstance(acls, list) else []:
        resource = mapping(mapping(acl).get("resource"))
        if resource.get("type") != resource_type:
            continue
        if resource_name is not None and resource.get("name") != resource_name:
            continue
        if resource_name is not None and resource.get("patternType", "literal") != "literal":
            continue
        if set(mapping(acl).get("operations", [])) >= operations:
            return True
    return False


def kubectl_json(kubectl: str, kubeconfig: Path, namespace: str, resource: str) -> dict[str, Any] | None:
    command = [
        kubectl,
        "--kubeconfig",
        str(kubeconfig),
        "-n",
        namespace,
        "get",
        resource,
        "-o",
        "json",
        "--request-timeout=15s",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        loaded = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def kubectl_api_ready(kubectl: str, kubeconfig: Path) -> bool:
    command = [
        kubectl,
        "--kubeconfig",
        str(kubeconfig),
        "get",
        "--raw=/readyz",
        "--request-timeout=8s",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=12)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and completed.stdout.strip().lower() == "ok"


def resource_items(resource: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [
        item
        for item in mapping(resource).get("items", [])
        if isinstance(item, dict)
    ]


def pod_ready(resource: dict[str, Any]) -> bool:
    return (
        get(resource, "status", "phase") == "Running"
        and not get(resource, "metadata", "deletionTimestamp")
        and any(
            isinstance(condition, dict)
            and condition.get("type") == "Ready"
            and str(condition.get("status", "")).lower() == "true"
            for condition in get(resource, "status", "conditions", default=[])
        )
    )


def pod_image(resource: dict[str, Any], container_name: str) -> str:
    for container in get(resource, "spec", "containers", default=[]):
        if isinstance(container, dict) and container.get("name") == container_name:
            return str(container.get("image", ""))
    return ""


def distributed_ready_pods(
    pods: list[dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    replicas: int,
    topology_key: str,
    expected_image: str = "",
    container_name: str = "",
) -> bool:
    node_names = {
        str(get(pod, "spec", "nodeName", default="")).strip()
        for pod in pods
    }
    node_names.discard("")
    domains = {
        str(get(nodes.get(node_name, {}), "metadata", "labels", topology_key, default="")).strip()
        for node_name in node_names
    }
    domains.discard("")
    images_match = True
    if expected_image:
        if container_name:
            images_match = all(
                pod_image(pod, container_name) == expected_image
                for pod in pods
            )
        else:
            images_match = all(
                any(
                    isinstance(container, dict) and container.get("image") == expected_image
                    for container in get(pod, "spec", "containers", default=[])
                )
                for pod in pods
            )
    return all(
        (
            len(pods) == replicas,
            all(pod_ready(pod) for pod in pods),
            len(node_names) == replicas,
            len(domains) == replicas,
            images_match,
        )
    )


def live_checks(values: dict[str, Any], kubeconfig: Path | None, namespace: str, enabled: bool) -> list[Check]:
    if not enabled:
        detail = "not assessed; rerun with --live and a private kubeconfig"
        return [
            Check("Live broker and topic readiness", 8, False, detail, True),
            Check("Live Connect and ClickHouse sink readiness", 8, False, detail, True),
        ]
    kubectl = shutil.which("kubectl")
    if not kubectl or kubeconfig is None or not kubeconfig.is_file():
        detail = "kubectl or the private kubeconfig is unavailable"
        return [
            Check("Live broker and topic readiness", 8, False, detail, True),
            Check("Live Connect and ClickHouse sink readiness", 8, False, detail, True),
        ]
    if not kubectl_api_ready(kubectl, kubeconfig):
        detail = "the authenticated Kubernetes API readyz probe failed"
        return [
            Check("Live broker and topic readiness", 8, False, detail, True),
            Check("Live Connect and ClickHouse sink readiness", 8, False, detail, True),
        ]

    strimzi = mapping(get(values, "messaging", "kafka", "strimzi", default={}))
    connect_config = mapping(strimzi.get("connect"))
    connector_config = mapping(connect_config.get("connector"))
    errors_config = mapping(connector_config.get("errors"))
    topic_definitions = topic_map(strimzi)
    source_topic = str(connector_config.get("topic", ""))
    dlq_topic = str(errors_config.get("deadLetterTopic", ""))
    connect_name = str(connect_config.get("name", "clickhouse-connect"))
    connector_name = str(connector_config.get("name", "clickhouse-bemobile-sink"))
    user_name = str(get(connect_config, "authentication", "userSecret", default=connect_name))
    node_pool_name = str(strimzi.get("nodePoolName", "dual-role"))

    pods = resource_items(kubectl_json(kubectl, kubeconfig, namespace, "pods"))
    pvcs = resource_items(kubectl_json(kubectl, kubeconfig, namespace, "persistentvolumeclaims"))
    node_resources = resource_items(kubectl_json(kubectl, kubeconfig, namespace, "nodes"))
    nodes = {
        str(get(node, "metadata", "name", default="")): node
        for node in node_resources
        if get(node, "metadata", "name")
    }
    topology_key = str(get(strimzi, "rack", "topologyKey", default="topology.kubernetes.io/zone"))
    desired_replicas = int(get(values, "messaging", "kafka", "replicas", default=0) or 0)
    expected_kafka_image = expected_component_image(
        values,
        mapping(get(values, "messaging", "kafka", "image", default={})),
    )
    expected_operator_image = expected_component_image(
        values,
        mapping(strimzi.get("operatorImage")),
    )
    operator_namespace = str(strimzi.get("operatorNamespace", "strimzi-system"))
    operator = kubectl_json(
        kubectl,
        kubeconfig,
        operator_namespace,
        "deployment/strimzi-cluster-operator",
    )
    operator_containers = get(operator or {}, "spec", "template", "spec", "containers", default=[])
    operator_images = {
        str(container.get("image", ""))
        for container in operator_containers
        if isinstance(container, dict)
    }
    operator_namespace_values = {
        str(env.get("value", ""))
        for container in operator_containers
        if isinstance(container, dict)
        for env in container.get("env", [])
        if isinstance(env, dict) and env.get("name") == "STRIMZI_NAMESPACE"
    }
    operator_watches_namespace = not operator_namespace_values or any(
        value == "*" or namespace in {part.strip() for part in value.split(",")}
        for value in operator_namespace_values
    )
    operator_ready = bool(
        operator
        and int(get(operator, "status", "availableReplicas", default=0) or 0) >= 1
        and operator_images == {expected_operator_image}
        and operator_watches_namespace
    )
    kafka_pods = [
        pod
        for pod in pods
        if get(pod, "metadata", "labels", "strimzi.io/cluster") == "kafka"
        and get(pod, "metadata", "labels", "strimzi.io/pool-name") == node_pool_name
    ]
    broker_pods_ready = distributed_ready_pods(
        kafka_pods,
        nodes,
        desired_replicas,
        topology_key,
        expected_kafka_image,
    )
    desired_storage_class = str(get(values, "messaging", "kafka", "storage", "className", default=""))
    desired_storage_size = str(get(values, "messaging", "kafka", "storage", "size", default=""))
    storage_class = kubectl_json(
        kubectl,
        kubeconfig,
        namespace,
        f"storageclass/{desired_storage_class}",
    )
    storage_class_ready = bool(
        storage_class
        and storage_class.get("provisioner")
        and storage_class.get("allowVolumeExpansion") is True
        and storage_class.get("reclaimPolicy") == "Retain"
    )
    kafka_pvcs = [
        pvc
        for pvc in pvcs
        if get(pvc, "metadata", "labels", "strimzi.io/cluster") == "kafka"
        and get(pvc, "metadata", "labels", "strimzi.io/pool-name") == node_pool_name
    ]
    kafka_pvcs_ready = (
        len(kafka_pvcs) == desired_replicas
        and all(
            get(pvc, "status", "phase") == "Bound"
            and get(pvc, "spec", "storageClassName") == desired_storage_class
            and scalar_equal(get(pvc, "status", "capacity", "storage"), desired_storage_size)
            for pvc in kafka_pvcs
        )
    )

    kafka = kubectl_json(kubectl, kubeconfig, namespace, "kafka/kafka")
    pool = kubectl_json(kubectl, kubeconfig, namespace, f"kafkanodepool/{node_pool_name}")
    source = kubectl_json(kubectl, kubeconfig, namespace, f"kafkatopic/{kubernetes_name(source_topic)}")
    dlq = kubectl_json(kubectl, kubeconfig, namespace, f"kafkatopic/{kubernetes_name(dlq_topic)}")
    kafka_monitor = kubectl_json(kubectl, kubeconfig, namespace, "podmonitor/kafka")
    kafka_spec = mapping((kafka or {}).get("spec"))
    kafka_runtime = mapping(kafka_spec.get("kafka"))
    kafka_config = mapping(kafka_runtime.get("config"))
    listeners = kafka_runtime.get("listeners", [])
    desired_pull_secrets = [
        str(value)
        for value in get(values, "global", "imagePullSecrets", default=[])
        if str(value).strip()
    ]
    kafka_pull_secrets = [
        str(mapping(item).get("name", ""))
        for item in get(kafka_runtime, "template", "pod", "imagePullSecrets", default=[])
        if isinstance(item, dict)
    ]
    listeners_match = (
        isinstance(listeners, list)
        and len(listeners) == 1
        and mapping(listeners[0]).get("tls") is True
        and get(listeners[0], "authentication", "type") == "tls"
    )
    pool_spec = mapping((pool or {}).get("spec"))
    pool_storage = mapping(pool_spec.get("storage"))
    pool_volumes = pool_storage.get("volumes", [])
    storage_matches = (
        pool_storage.get("type") == "jbod"
        and isinstance(pool_volumes, list)
        and len(pool_volumes) == 1
        and str(mapping(pool_volumes[0]).get("class", "")) == desired_storage_class
        and str(mapping(pool_volumes[0]).get("size", "")) == desired_storage_size
        and mapping(pool_volumes[0]).get("deleteClaim") is False
    )
    broker_live = bool(
        kafka
        and pool
        and source
        and dlq
        and reconciled_ready(kafka)
        and kafka_runtime.get("version") == strimzi.get("kafkaVersion")
        and kafka_runtime.get("image") == expected_kafka_image
        and get(kafka_spec, "kafkaExporter", "image") == expected_kafka_image
        and get(kafka_spec, "cruiseControl", "image") == expected_kafka_image
        and get(kafka_spec, "entityOperator", "topicOperator", "image") == expected_operator_image
        and get(kafka_spec, "entityOperator", "userOperator", "image") == expected_operator_image
        and operator_ready
        and str(get(kafka, "status", "kafkaVersion", default="")) == "4.3.0"
        and str(get(kafka, "status", "operatorLastSuccessfulVersion", default="")) == strimzi.get("operatorVersion")
        and broker_pods_ready
        and storage_class_ready
        and kafka_pvcs_ready
        and listeners_match
        and get(kafka_runtime, "authorization", "type") == "simple"
        and set(kafka_pull_secrets) == set(desired_pull_secrets)
        and int_at_least(kafka_config, "offsets.topic.replication.factor", 3)
        and int_at_least(kafka_config, "transaction.state.log.replication.factor", 3)
        and int_at_least(kafka_config, "transaction.state.log.min.isr", 2)
        and int_at_least(kafka_config, "default.replication.factor", 3)
        and int_at_least(kafka_config, "min.insync.replicas", 2)
        and scalar_equal(kafka_config.get("auto.create.topics.enable"), False)
        and scalar_equal(kafka_config.get("unclean.leader.election.enable"), False)
        and int(pool_spec.get("replicas", 0) or 0) == int(get(values, "messaging", "kafka", "replicas", default=0) or 0)
        and set(pool_spec.get("roles", [])) >= {"controller", "broker"}
        and storage_matches
        and len(get(pool, "status", "nodeIds", default=[])) >= 3
        and reconciled_ready(source)
        and topic_spec_matches(source, topic_definitions.get(source_topic, {}))
        and reconciled_ready(dlq)
        and topic_spec_matches(dlq, topic_definitions.get(dlq_topic, {}))
        and kafka_monitor
    )

    connect = kubectl_json(kubectl, kubeconfig, namespace, f"kafkaconnect/{connect_name}")
    connector = kubectl_json(kubectl, kubeconfig, namespace, f"kafkaconnector/{connector_name}")
    user = kubectl_json(kubectl, kubeconfig, namespace, f"kafkauser/{user_name}")
    external_secrets = mapping(get(values, "secretManagement", "externalSecrets", default={}))
    credential_secret_config = mapping(external_secrets.get("clickhouseSinkCredentials"))
    registry_secret_config = mapping(external_secrets.get("registryCredentials"))
    credential_target_name = str(credential_secret_config.get("targetName", "")).strip()
    registry_target_name = str(registry_secret_config.get("targetName", "")).strip()
    credential_target_type = str(credential_secret_config.get("type", "Opaque")).strip() or "Opaque"
    registry_target_type = str(
        registry_secret_config.get("type", "kubernetes.io/dockerconfigjson")
    ).strip() or "kubernetes.io/dockerconfigjson"
    credential_required_keys = {
        str(item.get("secretKey", "")).strip()
        for item in credential_secret_config.get("data", [])
        if isinstance(item, dict) and str(item.get("secretKey", "")).strip()
    }
    registry_required_keys = {
        str(item.get("secretKey", "")).strip()
        for item in registry_secret_config.get("data", [])
        if isinstance(item, dict) and str(item.get("secretKey", "")).strip()
    }
    credential_secret_namespace = str(
        credential_secret_config.get("namespace", namespace)
    ).strip() or namespace
    registry_secret_namespace = str(
        registry_secret_config.get("namespace", namespace)
    ).strip() or namespace
    secret_store_name = str(get(values, "secretManagement", "secretStoreRef", "name", default=""))
    secret_store_kind = str(get(values, "secretManagement", "secretStoreRef", "kind", default=""))
    secret_store_resource = (
        "clustersecretstore" if secret_store_kind == "ClusterSecretStore" else "secretstore"
    )
    secret_store = kubectl_json(
        kubectl,
        kubeconfig,
        namespace,
        f"{secret_store_resource}/{secret_store_name}",
    )
    credential_external_secret = kubectl_json(
        kubectl,
        kubeconfig,
        credential_secret_namespace,
        f"externalsecret/{external_secret_resource_name('clickhouseSinkCredentials')}",
    )
    registry_external_secret = kubectl_json(
        kubectl,
        kubeconfig,
        registry_secret_namespace,
        f"externalsecret/{external_secret_resource_name('registryCredentials')}",
    )
    credential_target_secret = kubectl_json(
        kubectl,
        kubeconfig,
        credential_secret_namespace,
        f"secret/{kubernetes_name(credential_target_name)}",
    )
    registry_target_secret = kubectl_json(
        kubectl,
        kubeconfig,
        registry_secret_namespace,
        f"secret/{kubernetes_name(registry_target_name)}",
    )
    connect_monitor = kubectl_json(kubectl, kubeconfig, namespace, f"podmonitor/{connect_name}")
    prometheus_rule = kubectl_json(kubectl, kubeconfig, namespace, "prometheusrule/urban-platform-slo")
    clickhouse_network_policy = kubectl_json(
        kubectl,
        kubeconfig,
        namespace,
        f"networkpolicy/{connect_name}-clickhouse-egress",
    )
    connector_status = mapping(get(connector or {}, "status", "connectorStatus", default={}))
    connector_state = str(get(connector_status, "connector", "state", default="")).upper()
    tasks = connector_status.get("tasks", [])
    source_partitions = int(get(topic_definitions.get(source_topic, {}), "partitions", default=0) or 0)
    tasks_max = int(connector_config.get("tasksMax", 0) or 0)
    expected_tasks = min(source_partitions, tasks_max)
    tasks_running = (
        expected_tasks > 0
        and len(tasks) == expected_tasks
        and all(str(mapping(task).get("state", "")).upper() == "RUNNING" for task in tasks)
    )
    connector_plugins = get(connect or {}, "status", "connectorPlugins", default=[])
    plugin_present = any(
        mapping(plugin).get("class") == connector_config.get("class")
        for plugin in connector_plugins
    )
    connect_spec = mapping((connect or {}).get("spec"))
    connect_runtime_config = mapping(connect_spec.get("config"))
    connect_pull_secrets = [
        str(mapping(item).get("name", ""))
        for item in get(connect_spec, "template", "pod", "imagePullSecrets", default=[])
        if isinstance(item, dict)
    ]
    expected_image = expected_connect_image(values, connect_config)
    connect_replicas = int(connect_config.get("replicas", 0) or 0)
    connect_pods = [
        pod
        for pod in pods
        if get(pod, "metadata", "labels", "strimzi.io/cluster") == connect_name
    ]
    connect_pods_ready = distributed_ready_pods(
        connect_pods,
        nodes,
        connect_replicas,
        topology_key,
        expected_image,
    )
    connect_spec_matches = all(
        (
            connect_spec.get("version") == strimzi.get("kafkaVersion"),
            int(connect_spec.get("replicas", 0) or 0) == int(connect_config.get("replicas", 0) or 0),
            connect_spec.get("bootstrapServers") == "kafka-kafka-bootstrap:9093",
            connect_spec.get("groupId") == connect_config.get("groupId"),
            connect_spec.get("configStorageTopic") == connect_config.get("configStorageTopic"),
            connect_spec.get("offsetStorageTopic") == connect_config.get("offsetStorageTopic"),
            connect_spec.get("statusStorageTopic") == connect_config.get("statusStorageTopic"),
            connect_spec.get("image") == expected_image,
            set(connect_pull_secrets) == set(desired_pull_secrets),
            get(connect_spec, "authentication", "type") == "tls",
            bool(get(connect_spec, "tls", "trustedCertificates", default=[])),
            int_at_least(connect_runtime_config, "config.storage.replication.factor", 3),
            int_at_least(connect_runtime_config, "offset.storage.replication.factor", 3),
            int_at_least(connect_runtime_config, "status.storage.replication.factor", 3),
        )
    )
    connector_spec = mapping((connector or {}).get("spec"))
    live_connector_config = mapping(connector_spec.get("config"))
    expected_group = str(connector_config.get("consumerGroup", ""))
    expected_connector_values = {
        "topics": source_topic,
        "topic2TableMap": f"{source_topic}={connector_config.get('table', '')}",
        "hostname": connector_config.get("hostname"),
        "port": connector_config.get("port"),
        "exactlyOnce": connector_config.get("exactlyOnce"),
        "ignorePartitionsWhenBatching": connector_config.get("ignorePartitionsWhenBatching"),
        "errors.deadletterqueue.topic.name": dlq_topic,
        "consumer.override.group.id": expected_group,
        "consumer.override.isolation.level": get(connector_config, "consumer", "isolationLevel"),
    }
    connector_spec_matches = all(
        (
            connector_spec.get("class") == connector_config.get("class"),
            int(connector_spec.get("tasksMax", 0) or 0) == tasks_max,
            str(connector_spec.get("state", "")).lower() == "running",
            get(connector_spec, "autoRestart", "enabled") is True,
            all(
                scalar_equal(live_connector_config.get(key), expected)
                for key, expected in expected_connector_values.items()
            ),
            "async_insert=1" in str(live_connector_config.get("clickhouseSettings", "")),
            "wait_for_async_insert=1" in str(live_connector_config.get("clickhouseSettings", "")),
        )
    )
    keeper_on_cluster = str(connector_config.get("keeperOnCluster", "")).strip()
    if keeper_on_cluster:
        connector_spec_matches = connector_spec_matches and live_connector_config.get("keeperOnCluster") == keeper_on_cluster
    user_spec = mapping((user or {}).get("spec"))
    user_acls = get(user_spec, "authorization", "acls", default=[])
    user_spec_matches = all(
        (
            get(user_spec, "authentication", "type") == "tls",
            get(user_spec, "authorization", "type") == "simple",
            acl_allows(user_acls, "group", str(connect_config.get("groupId", "")), {"Read"}),
            acl_allows(user_acls, "group", expected_group, {"Read"}),
            acl_allows(user_acls, "topic", source_topic, {"Read", "Describe"}),
            acl_allows(user_acls, "topic", dlq_topic, {"Write", "Describe"}),
            not acl_allows(user_acls, "cluster", None, {"IdempotentWrite"}),
        )
    )
    expected_egress_cidrs = {
        str(value)
        for value in get(connect_config, "networkPolicy", "egressCidrs", default=[])
    }
    network_policy_spec = mapping((clickhouse_network_policy or {}).get("spec"))
    actual_egress_cidrs = {
        str(get(target, "ipBlock", "cidr", default=""))
        for rule in network_policy_spec.get("egress", [])
        for target in mapping(rule).get("to", [])
        if get(target, "ipBlock", "cidr")
    }
    actual_egress_ports = {
        int(mapping(port).get("port", 0) or 0)
        for rule in network_policy_spec.get("egress", [])
        for port in mapping(rule).get("ports", [])
    }
    network_policy_matches = all(
        (
            bool(clickhouse_network_policy),
            expected_egress_cidrs == actual_egress_cidrs,
            int(connector_config.get("port", 0) or 0) in actual_egress_ports,
        )
    )
    alert_names = {
        str(mapping(rule).get("alert", ""))
        for group in get(prometheus_rule or {}, "spec", "groups", default=[])
        for rule in mapping(group).get("rules", [])
        if mapping(rule).get("alert")
    }
    observability_matches = all(
        (
            bool(kafka_monitor),
            bool(connect_monitor),
            {
                "UrbanPlatformKafkaUnderReplicatedPartitions",
                "UrbanPlatformClickHouseSinkConsumerLagHigh",
                "UrbanPlatformClickHouseSinkDeadLetterQueueActive",
            }
            <= alert_names,
        )
    )
    connect_live = bool(
        connect
        and connector
        and user
        and reconciled_ready(connect)
        and reconciled_ready(connector)
        and reconciled_ready(user)
        and credential_external_secret
        and condition_ready_if_observed(credential_external_secret)
        and external_secret_target_matches(credential_external_secret, credential_target_name)
        and target_secret_matches(
            credential_target_secret,
            credential_target_name,
            credential_target_type,
            credential_required_keys,
        )
        and registry_external_secret
        and condition_ready_if_observed(registry_external_secret)
        and external_secret_target_matches(registry_external_secret, registry_target_name)
        and target_secret_matches(
            registry_target_secret,
            registry_target_name,
            registry_target_type,
            registry_required_keys,
        )
        and secret_store
        and condition_ready_if_observed(secret_store)
        and connect_spec_matches
        and connect_pods_ready
        and int(get(connect, "status", "replicas", default=0) or 0) == int(connect_config.get("replicas", 0) or 0)
        and plugin_present
        and connector_spec_matches
        and user_spec_matches
        and network_policy_matches
        and observability_matches
        and connector_state == "RUNNING"
        and tasks_running
    )
    return [
        Check("Live broker and topic readiness", 8, broker_live, "Kafka 4.3, retained expandable storage, three failure-domain broker pods/PVCs, and both managed topics match the requested private profile", True),
        Check("Live Connect and ClickHouse sink readiness", 8, connect_live, "three failure-domain Connect workers, a Ready external secret store, the immutable image, exact ACLs/config, reviewed plugin, and all sink tasks match the requested profile", True),
    ]


def render_report(checks: list[Check], minimum: int) -> str:
    score = sum(check.weight for check in checks if check.passed)
    critical_failures = [check.name for check in checks if check.critical and not check.passed]
    passed = score >= minimum and not critical_failures
    lines = [
        "# Kafka to ClickHouse Readiness",
        "",
        "This report never reads or prints Secret values, private endpoints, or kubeconfig content.",
        "",
        f"- Result: `{'PASS' if passed else 'FAIL'}`",
        f"- Score: `{score}/100`",
        f"- Required score: `{minimum}/100`",
        f"- Critical failures: `{len(critical_failures)}`",
        "",
        "| Check | Weight | Status | Detail |",
        "|---|---:|---|---|",
    ]
    for check in checks:
        lines.append(f"| {check.name} | {check.weight} | {'PASS' if check.passed else 'FAIL'} | {check.detail} |")
    lines.extend(
        [
            "",
            "A score below 92 is not enterprise-ready. Live checks and private deployment inputs are required; repository YAML alone cannot earn the threshold.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score Kafka-to-ClickHouse production readiness.")
    parser.add_argument("--base-values", default=str(ROOT / "helm/urban-platform-infra/values.yaml"))
    parser.add_argument("--production-values", default=str(ROOT / "helm/urban-platform-infra/values-production.yaml"))
    parser.add_argument("--private-values", default="")
    parser.add_argument("--kubeconfig", default="")
    parser.add_argument("--namespace", default="urban-platform")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--minimum", type=int, default=100)
    parser.add_argument("--output", default=str(ROOT / "reports/kafka-clickhouse-readiness.md"))
    args = parser.parse_args(argv)

    if not 0 <= args.minimum <= 100:
        parser.error("--minimum must be between 0 and 100")
    try:
        values = merge(load_yaml(Path(args.base_values)), load_yaml(Path(args.production_values)))
        if args.private_values:
            values = merge(values, load_yaml(Path(args.private_values)))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Kafka-to-ClickHouse readiness inputs are invalid: {exc}", file=sys.stderr)
        return 2

    kubeconfig = Path(args.kubeconfig).expanduser() if args.kubeconfig else None
    checks = static_checks(values) + live_checks(values, kubeconfig, args.namespace, args.live)
    report = render_report(checks, args.minimum)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")

    score = sum(check.weight for check in checks if check.passed)
    critical_failures = [check for check in checks if check.critical and not check.passed]
    print(f"Kafka-to-ClickHouse readiness report written: {output}")
    print(f"Kafka-to-ClickHouse readiness score: {score}/100 (required: {args.minimum}/100)")
    return 0 if score >= args.minimum and not critical_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
