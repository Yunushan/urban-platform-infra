#!/usr/bin/env python3
"""Validate the public production profile before it is rendered or deployed."""
from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - CI installs the pinned requirements.
    raise SystemExit("PyYAML is required to validate the production profile.") from exc


ROOT = Path(__file__).resolve().parents[1]


def load_mapping(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise SystemExit(f"{path} must contain a YAML mapping.")
    return value


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def get(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


def require(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def is_ip_literal(value: Any) -> bool:
    try:
        ipaddress.ip_address(str(value).strip())
    except ValueError:
        return False
    return True


def validate_values(values: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    require(errors, get(values, "global", "environment") == "production", "global.environment must be production")
    require(errors, get(values, "global", "releaseIdentity", "enabled") is True, "production release identity must be enabled")
    require(errors, get(values, "global", "defaultReplicas", default=0) >= 3, "global.defaultReplicas must be at least 3")
    require(errors, get(values, "global", "replicaOverride", default=None) is None, "global.replicaOverride must remain null so per-service HA replicas are preserved")
    require(errors, get(values, "global", "scheduling", "topologySpread") is True, "topology spread must be enabled")
    require(errors, get(values, "global", "scheduling", "topologySpreadWhenUnsatisfiable") == "DoNotSchedule", "production topology spread must use DoNotSchedule")
    require(errors, get(values, "global", "scheduling", "antiAffinity") == "required", "production anti-affinity must be required")
    require(errors, get(values, "global", "security", "runAsNonRoot") is True, "global security must require non-root workloads")
    require(errors, get(values, "global", "security", "allowPrivilegeEscalation") is False, "privilege escalation must be disabled")
    require(errors, set(get(values, "global", "security", "capabilities", "drop", default=[])) >= {"ALL"}, "all Linux capabilities must be dropped")
    require(errors, get(values, "global", "podSecurityContext", "enabled") is True, "pod security context must be enabled")
    require(errors, get(values, "global", "podSecurityContext", "seccompProfile", "type") == "RuntimeDefault", "RuntimeDefault seccomp must be required")

    require(errors, get(values, "runtimeHardening", "enabled") is True, "runtime hardening must be enabled")
    require(errors, get(values, "runtimeHardening", "enforcementMode") == "enforce", "runtime hardening must be enforcing")
    require(errors, get(values, "runtimeHardening", "workloadSecurity", "requireRunAsNonRoot") is True, "runtime hardening must require non-root workloads")
    require(errors, get(values, "runtimeHardening", "workloadSecurity", "requireRuntimeDefaultSeccomp") is True, "runtime hardening must require RuntimeDefault seccomp")
    require(errors, get(values, "runtimeHardening", "workloadSecurity", "requireDropAllCapabilities") is True, "runtime hardening must require drop-all capabilities")
    require(errors, get(values, "runtimeHardening", "workloadSecurity", "disallowPrivilegeEscalation") is True, "runtime hardening must disallow privilege escalation")
    require(errors, get(values, "runtimeHardening", "images", "requireDigestPins") is True, "production images must require digest pins")
    require(errors, get(values, "imagePromotionController", "enabled") is True, "image promotion must be enabled")
    for key in ("requireDigestPins", "requireVulnerabilityScan", "requireSbom", "requireSignatureOrAttestation", "requirePromotionRecord"):
        require(errors, get(values, "imagePromotionController", key) is True, f"image promotion must require {key}")

    require(errors, get(values, "networkConnectivity", "enabled") is True, "network connectivity policy must be enabled")
    require(errors, get(values, "networkConnectivity", "networkPolicy", "defaultDeny") is True, "network policy must default deny")
    require(errors, get(values, "networkConnectivity", "egress", "requireExplicitCidrs") is True, "external egress must use explicit CIDRs")
    require(errors, get(values, "networkConnectivity", "tls", "requireTrustedIssuer") is True, "TLS must require a trusted issuer")
    require(errors, get(values, "secretManagement", "enabled") is True, "external secret management must be enabled")
    require(errors, get(values, "secretManagement", "provider") in {"external-secrets", "vault"}, "production secrets must use an external provider")
    require(errors, get(values, "secretManagement", "providerAdapters", "kubernetesDirect", "enabled") is False, "direct Kubernetes secret import must be disabled in production")

    require(errors, get(values, "namespace", "podSecurity", "enforce") == "restricted", "namespace PSA enforce level must be restricted")
    require(errors, get(values, "namespace", "podSecurity", "audit") == "restricted", "namespace PSA audit level must be restricted")
    require(errors, get(values, "namespace", "podSecurity", "warn") == "restricted", "namespace PSA warn level must be restricted")
    require(errors, get(values, "storageTiers", "hot", "enabled") is True, "durable hot storage tier must be enabled")
    hot_storage_class = get(values, "storageTiers", "hot", "storageClassName")
    require(errors, bool(hot_storage_class), "production must name a durable hot StorageClass")

    require(errors, get(values, "backup", "enabled") is True, "backup automation must be enabled")
    require(errors, get(values, "backup", "profile") == "production", "backup profile must be production")
    require(errors, get(values, "backup", "velero", "enabled") is True, "Velero backup integration must be enabled")
    require(errors, get(values, "backup", "velero", "installOperator") is True, "Velero operator installation must be enabled")
    require(errors, get(values, "backup", "velero", "snapshotsEnabled") is True, "volume snapshots must be enabled")
    require(errors, get(values, "backup", "rke2Etcd", "enabled") is True, "RKE2 etcd backups must be enabled")
    require(errors, get(values, "backup", "imageArchives", "enabled") is True, "image archive retention must be enabled")

    require(errors, get(values, "databases", "storageOverride", "className") == hot_storage_class, "database storage must use the durable hot StorageClass")
    database_size = str(get(values, "databases", "storageOverride", "size", default="0Gi"))
    require(errors, database_size not in {"", "0Gi", "1Gi"}, "database storage must be larger than the lab default")
    require(errors, get(values, "databases", "backup", "enabled") is True, "CNPG database backups must be enabled")
    require(errors, get(values, "databases", "backup", "objectStore", "enabled") is True, "CNPG backups must use an object store")
    require(errors, bool(get(values, "databases", "backup", "objectStore", "bucket")), "CNPG backups must name an object-store bucket")
    require(errors, get(values, "databases", "backup", "objectStore", "secretRef", "name") == "production-backup-credentials", "CNPG backups must use the production backup credential target")
    require(errors, get(values, "databases", "backup", "schedule", "enabled") is True, "CNPG scheduled backups must be enabled")

    external_secrets = get(values, "secretManagement", "externalSecrets", default={})
    require(errors, isinstance(external_secrets, dict), "production must define ExternalSecret resources")
    for name in ("databaseBackupCredentials", "veleroBackupCredentials"):
        secret = external_secrets.get(name, {}) if isinstance(external_secrets, dict) else {}
        require(errors, secret.get("enabled") is True, f"ExternalSecret/{name} must be enabled")
        require(errors, secret.get("targetName") == "production-backup-credentials", f"ExternalSecret/{name} must target production-backup-credentials")
        require(errors, bool(secret.get("namespace")), f"ExternalSecret/{name} must declare its namespace")
        require(errors, bool(secret.get("data")), f"ExternalSecret/{name} must declare remote data mappings")

    require(errors, get(values, "observability", "prometheus", "enabled") is True, "Prometheus must be enabled for production")
    require(errors, get(values, "monitoring", "enabled") is True, "monitoring must be enabled for production")
    require(errors, get(values, "monitoring", "prometheusRules", "enabled") is True, "PrometheusRule generation must be enabled")
    require(errors, get(values, "webserver", "providers", "nginx", "autoscaling", "enabled") is True, "webserver autoscaling must be enabled")

    for section in ("accessGovernance", "complianceEvidence", "incidentResponse", "changeManagement", "cutoverGates", "smokeTesting", "releaseRunbook", "clusterUpgrade", "disasterRecovery"):
        require(errors, get(values, section, "enabled") is True, f"{section} must be enabled for production")
    require(errors, get(values, "smokeTesting", "probes", "databaseConnections") is True, "smoke tests must check database connections")
    require(errors, get(values, "smokeTesting", "probes", "messagingConnections") is True, "smoke tests must check messaging connections")
    require(errors, get(values, "disasterRecovery", "restoreDrills", "requireDatabaseRestore") is True, "DR must require a database restore drill")
    require(errors, get(values, "disasterRecovery", "restoreDrills", "requireEtcdRestore") is True, "DR must require an etcd restore drill")

    require(errors, get(values, "messaging", "kafka", "provider") == "strimzi", "production Kafka provider must be Strimzi")
    require(errors, get(values, "messaging", "kafka", "replicas", default=0) >= 3, "Kafka must have at least three brokers")
    require(errors, get(values, "messaging", "kafka", "compatibilitySecurityContext") is False, "Kafka compatibility security mode must be disabled")
    require(errors, get(values, "messaging", "kafka", "strimzi", "kafkaVersion") == "4.3.0", "production Kafka version must be 4.3.0")
    strimzi = get(values, "messaging", "kafka", "strimzi", default={})
    require(errors, get(strimzi, "operatorVersion") == "1.1.0", "Apache Kafka 4.3.0 requires the reviewed Strimzi 1.1.0 operator")
    require(errors, get(strimzi, "operatorNamespace") == "strimzi-system", "production Strimzi operator namespace must be explicit")
    require(errors, get(strimzi, "operatorImage", "repository") == "quay.io/strimzi/operator", "production Strimzi operator image repository must be explicit")
    require(errors, get(strimzi, "operatorImage", "tag") == "1.1.0", "production Strimzi operator image tag must match the operator version")
    require(errors, get(strimzi, "useCustomKafkaImage") is True, "production Strimzi must consume the promoted Kafka image override")
    require(errors, get(strimzi, "listeners", "plain", "enabled") is False, "production Kafka must disable its plaintext listener")
    require(errors, get(strimzi, "listeners", "tls", "enabled") is True, "production Kafka must enable its TLS listener")
    require(errors, get(strimzi, "listeners", "tls", "authentication") == "tls", "production Kafka clients must use mutual TLS")
    require(errors, get(strimzi, "authorization", "enabled") is True, "production Kafka authorization must be enabled")
    require(errors, get(strimzi, "authorization", "type") == "simple", "production Kafka must enforce Strimzi simple ACL authorization")
    require(errors, get(strimzi, "rack", "enabled") is True, "production Kafka must use rack-aware placement")
    require(errors, get(strimzi, "rack", "topologyKey") == "topology.kubernetes.io/zone", "production Kafka rack awareness must use zone labels")
    require(errors, get(strimzi, "brokerConfig", "autoCreateTopics") is False, "production Kafka must disable automatic topic creation")
    require(errors, get(strimzi, "brokerConfig", "uncleanLeaderElection") is False, "production Kafka must disable unclean leader election")
    require(errors, get(strimzi, "scheduling", "enabled") is True, "production Kafka must enforce zone and host placement")
    require(errors, get(strimzi, "kafkaExporter", "enabled") is True, "Kafka exporter must be enabled")
    require(errors, get(strimzi, "cruiseControl", "enabled") is True, "Kafka Cruise Control must be enabled")
    require(errors, get(strimzi, "metrics", "enabled") is True, "Kafka JMX metrics must be enabled")

    topics = get(strimzi, "topics", "definitions", default=[])
    require(errors, get(strimzi, "topics", "enabled") is True, "production Kafka topics must be operator managed")
    topic_by_name = {
        str(item.get("name")): item for item in topics if isinstance(item, dict) and item.get("name")
    }
    source_topic = topic_by_name.get("beMobile", {})
    dlq_topic = topic_by_name.get("beMobile.clickhouse.dlq", {})
    require(errors, int(source_topic.get("partitions", 0) or 0) >= 6, "ClickHouse source topic must have at least six partitions")
    require(errors, int(source_topic.get("replicas", 0) or 0) >= 3, "ClickHouse source topic must have three replicas")
    require(errors, int(get(source_topic, "config", "min.insync.replicas", default=0) or 0) >= 2, "ClickHouse source topic must require two in-sync replicas")
    require(errors, int(dlq_topic.get("partitions", 0) or 0) >= 3, "ClickHouse DLQ must have at least three partitions")
    require(errors, int(dlq_topic.get("replicas", 0) or 0) >= 3, "ClickHouse DLQ must have three replicas")
    require(errors, int(get(dlq_topic, "config", "min.insync.replicas", default=0) or 0) >= 2, "ClickHouse DLQ must require two in-sync replicas")

    connect = get(strimzi, "connect", default={})
    connector = get(connect, "connector", default={})
    require(errors, get(connect, "enabled") is True, "production Kafka Connect must be enabled")
    require(errors, int(get(connect, "replicas", default=0) or 0) >= 3, "production Kafka Connect must have at least three workers")
    require(errors, get(connect, "authentication", "type") == "tls", "Kafka Connect must authenticate with mutual TLS")
    require(errors, bool(get(connect, "credentialsSecret", "name")), "Kafka Connect must reference a ClickHouse credential Secret")
    require(errors, get(connect, "build", "enabled") is False, "production must use a promoted Kafka Connect image instead of in-cluster builds")
    require(errors, get(connect, "image", "tag") == "1.4.0", "production must use the reviewed ClickHouse connector 1.4.0 image")
    require(errors, get(connect, "metrics", "enabled") is True, "Kafka Connect JMX metrics must be enabled")
    require(errors, get(connect, "networkPolicy", "enabled") is True, "Kafka Connect must use an explicit ClickHouse egress policy")
    image_pull_secrets = get(values, "global", "imagePullSecrets", default=[])
    require(errors, isinstance(image_pull_secrets, list) and bool(image_pull_secrets), "production must declare a registry pull Secret")
    require(errors, get(connector, "enabled") is True, "ClickHouse KafkaConnector must be enabled")
    require(errors, get(connector, "class") == "com.clickhouse.kafka.connect.ClickHouseSinkConnector", "the official ClickHouse sink connector class is required")
    tasks_max = int(get(connector, "tasksMax", default=0) or 0)
    source_partitions = int(source_topic.get("partitions", 0) or 0)
    require(errors, tasks_max > 0, "ClickHouse connector tasksMax must be positive")
    require(errors, source_partitions > 0 and tasks_max <= source_partitions, "ClickHouse connector tasksMax must not exceed source topic partitions")
    require(errors, get(connector, "topic") == "beMobile", "ClickHouse connector must consume the managed source topic")
    require(errors, get(connector, "ssl") is True, "ClickHouse transport must use TLS")
    require(errors, get(connector, "jdbcConnectionProperties") == "?sslmode=STRICT", "ClickHouse TLS must enforce strict certificate validation")
    require(errors, not is_ip_literal(get(connector, "hostname", default="")), "ClickHouse must use a DNS name rather than a fixed IP address")
    require(errors, int(get(connector, "port", default=0) or 0) not in {0, 8123}, "ClickHouse must not use the plaintext HTTP port")
    require(errors, get(connector, "exactlyOnce") is True, "ClickHouse exactly-once delivery must be enabled")
    require(errors, get(connector, "ignorePartitionsWhenBatching") is False, "partition identity must be preserved while batching")
    require(errors, int(get(connector, "bufferCount", default=-1) or 0) == 0, "internal connector buffering must be disabled with exactly-once delivery")
    require(errors, int(get(connector, "bufferFlushTimeMs", default=-1) or 0) == 0, "connector buffer flush timing must remain disabled with exactly-once delivery")
    require(errors, int(get(connector, "errors", "retryTimeoutMs", default=0) or 0) >= 300000, "ClickHouse retries must cover at least five minutes")
    require(errors, int(get(connector, "errors", "retryDelayMaxMs", default=0) or 0) >= 10000, "ClickHouse retry backoff must reach at least ten seconds")
    require(errors, get(connector, "errors", "logIncludeMessages") is False, "connector logs must not include message payloads")
    require(errors, get(connector, "errors", "deadLetterTopic") == "beMobile.clickhouse.dlq", "connector failures must route to the managed DLQ")
    require(errors, int(get(connector, "errors", "deadLetterReplicationFactor", default=0) or 0) >= 3, "connector DLQ writes must require replication factor three")
    sink_consumer_group = str(get(connector, "consumerGroup", default="")).strip()
    require(errors, bool(sink_consumer_group), "ClickHouse connector must declare its sink consumer group")
    require(errors, sink_consumer_group != str(get(connect, "groupId", default="")).strip(), "sink tasks must not reuse the Connect worker coordination group")
    require(errors, get(connector, "consumer", "isolationLevel") == "read_committed", "sink tasks must ignore aborted transactional records")
    require(errors, int(get(connector, "consumer", "maxPollRecords", default=0) or 0) <= 10000, "max.poll.records must remain bounded at 10,000 or less")
    require(errors, get(connector, "clickhouseSettings", "asyncInsert") is True, "ClickHouse async inserts must be enabled")
    require(errors, get(connector, "clickhouseSettings", "waitForAsyncInsert") is True, "the connector must wait for ClickHouse async-insert acknowledgement")
    require(errors, get(values, "monitoring", "prometheusRules", "kafkaClickhouse", "enabled") is True, "Kafka-to-ClickHouse lag, replication, and DLQ alerts must be enabled")
    require(errors, get(values, "monitoring", "prometheusRules", "kafkaClickhouse", "consumerGroup") == sink_consumer_group, "consumer-lag alerts must target the sink task group")

    clickhouse_secret = external_secrets.get("clickhouseSinkCredentials", {}) if isinstance(external_secrets, dict) else {}
    registry_secret = external_secrets.get("registryCredentials", {}) if isinstance(external_secrets, dict) else {}
    require(errors, registry_secret.get("enabled") is True, "ExternalSecret/registryCredentials must be enabled")
    require(errors, registry_secret.get("targetName") in image_pull_secrets, "registry ExternalSecret target must match a global imagePullSecret")
    require(errors, clickhouse_secret.get("enabled") is True, "ExternalSecret/clickhouseSinkCredentials must be enabled")
    require(errors, clickhouse_secret.get("targetName") == get(connect, "credentialsSecret", "name"), "ClickHouse ExternalSecret target must match the Kafka Connect credential reference")
    secret_keys = {item.get("secretKey") for item in clickhouse_secret.get("data", []) if isinstance(item, dict)}
    require(errors, secret_keys >= {"username", "password"}, "ClickHouse ExternalSecret must deliver username and password keys")
    require(errors, get(values, "messaging", "redis", "replicas", default=0) >= 3, "Redis must have at least three replicas")
    require(errors, get(values, "messaging", "redis", "sentinel", "enabled") is True, "Redis Sentinel must be enabled")
    require(errors, get(values, "messaging", "redis", "compatibilitySecurityContext") is False, "Redis compatibility security mode must be disabled")
    require(errors, get(values, "databases", "defaultInstances", default=0) >= 3, "database instances must default to three")
    return errors


def validate_environment_profile(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    profiles = config.get("profiles", {})
    production = profiles.get("production", {}) if isinstance(profiles, dict) else {}
    require(errors, isinstance(production, dict), "environment profile catalog must define a production profile")
    for key in ("strictDatabaseMigration", "requireIngressEndpoint", "requirePrivateRegistry", "requireRestoreDrill", "requireReleaseEvidence"):
        require(errors, production.get(key) is True, f"production environment profile must require {key}")
    for key in (
        "runtimeHardeningProfile", "gitOpsProfile", "progressiveDeliveryProfile", "scalingPolicyProfile",
        "networkConnectivityProfile", "accessGovernanceProfile", "complianceEvidenceProfile",
        "incidentResponseProfile", "changeManagementProfile", "cutoverGateProfile", "smokeTestProfile",
        "releaseRunbookProfile", "clusterUpgradeProfile", "disasterRecoveryProfile", "backupProfile",
        "observabilityProfile",
    ):
        require(errors, bool(production.get(key)), f"production environment profile must declare {key}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate production deployment intent.")
    parser.add_argument("--values", default=str(ROOT / "helm/urban-platform-infra/values.yaml"))
    parser.add_argument("--production-values", default=str(ROOT / "helm/urban-platform-infra/values-production.yaml"))
    parser.add_argument("--environment-profiles", default=str(ROOT / "config/environment-profiles.yaml"))
    args = parser.parse_args(argv)

    base = load_mapping(Path(args.values))
    overlay = load_mapping(Path(args.production_values))
    merged = deep_merge(base, overlay)
    errors = validate_values(merged) + validate_environment_profile(load_mapping(Path(args.environment_profiles)))
    if errors:
        for error in errors:
            print(f"PRODUCTION-PROFILE: {error}")
        print(f"Production profile validation failed with {len(errors)} error(s).")
        return 1
    print("Production profile contract passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
