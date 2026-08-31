#!/usr/bin/env python3
"""Check the rendered production chart for HA, durability, and recovery controls."""
from __future__ import annotations

import argparse
import ipaddress
import re
import sys
from pathlib import Path
from typing import Any

import yaml


KUBERNETES_NAME = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$")
PSA_VERSION = re.compile(r"^v1\.[0-9]+$")
MIN_DATABASE_BYTES = 20 * 1024**3


def quantity_bytes(value: Any) -> int:
    match = re.fullmatch(r"(\d+)(Ki|Mi|Gi|Ti)", str(value or ""))
    if not match:
        return 0
    units = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4}
    return int(match.group(1)) * units[match.group(2)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate rendered production manifests.")
    parser.add_argument("rendered_manifest")
    args = parser.parse_args(argv)

    path = Path(args.rendered_manifest)
    if not path.is_file():
        print(f"Missing rendered manifest: {path}", file=sys.stderr)
        return 2

    documents = [doc for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")) if isinstance(doc, dict)]
    errors: list[str] = []
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for document in documents:
        by_kind.setdefault(str(document.get("kind", "")), []).append(document)
        metadata = document.get("metadata", {})
        name = metadata.get("name")
        if name and not KUBERNETES_NAME.fullmatch(str(name)):
            errors.append(f"{document.get('kind')}/{name}: metadata.name is not a DNS-compatible Kubernetes name")

    namespaces = by_kind.get("Namespace", [])
    if not namespaces:
        errors.append("production render must include the target Namespace")
    else:
        labels = namespaces[0].get("metadata", {}).get("labels", {})
        for mode in ("enforce", "audit", "warn"):
            if labels.get(f"pod-security.kubernetes.io/{mode}") != "restricted":
                errors.append(f"Namespace: pod-security {mode} must be restricted")
            version = labels.get(f"pod-security.kubernetes.io/{mode}-version")
            if not PSA_VERSION.fullmatch(str(version or "")):
                errors.append(f"Namespace: pod-security {mode} version must be pinned as v1.<minor>")

    if by_kind.get("Secret"):
        errors.append("plain Kubernetes Secret manifests must not be rendered")

    ingresses = by_kind.get("Ingress", [])
    secure_ingresses = [
        item for item in ingresses if item.get("spec", {}).get("tls")
    ]
    if not ingresses or not secure_ingresses:
        errors.append("Ingress: production must render at least one TLS-enabled route")
    for ingress in ingresses:
        spec = ingress.get("spec", {})
        if spec.get("ingressClassName") != "traefik":
            errors.append(f"Ingress/{ingress.get('metadata', {}).get('name', '<unknown>')}: production must use the Traefik ingress class")
        if spec.get("tls"):
            if any(
                item.get("secretName") != "urban-platform-tls"
                for item in spec.get("tls", [])
                if isinstance(item, dict)
            ):
                errors.append(f"Ingress/{ingress.get('metadata', {}).get('name', '<unknown>')}: wrong TLS Secret is referenced")
            continue
        annotations = ingress.get("metadata", {}).get("annotations", {})
        if (
            annotations.get("traefik.ingress.kubernetes.io/router.entrypoints") != "web"
            or "redirect-https@kubernetescrd"
            not in str(annotations.get("traefik.ingress.kubernetes.io/router.middlewares", ""))
        ):
            errors.append(f"Ingress/{ingress.get('metadata', {}).get('name', '<unknown>')}: plaintext route is not an explicit HTTPS redirect")

    expected_quota = {
        "requests.cpu": "12",
        "requests.memory": "32Gi",
        "limits.cpu": "20",
        "limits.memory": "40Gi",
        "requests.storage": "2Ti",
        "persistentvolumeclaims": "100",
        "pods": "300",
    }
    quota_items = by_kind.get("ResourceQuota", [])
    if not any(
        all(str(item.get("spec", {}).get("hard", {}).get(key, "")).strip() == value for key, value in expected_quota.items())
        for item in quota_items
    ):
        errors.append("ResourceQuota: production quota must enforce the reviewed CPU, memory, storage, PVC, and pod ceilings")

    expected_limit_default = {"cpu": "1", "memory": "1Gi", "ephemeral-storage": "2Gi"}
    expected_limit_request = {"cpu": "100m", "memory": "256Mi", "ephemeral-storage": "512Mi"}
    limit_range_items = by_kind.get("LimitRange", [])
    if not any(
        any(
            entry.get("type") == "Container"
            and all(str(entry.get("default", {}).get(key, "")).strip() == value for key, value in expected_limit_default.items())
            and all(str(entry.get("defaultRequest", {}).get(key, "")).strip() == value for key, value in expected_limit_request.items())
            for entry in item.get("spec", {}).get("limits", [])
            if isinstance(entry, dict)
        )
        for item in limit_range_items
    ):
        errors.append("LimitRange: production default container requests and limits are missing or drifted")

    release_identity = next(
        (
            item
            for item in by_kind.get("ConfigMap", [])
            if item.get("metadata", {}).get("name") == "urban-platform-release-identity"
        ),
        None,
    )
    if release_identity is None:
        errors.append("ConfigMap/urban-platform-release-identity: signed release identity is missing")
    elif set(release_identity.get("data", {})) != {"releaseTag", "sourceRevision", "deploymentId"}:
        errors.append("ConfigMap/urban-platform-release-identity: release tag, source revision, and deployment ID keys are required")

    for workload in by_kind.get("Deployment", []) + by_kind.get("StatefulSet", []):
        name = workload.get("metadata", {}).get("name", "<unknown>")
        spec = workload.get("spec", {})
        if int(spec.get("replicas", 0)) < 3:
            errors.append(f"{workload.get('kind')}/{name}: production replicas must be at least 3")
        pod_spec = spec.get("template", {}).get("spec", {})
        constraints = pod_spec.get("topologySpreadConstraints", [])
        if not any(item.get("whenUnsatisfiable") == "DoNotSchedule" for item in constraints):
            errors.append(f"{workload.get('kind')}/{name}: DoNotSchedule topology spread is missing")
        affinity = pod_spec.get("affinity", {}).get("podAntiAffinity", {})
        if not affinity.get("requiredDuringSchedulingIgnoredDuringExecution"):
            errors.append(f"{workload.get('kind')}/{name}: required pod anti-affinity is missing")

    database_clusters = [
        document
        for document in by_kind.get("Cluster", [])
        if str(document.get("apiVersion", "")).startswith("postgresql.cnpg.io/")
    ]
    if not database_clusters:
        errors.append("production render must include CNPG database clusters")
    for cluster in database_clusters:
        name = cluster.get("metadata", {}).get("name", "<unknown>")
        spec = cluster.get("spec", {})
        storage = spec.get("storage", {})
        backup = spec.get("backup", {})
        if int(spec.get("instances", 0)) < 3:
            errors.append(f"Cluster/{name}: CNPG instances must be at least 3")
        if storage.get("storageClass") != "production-durable":
            errors.append(f"Cluster/{name}: durable storage class is missing")
        if quantity_bytes(storage.get("size")) < MIN_DATABASE_BYTES:
            errors.append(f"Cluster/{name}: storage must be at least 20Gi")
        if not backup.get("barmanObjectStore"):
            errors.append(f"Cluster/{name}: object-store backup configuration is missing")

    scheduled_backups = by_kind.get("ScheduledBackup", [])
    cluster_names = {item.get("metadata", {}).get("name") for item in database_clusters}
    backup_cluster_names = {
        item.get("spec", {}).get("cluster", {}).get("name") for item in scheduled_backups
    }
    if len(scheduled_backups) != len(database_clusters) or backup_cluster_names != cluster_names:
        errors.append("every CNPG cluster must have exactly one ScheduledBackup")

    for elasticsearch in by_kind.get("Elasticsearch", []):
        name = elasticsearch.get("metadata", {}).get("name", "<unknown>")
        for node_set in elasticsearch.get("spec", {}).get("nodeSets", []):
            for volume_claim in node_set.get("volumeClaimTemplates", []):
                storage_class = volume_claim.get("spec", {}).get("storageClassName")
                if storage_class != "production-durable":
                    errors.append(f"Elasticsearch/{name}: durable storage class is missing")

    pdb_names = {item.get("metadata", {}).get("name") for item in by_kind.get("PodDisruptionBudget", [])}
    for name in ("redis", "webserver-nginx", "zabbix-agent2"):
        if name not in pdb_names:
            errors.append(f"PodDisruptionBudget/{name}: production disruption budget is missing")

    hpa_names = {item.get("metadata", {}).get("name") for item in by_kind.get("HorizontalPodAutoscaler", [])}
    if "webserver-nginx" not in hpa_names:
        errors.append("HorizontalPodAutoscaler/webserver-nginx: production autoscaling is missing")

    external_secret_names = {
        item.get("metadata", {}).get("name") for item in by_kind.get("ExternalSecret", [])
    }
    for name in ("database-backup-credentials", "velero-backup-credentials", "clickhouse-sink-credentials", "registry-credentials", "ingress-tls"):
        if name not in external_secret_names:
            errors.append(f"ExternalSecret/{name}: production credential delivery is missing")
    ingress_tls_external = next(
        (item for item in by_kind.get("ExternalSecret", []) if item.get("metadata", {}).get("name") == "ingress-tls"),
        None,
    )
    if ingress_tls_external:
        target = ingress_tls_external.get("spec", {}).get("target", {})
        if target.get("name") != "urban-platform-tls" or target.get("template", {}).get("type") != "kubernetes.io/tls":
            errors.append("ExternalSecret/ingress-tls: TLS target Secret contract is incomplete")
        tls_keys = {
            item.get("secretKey") for item in ingress_tls_external.get("spec", {}).get("data", [])
            if isinstance(item, dict)
        }
        if tls_keys < {"tls.crt", "tls.key"}:
            errors.append("ExternalSecret/ingress-tls: both TLS key material fields are required")

    pod_monitor_names = {item.get("metadata", {}).get("name") for item in by_kind.get("PodMonitor", [])}
    for name in ("kafka", "clickhouse-connect"):
        if name not in pod_monitor_names:
            errors.append(f"PodMonitor/{name}: production metrics discovery is missing")

    kafka = next(iter(by_kind.get("Kafka", [])), None)
    node_pool = next(iter(by_kind.get("KafkaNodePool", [])), None)
    if not kafka or kafka.get("spec", {}).get("kafka", {}).get("version") != "4.3.0":
        errors.append("Kafka: Apache Kafka 4.3.0 is not rendered")
    elif kafka:
        kafka_spec = kafka.get("spec", {}).get("kafka", {})
        expected_kafka_image = "quay.io/strimzi/kafka:1.1.0-kafka-4.3.0"
        expected_operator_image = "quay.io/strimzi/operator:1.1.0"
        if kafka_spec.get("image") != expected_kafka_image:
            errors.append("Kafka: the reviewed Strimzi Apache Kafka image override is not rendered")
        if kafka.get("spec", {}).get("kafkaExporter", {}).get("image") != expected_kafka_image:
            errors.append("Kafka: Kafka Exporter must use the reviewed Kafka image")
        if kafka.get("spec", {}).get("cruiseControl", {}).get("image") != expected_kafka_image:
            errors.append("Kafka: Cruise Control must use the reviewed Kafka image")
        entity_operator = kafka.get("spec", {}).get("entityOperator", {})
        if entity_operator.get("topicOperator", {}).get("image") != expected_operator_image:
            errors.append("Kafka: Topic Operator must use the reviewed Strimzi operator image")
        if entity_operator.get("userOperator", {}).get("image") != expected_operator_image:
            errors.append("Kafka: User Operator must use the reviewed Strimzi operator image")
        kafka_pull_secrets = {
            item.get("name")
            for item in kafka_spec.get("template", {}).get("pod", {}).get("imagePullSecrets", [])
            if isinstance(item, dict)
        }
        if "registry-credentials" not in kafka_pull_secrets:
            errors.append("Kafka/kafka: private registry pull Secret is missing from the pod template")
        listeners = kafka_spec.get("listeners", [])
        if any(listener.get("tls") is not True for listener in listeners) or len(listeners) != 1:
            errors.append("Kafka: production must expose exactly one TLS-only listener")
        elif listeners[0].get("authentication", {}).get("type") != "tls":
            errors.append("Kafka: the production listener must require mutual TLS")
        if kafka_spec.get("authorization", {}).get("type") != "simple":
            errors.append("Kafka: Strimzi simple ACL authorization is required")
        if kafka_spec.get("rack", {}).get("topologyKey") != "topology.kubernetes.io/zone":
            errors.append("Kafka: zone-aware rack placement is required")
        kafka_config = kafka_spec.get("config", {})
        expected_config = {
            "offsets.topic.replication.factor": 3,
            "transaction.state.log.replication.factor": 3,
            "transaction.state.log.min.isr": 2,
            "default.replication.factor": 3,
            "min.insync.replicas": 2,
            "auto.create.topics.enable": False,
            "unclean.leader.election.enable": False,
        }
        for key, expected in expected_config.items():
            if kafka_config.get(key) != expected:
                errors.append(f"Kafka: {key} must equal {expected!r}")
        template = kafka_spec.get("template", {})
        pod_template = template.get("pod", {})
        if not any(item.get("whenUnsatisfiable") == "DoNotSchedule" for item in pod_template.get("topologySpreadConstraints", [])):
            errors.append("Kafka: required topology spread is missing")
        if not pod_template.get("affinity", {}).get("podAntiAffinity", {}).get("requiredDuringSchedulingIgnoredDuringExecution"):
            errors.append("Kafka: required pod anti-affinity is missing")
        if template.get("podDisruptionBudget", {}).get("maxUnavailable") != 1:
            errors.append("Kafka: maxUnavailable=1 disruption budget is required")
        if not kafka.get("spec", {}).get("kafkaExporter"):
            errors.append("Kafka: Kafka Exporter is required")
        if "cruiseControl" not in kafka.get("spec", {}):
            errors.append("Kafka: Cruise Control is required")
        if not kafka_spec.get("metricsConfig"):
            errors.append("Kafka: JMX metrics configuration is required")
    if not node_pool or int(node_pool.get("spec", {}).get("replicas", 0)) < 3:
        errors.append("KafkaNodePool: production Kafka requires at least 3 replicas")
    else:
        volumes = node_pool.get("spec", {}).get("storage", {}).get("volumes", [])
        if not volumes or volumes[0].get("class") != "production-durable" or volumes[0].get("deleteClaim") is not False:
            errors.append("KafkaNodePool: durable non-deleting storage is required")

    topics = {
        item.get("metadata", {}).get("annotations", {}).get("strimzi.io/topic-name"): item
        for item in by_kind.get("KafkaTopic", [])
    }
    source_topic = topics.get("beMobile")
    dlq_topic = topics.get("beMobile.clickhouse.dlq")
    for name, topic, partitions in (
        ("beMobile", source_topic, 6),
        ("beMobile.clickhouse.dlq", dlq_topic, 3),
    ):
        if not topic:
            errors.append(f"KafkaTopic/{name}: managed topic is missing")
            continue
        spec = topic.get("spec", {})
        if int(spec.get("partitions", 0)) < partitions or int(spec.get("replicas", 0)) < 3:
            errors.append(f"KafkaTopic/{name}: requires at least {partitions} partitions and three replicas")
        if int(spec.get("config", {}).get("min.insync.replicas", 0)) < 2:
            errors.append(f"KafkaTopic/{name}: min.insync.replicas must be at least two")

    kafka_user = next(iter(by_kind.get("KafkaUser", [])), None)
    if not kafka_user:
        errors.append("KafkaUser/clickhouse-connect: mTLS identity and ACLs are missing")
    else:
        user_spec = kafka_user.get("spec", {})
        if user_spec.get("authentication", {}).get("type") != "tls":
            errors.append("KafkaUser/clickhouse-connect: mTLS authentication is required")
        acls = user_spec.get("authorization", {}).get("acls", [])

        def has_acl(
            resource_type: str,
            resource_name: str | None,
            operations: set[str],
            pattern_type: str | None = None,
        ) -> bool:
            for acl in acls:
                resource = acl.get("resource", {})
                if resource.get("type") != resource_type:
                    continue
                if resource_name is not None and resource.get("name") != resource_name:
                    continue
                if pattern_type is not None and resource.get("patternType", "literal") != pattern_type:
                    continue
                if set(acl.get("operations", [])) >= operations:
                    return True
            return False

        if not has_acl("topic", "beMobile", {"Read", "Describe"}, "literal"):
            errors.append("KafkaUser/clickhouse-connect: source-topic read ACL is missing")
        if not has_acl("group", "clickhouse-connect", {"Read"}, "literal"):
            errors.append("KafkaUser/clickhouse-connect: worker coordination-group ACL is missing")
        if not has_acl("group", "connect-clickhouse-bemobile-sink", {"Read"}, "literal"):
            errors.append("KafkaUser/clickhouse-connect: sink consumer-group ACL is missing")
        for internal_topic in (
            "clickhouse-connect-configs",
            "clickhouse-connect-offsets",
            "clickhouse-connect-status",
        ):
            if not has_acl("topic", internal_topic, {"Create", "Read", "Write", "Describe"}, "literal"):
                errors.append(f"KafkaUser/clickhouse-connect: exact ACL for {internal_topic} is missing")
        if not has_acl("topic", "beMobile.clickhouse.dlq", {"Create", "Write", "Describe"}, "literal"):
            errors.append("KafkaUser/clickhouse-connect: DLQ write ACL is missing")
        if not has_acl("cluster", None, {"Describe"}):
            errors.append("KafkaUser/clickhouse-connect: cluster describe ACL is missing")
        if has_acl("cluster", None, {"IdempotentWrite"}):
            errors.append("KafkaUser/clickhouse-connect: deprecated sink IdempotentWrite privilege must not be granted")

    connect = next(iter(by_kind.get("KafkaConnect", [])), None)
    if not connect:
        errors.append("KafkaConnect/clickhouse-connect: production Connect cluster is missing")
    else:
        connect_spec = connect.get("spec", {})
        connect_pull_secrets = {
            item.get("name")
            for item in connect_spec.get("template", {}).get("pod", {}).get("imagePullSecrets", [])
            if isinstance(item, dict)
        }
        if "registry-credentials" not in connect_pull_secrets:
            errors.append("KafkaConnect/clickhouse-connect: private registry pull Secret is missing from the pod template")
        if int(connect_spec.get("replicas", 0)) < 3:
            errors.append("KafkaConnect/clickhouse-connect: at least three workers are required")
        if connect_spec.get("bootstrapServers") != "kafka-kafka-bootstrap:9093":
            errors.append("KafkaConnect/clickhouse-connect: TLS Kafka bootstrap address is required")
        if connect_spec.get("authentication", {}).get("type") != "tls" or not connect_spec.get("tls", {}).get("trustedCertificates"):
            errors.append("KafkaConnect/clickhouse-connect: broker mTLS is incomplete")
        image = str(connect_spec.get("image", ""))
        if not (image.endswith(":1.4.0") or "@sha256:" in image):
            errors.append("KafkaConnect/clickhouse-connect: connector image must be versioned at 1.4.0 or digest pinned")
        connect_config = connect_spec.get("config", {})
        for key in (
            "config.storage.replication.factor",
            "offset.storage.replication.factor",
            "status.storage.replication.factor",
        ):
            if int(connect_config.get(key, 0)) < 3:
                errors.append(f"KafkaConnect/clickhouse-connect: {key} must be at least three")
        if connect_config.get("connector.client.config.override.policy") != "All":
            errors.append("KafkaConnect/clickhouse-connect: connector client overrides must be explicitly enabled")
        if connect_config.get("config.providers.env.class") != "org.apache.kafka.common.config.provider.EnvVarConfigProvider":
            errors.append("KafkaConnect/clickhouse-connect: EnvVarConfigProvider is required")
        if not connect_spec.get("metricsConfig"):
            errors.append("KafkaConnect/clickhouse-connect: JMX metrics configuration is required")
        connect_template = connect_spec.get("template", {})
        connect_pod = connect_template.get("pod", {})
        if not any(item.get("whenUnsatisfiable") == "DoNotSchedule" for item in connect_pod.get("topologySpreadConstraints", [])):
            errors.append("KafkaConnect/clickhouse-connect: required topology spread is missing")
        if not connect_pod.get("affinity", {}).get("podAntiAffinity", {}).get("requiredDuringSchedulingIgnoredDuringExecution"):
            errors.append("KafkaConnect/clickhouse-connect: required pod anti-affinity is missing")
        if connect_template.get("podDisruptionBudget", {}).get("maxUnavailable") != 1:
            errors.append("KafkaConnect/clickhouse-connect: maxUnavailable=1 disruption budget is required")
        env = connect_template.get("connectContainer", {}).get("env", [])
        env_names = {
            item.get("name"): item.get("valueFrom", {}).get("secretKeyRef", {})
            for item in env if isinstance(item, dict)
        }
        for variable, key in (("CLICKHOUSE_USERNAME", "username"), ("CLICKHOUSE_PASSWORD", "password")):
            ref = env_names.get(variable, {})
            if ref.get("name") != "clickhouse-sink-credentials" or ref.get("key") != key:
                errors.append(f"KafkaConnect/clickhouse-connect: {variable} must come from the managed credential Secret")

    connector = next(iter(by_kind.get("KafkaConnector", [])), None)
    if not connector:
        errors.append("KafkaConnector/clickhouse-bemobile-sink: connector resource is missing")
    else:
        connector_spec = connector.get("spec", {})
        connector_config = connector_spec.get("config", {})
        if connector_spec.get("class") != "com.clickhouse.kafka.connect.ClickHouseSinkConnector":
            errors.append("KafkaConnector/clickhouse-bemobile-sink: official ClickHouse connector class is required")
        tasks_max = int(connector_spec.get("tasksMax", 0))
        source_partitions = int(source_topic.get("spec", {}).get("partitions", 0)) if source_topic else 0
        if tasks_max < 1 or tasks_max > source_partitions:
            errors.append("KafkaConnector/clickhouse-bemobile-sink: tasksMax must be positive and no greater than source partitions")
        if connector_spec.get("autoRestart", {}).get("enabled") is not True:
            errors.append("KafkaConnector/clickhouse-bemobile-sink: automatic restart is required")
        if connector_config.get("username") != "${env:CLICKHOUSE_USERNAME}" or connector_config.get("password") != "${env:CLICKHOUSE_PASSWORD}":
            errors.append("KafkaConnector/clickhouse-bemobile-sink: credentials must use EnvVarConfigProvider references")
        hostname = str(connector_config.get("hostname", ""))
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            errors.append("KafkaConnector/clickhouse-bemobile-sink: ClickHouse must use DNS instead of a fixed IP")
        expected_connector_config = {
            "ssl": "true",
            "jdbcConnectionProperties": "?sslmode=STRICT",
            "exactlyOnce": "true",
            "ignorePartitionsWhenBatching": "false",
            "bufferCount": "0",
            "bufferFlushTime": "0",
            "errors.tolerance": "all",
            "errors.log.include.messages": "false",
            "errors.deadletterqueue.topic.name": "beMobile.clickhouse.dlq",
            "errors.deadletterqueue.topic.replication.factor": "3",
            "consumer.override.group.id": "connect-clickhouse-bemobile-sink",
            "consumer.override.isolation.level": "read_committed",
        }
        for key, expected in expected_connector_config.items():
            if str(connector_config.get(key, "")).lower() != expected.lower():
                errors.append(f"KafkaConnector/clickhouse-bemobile-sink: {key} must equal {expected}")
        if int(connector_config.get("errors.retry.timeout", 0)) < 300000:
            errors.append("KafkaConnector/clickhouse-bemobile-sink: retry timeout must cover at least five minutes")
        if int(connector_config.get("consumer.override.max.poll.records", 0)) > 10000:
            errors.append("KafkaConnector/clickhouse-bemobile-sink: max.poll.records must remain at or below 10,000")
        clickhouse_settings = str(connector_config.get("clickhouseSettings", ""))
        if "async_insert=1" not in clickhouse_settings or "wait_for_async_insert=1" not in clickhouse_settings:
            errors.append("KafkaConnector/clickhouse-bemobile-sink: durable acknowledged async inserts are required")

    alert_rules = {
        rule.get("alert"): rule
        for resource in by_kind.get("PrometheusRule", [])
        for group in resource.get("spec", {}).get("groups", [])
        for rule in group.get("rules", [])
        if isinstance(rule, dict)
    }
    for alert in (
        "UrbanPlatformKafkaUnderReplicatedPartitions",
        "UrbanPlatformClickHouseSinkConsumerLagHigh",
        "UrbanPlatformClickHouseSinkDeadLetterQueueActive",
    ):
        if alert not in alert_rules:
            errors.append(f"PrometheusRule: required Kafka-to-ClickHouse alert {alert} is missing")
    lag_expression = str(alert_rules.get("UrbanPlatformClickHouseSinkConsumerLagHigh", {}).get("expr", ""))
    if 'consumergroup="connect-clickhouse-bemobile-sink"' not in lag_expression:
        errors.append("PrometheusRule: ClickHouse lag alert must target the sink task consumer group")

    if not by_kind.get("PrometheusRule"):
        errors.append("PrometheusRule: production alert rules are missing")

    if errors:
        for error in errors:
            print(f"PRODUCTION-RENDER: {error}", file=sys.stderr)
        print(f"Production render validation failed with {len(errors)} error(s).", file=sys.stderr)
        return 1

    print(
        "Production render checks passed: "
        f"{len(database_clusters)} CNPG clusters, {len(scheduled_backups)} scheduled backups, "
        f"{len(by_kind.get('PodDisruptionBudget', []))} PDBs, and HA Kafka controls."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
