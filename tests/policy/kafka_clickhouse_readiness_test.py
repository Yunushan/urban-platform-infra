#!/usr/bin/env python3
"""Exercise the Kafka-to-ClickHouse static score with public and private inputs."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import kafka_clickhouse_readiness as readiness


DIGEST = "sha256:" + ("a" * 64)
SYNTHETIC_PRIVATE_CIDR = ".".join(("10", "254", "253", "252")) + "/32"


def main() -> int:
    base = readiness.load_yaml(ROOT / "helm/urban-platform-infra/values.yaml")
    production = readiness.load_yaml(ROOT / "helm/urban-platform-infra/values-production.yaml")
    public_values = readiness.merge(base, production)
    public_checks = readiness.static_checks(public_values)
    if [check.passed for check in public_checks] != [True, True, True, True, True, False]:
        raise SystemExit("public Kafka-to-ClickHouse controls or placeholder detection regressed")

    private_overlay = {
        "global": {
            "imageRegistry": "registry.prod.corp.internal/platform",
            "imagePullSecrets": ["registry-credentials"],
        },
        "secretManagement": {
            "externalSecrets": {
                "registryCredentials": {
                    "data": [
                        {
                            "secretKey": ".dockerconfigjson",
                            "remoteRef": {"key": "production/registry/dockerconfigjson"},
                        }
                    ]
                },
                "clickhouseSinkCredentials": {
                    "data": [
                        {"secretKey": "username", "remoteRef": {"key": "production/clickhouse/username"}},
                        {"secretKey": "password", "remoteRef": {"key": "production/clickhouse/password"}},
                    ]
                }
            }
        },
        "messaging": {
            "kafka": {
                "image": {"digest": DIGEST},
                "strimzi": {
                    "operatorImage": {"digest": DIGEST},
                    "connect": {
                        "image": {"digest": DIGEST},
                        "networkPolicy": {"egressCidrs": [SYNTHETIC_PRIVATE_CIDR]},
                        "connector": {"hostname": "clickhouse.prod.corp.internal"},
                    }
                }
            }
        },
    }
    private_checks = readiness.static_checks(readiness.merge(public_values, private_overlay))
    if not all(check.passed for check in private_checks):
        failed = ", ".join(check.name for check in private_checks if not check.passed)
        raise SystemExit(f"synthetic private Kafka-to-ClickHouse profile failed: {failed}")
    if sum(check.weight for check in private_checks) != 84:
        raise SystemExit("static Kafka-to-ClickHouse score weights no longer total 84")

    mutable_broker_values = readiness.merge(
        readiness.merge(public_values, private_overlay),
        {"messaging": {"kafka": {"image": {"digest": ""}}}},
    )
    if readiness.static_checks(mutable_broker_values)[-1].passed:
        raise SystemExit("a mutable Kafka broker image was accepted as a private production input")

    mutable_operator_values = readiness.merge(
        readiness.merge(public_values, private_overlay),
        {"messaging": {"kafka": {"strimzi": {"operatorImage": {"digest": ""}}}}},
    )
    if readiness.static_checks(mutable_operator_values)[-1].passed:
        raise SystemExit("a mutable Strimzi operator image was accepted as a private production input")

    reused_worker_group = {
        "messaging": {
            "kafka": {
                "strimzi": {
                    "connect": {
                        "connector": {"consumerGroup": "clickhouse-connect"},
                    }
                }
            }
        }
    }
    unsafe_group_values = readiness.merge(
        readiness.merge(public_values, private_overlay),
        reused_worker_group,
    )
    if readiness.static_checks(unsafe_group_values)[3].passed:
        raise SystemExit("sink tasks were allowed to reuse the worker coordination group")

    stale_alert_group = {
        "monitoring": {
            "prometheusRules": {
                "kafkaClickhouse": {"consumerGroup": "clickhouse-connect"},
            }
        }
    }
    stale_alert_values = readiness.merge(
        readiness.merge(public_values, private_overlay),
        stale_alert_group,
    )
    if readiness.static_checks(stale_alert_values)[4].passed:
        raise SystemExit("consumer-lag alert was allowed to monitor the worker group")

    placeholder_overlay = readiness.merge(
        private_overlay,
        {
            "global": {"imageRegistry": "registry.production.example/platform"},
            "messaging": {
                "kafka": {
                    "strimzi": {
                        "connect": {
                            "networkPolicy": {"egressCidrs": ["192.0.2.44/32"]},
                            "connector": {"hostname": "clickhouse.production.example"},
                        }
                    }
                }
            },
        },
    )
    if readiness.static_checks(readiness.merge(public_values, placeholder_overlay))[-1].passed:
        raise SystemExit("documentation-only private inputs were accepted as deployment evidence")

    def ready_resource(*, spec: dict | None = None, status: dict | None = None) -> dict:
        resource_status = {
            "observedGeneration": 1,
            "conditions": [{"type": "Ready", "status": "True"}],
        }
        resource_status.update(status or {})
        return {
            "metadata": {"generation": 1},
            "spec": spec or {},
            "status": resource_status,
        }

    connector_class = "com.clickhouse.kafka.connect.ClickHouseSinkConnector"
    sink_group = "connect-clickhouse-bemobile-sink"
    connect_image = (
        "registry.prod.corp.internal/platform/urban-platform/"
        f"clickhouse-kafka-connect@{DIGEST}"
    )
    kafka_image = (
        "registry.prod.corp.internal/platform/quay.io/strimzi/"
        f"kafka@{DIGEST}"
    )
    operator_image = (
        "registry.prod.corp.internal/platform/quay.io/strimzi/"
        f"operator@{DIGEST}"
    )
    kafka_config = {
        "offsets.topic.replication.factor": 3,
        "transaction.state.log.replication.factor": 3,
        "transaction.state.log.min.isr": 2,
        "default.replication.factor": 3,
        "min.insync.replicas": 2,
        "auto.create.topics.enable": False,
        "unclean.leader.election.enable": False,
    }
    connect_internal_config = {
        "config.storage.replication.factor": 3,
        "offset.storage.replication.factor": 3,
        "status.storage.replication.factor": 3,
    }
    connector_live_config = {
        "topics": "beMobile",
        "topic2TableMap": "beMobile=bemobile",
        "hostname": "clickhouse.prod.corp.internal",
        "port": "8443",
        "exactlyOnce": "true",
        "ignorePartitionsWhenBatching": "false",
        "errors.deadletterqueue.topic.name": "beMobile.clickhouse.dlq",
        "consumer.override.group.id": sink_group,
        "consumer.override.isolation.level": "read_committed",
        "clickhouseSettings": "async_insert=1,wait_for_async_insert=1",
    }
    kafka_user_acls = [
        {
            "resource": {"type": "group", "name": "clickhouse-connect", "patternType": "literal"},
            "operations": ["Read"],
        },
        {
            "resource": {"type": "group", "name": sink_group, "patternType": "literal"},
            "operations": ["Read"],
        },
        {
            "resource": {"type": "topic", "name": "beMobile", "patternType": "literal"},
            "operations": ["Read", "Describe"],
        },
        {
            "resource": {
                "type": "topic",
                "name": "beMobile.clickhouse.dlq",
                "patternType": "literal",
            },
            "operations": ["Write", "Describe"],
        },
        {"resource": {"type": "cluster"}, "operations": ["Describe"]},
    ]
    resources = {
        "kafka/kafka": ready_resource(
            spec={
                "kafka": {
                    "version": "4.3.0",
                    "image": kafka_image,
                    "listeners": [
                        {
                            "name": "tls",
                            "port": 9093,
                            "type": "internal",
                            "tls": True,
                            "authentication": {"type": "tls"},
                        }
                    ],
                    "authorization": {"type": "simple"},
                    "config": kafka_config,
                    "template": {
                        "pod": {"imagePullSecrets": [{"name": "registry-credentials"}]},
                    },
                },
                "kafkaExporter": {"image": kafka_image},
                "cruiseControl": {"image": kafka_image},
                "entityOperator": {
                    "topicOperator": {"image": operator_image},
                    "userOperator": {"image": operator_image},
                },
            },
            status={
                "kafkaVersion": "4.3.0",
                "operatorLastSuccessfulVersion": "1.1.0",
            },
        ),
        "deployment/strimzi-cluster-operator": {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "strimzi-cluster-operator",
                                "image": operator_image,
                                "env": [{"name": "STRIMZI_NAMESPACE", "value": "urban-platform"}],
                            }
                        ]
                    }
                }
            },
            "status": {"availableReplicas": 1},
        },
        "kafkanodepool/dual-role": ready_resource(
            spec={
                "replicas": 3,
                "roles": ["controller", "broker"],
                "storage": {
                    "type": "jbod",
                    "volumes": [
                        {
                            "id": 0,
                            "type": "persistent-claim",
                            "class": "production-durable",
                            "size": "100Gi",
                            "deleteClaim": False,
                        }
                    ],
                },
            },
            status={"nodeIds": [0, 1, 2]},
        ),
        "kafkatopic/bemobile": ready_resource(
            spec={
                "partitions": 6,
                "replicas": 3,
                "config": {"min.insync.replicas": 2},
            }
        ),
        "kafkatopic/bemobile-clickhouse-dlq": ready_resource(
            spec={
                "partitions": 3,
                "replicas": 3,
                "config": {"min.insync.replicas": 2},
            }
        ),
        "podmonitor/kafka": {"metadata": {"name": "kafka"}},
        "nodes": {
            "items": [
                {
                    "metadata": {
                        "name": f"node-{number}",
                        "labels": {"topology.kubernetes.io/zone": f"zone-{number}"},
                    }
                }
                for number in range(1, 4)
            ]
        },
        "pods": {
            "items": [
                *[
                    {
                        "metadata": {
                            "name": f"kafka-dual-role-{number}",
                            "labels": {
                                "strimzi.io/cluster": "kafka",
                                "strimzi.io/pool-name": "dual-role",
                            },
                        },
                        "spec": {
                            "nodeName": f"node-{number + 1}",
                            "containers": [
                                {
                                    "name": "kafka",
                                    "image": kafka_image,
                                }
                            ],
                        },
                        "status": {
                            "phase": "Running",
                            "conditions": [{"type": "Ready", "status": "True"}],
                        },
                    }
                    for number in range(3)
                ],
                *[
                    {
                        "metadata": {
                            "name": f"clickhouse-connect-{number}",
                            "labels": {"strimzi.io/cluster": "clickhouse-connect"},
                        },
                        "spec": {
                            "nodeName": f"node-{number + 1}",
                            "containers": [
                                {"name": "connect", "image": connect_image}
                            ],
                        },
                        "status": {
                            "phase": "Running",
                            "conditions": [{"type": "Ready", "status": "True"}],
                        },
                    }
                    for number in range(3)
                ],
            ]
        },
        "persistentvolumeclaims": {
            "items": [
                {
                    "metadata": {
                        "name": f"data-0-kafka-dual-role-{number}",
                        "labels": {
                            "strimzi.io/cluster": "kafka",
                            "strimzi.io/pool-name": "dual-role",
                        },
                    },
                    "spec": {"storageClassName": "production-durable"},
                    "status": {"phase": "Bound", "capacity": {"storage": "100Gi"}},
                }
                for number in range(3)
            ]
        },
        "storageclass/production-durable": {
            "metadata": {"name": "production-durable"},
            "provisioner": "csi.production.internal",
            "allowVolumeExpansion": True,
            "reclaimPolicy": "Retain",
        },
        "kafkaconnect/clickhouse-connect": ready_resource(
            spec={
                "version": "4.3.0",
                "replicas": 3,
                "bootstrapServers": "kafka-kafka-bootstrap:9093",
                "groupId": "clickhouse-connect",
                "configStorageTopic": "clickhouse-connect-configs",
                "offsetStorageTopic": "clickhouse-connect-offsets",
                "statusStorageTopic": "clickhouse-connect-status",
                "image": connect_image,
                "tls": {"trustedCertificates": [{"secretName": "kafka-cluster-ca-cert"}]},
                "authentication": {"type": "tls"},
                "config": connect_internal_config,
                "template": {
                    "pod": {"imagePullSecrets": [{"name": "registry-credentials"}]},
                },
            },
            status={
                "replicas": 3,
                "connectorPlugins": [{"class": connector_class, "type": "sink", "version": "1.4.0"}],
            },
        ),
        "kafkaconnector/clickhouse-bemobile-sink": ready_resource(
            spec={
                "class": connector_class,
                "tasksMax": 6,
                "state": "running",
                "autoRestart": {"enabled": True, "maxRestarts": 10},
                "config": connector_live_config,
            },
            status={
                "connectorStatus": {
                    "connector": {"state": "RUNNING"},
                    "tasks": [{"id": task, "state": "RUNNING"} for task in range(6)],
                }
            }
        ),
        "kafkauser/clickhouse-connect": ready_resource(
            spec={
                "authentication": {"type": "tls"},
                "authorization": {"type": "simple", "acls": kafka_user_acls},
            }
        ),
        "externalsecret/clickhouse-sink-credentials": ready_resource(
            spec={"target": {"name": "clickhouse-sink-credentials"}}
        ),
        "externalsecret/registry-credentials": ready_resource(
            spec={"target": {"name": "registry-credentials"}}
        ),
        "secret/clickhouse-sink-credentials": {
            "metadata": {"name": "clickhouse-sink-credentials"},
            "type": "Opaque",
            "data": {"username": "dXNlcg==", "password": "cGFzcw=="},
        },
        "secret/registry-credentials": {
            "metadata": {"name": "registry-credentials"},
            "type": "kubernetes.io/dockerconfigjson",
            "data": {".dockerconfigjson": "e30="},
        },
        "clustersecretstore/vault": ready_resource(),
        "podmonitor/clickhouse-connect": {"metadata": {"name": "clickhouse-connect"}},
        "prometheusrule/urban-platform-slo": {
            "metadata": {"name": "urban-platform-slo"},
            "spec": {
                "groups": [
                    {
                        "rules": [
                            {"alert": "UrbanPlatformKafkaUnderReplicatedPartitions"},
                            {"alert": "UrbanPlatformClickHouseSinkConsumerLagHigh"},
                            {"alert": "UrbanPlatformClickHouseSinkDeadLetterQueueActive"},
                        ]
                    }
                ]
            },
        },
        "networkpolicy/clickhouse-connect-clickhouse-egress": {
            "metadata": {"name": "clickhouse-connect-clickhouse-egress"},
            "spec": {
                "egress": [
                    {
                        "to": [{"ipBlock": {"cidr": SYNTHETIC_PRIVATE_CIDR}}],
                        "ports": [{"protocol": "TCP", "port": 8443}],
                    }
                ]
            },
        },
    }

    def fake_kubectl_json(_kubectl: str, _kubeconfig: Path, _namespace: str, resource: str) -> dict | None:
        return resources.get(resource)

    with (
        patch.object(readiness.shutil, "which", return_value="kubectl"),
        patch.object(readiness, "kubectl_api_ready", return_value=True),
        patch.object(readiness, "kubectl_json", side_effect=fake_kubectl_json),
    ):
        live_checks = readiness.live_checks(
            readiness.merge(public_values, private_overlay),
            Path(__file__),
            "urban-platform",
            True,
        )
        if not all(check.passed for check in live_checks):
            failed = ", ".join(check.name for check in live_checks if not check.passed)
            raise SystemExit(f"synthetic healthy live resources did not pass readiness: {failed}")

        resources["kafka/kafka"]["status"]["conditions"].append({"type": "Warning", "status": "True"})
        if readiness.live_checks(readiness.merge(public_values, private_overlay), Path(__file__), "urban-platform", True)[0].passed:
            raise SystemExit("an active Strimzi Kafka warning was accepted as ready")
        resources["kafka/kafka"]["status"]["conditions"].pop()

        pods = resources["pods"]["items"]
        pods[1]["spec"]["nodeName"] = "node-1"
        if readiness.live_checks(readiness.merge(public_values, private_overlay), Path(__file__), "urban-platform", True)[0].passed:
            raise SystemExit("co-located Kafka brokers were accepted as failure-domain ready")
        pods[1]["spec"]["nodeName"] = "node-2"

        storage_class = resources["storageclass/production-durable"]
        storage_class["allowVolumeExpansion"] = False
        if readiness.live_checks(readiness.merge(public_values, private_overlay), Path(__file__), "urban-platform", True)[0].passed:
            raise SystemExit("non-expandable Kafka storage was accepted as production ready")
        storage_class["allowVolumeExpansion"] = True

        resources["kafka/kafka"]["spec"]["kafka"]["image"] = "quay.io/strimzi/kafka:1.1.0-kafka-4.3.0"
        if readiness.live_checks(readiness.merge(public_values, private_overlay), Path(__file__), "urban-platform", True)[0].passed:
            raise SystemExit("a drifted Kafka CR broker image was accepted as ready")
        resources["kafka/kafka"]["spec"]["kafka"]["image"] = kafka_image

        resources["deployment/strimzi-cluster-operator"]["spec"]["template"]["spec"]["containers"][0]["image"] = "quay.io/strimzi/operator:1.1.0"
        if readiness.live_checks(readiness.merge(public_values, private_overlay), Path(__file__), "urban-platform", True)[0].passed:
            raise SystemExit("a mutable Strimzi operator image was accepted as ready")
        resources["deployment/strimzi-cluster-operator"]["spec"]["template"]["spec"]["containers"][0]["image"] = operator_image

        pods[0]["spec"]["containers"][0]["image"] = "quay.io/strimzi/kafka:1.1.0-kafka-4.3.0"
        if readiness.live_checks(readiness.merge(public_values, private_overlay), Path(__file__), "urban-platform", True)[0].passed:
            raise SystemExit("a broker pod running outside the promoted image was accepted as ready")
        pods[0]["spec"]["containers"][0]["image"] = kafka_image

        resources["kafkaconnector/clickhouse-bemobile-sink"]["metadata"]["generation"] = 2
        if readiness.live_checks(readiness.merge(public_values, private_overlay), Path(__file__), "urban-platform", True)[1].passed:
            raise SystemExit("a stale KafkaConnector generation was accepted as ready")
        resources["kafkaconnector/clickhouse-bemobile-sink"]["metadata"]["generation"] = 1

        network_policy = resources["networkpolicy/clickhouse-connect-clickhouse-egress"]
        network_policy["spec"]["egress"][0]["to"][0]["ipBlock"]["cidr"] = ".".join(
            ("10", "254", "253", "251")
        ) + "/32"
        if readiness.live_checks(readiness.merge(public_values, private_overlay), Path(__file__), "urban-platform", True)[1].passed:
            raise SystemExit("a drifted ClickHouse egress CIDR was accepted as ready")
        network_policy["spec"]["egress"][0]["to"][0]["ipBlock"]["cidr"] = SYNTHETIC_PRIVATE_CIDR

        resources["externalsecret/clickhouse-sink-credentials"]["status"]["conditions"][0]["status"] = "False"
        if readiness.live_checks(readiness.merge(public_values, private_overlay), Path(__file__), "urban-platform", True)[1].passed:
            raise SystemExit("an unready ClickHouse credential ExternalSecret was accepted as ready")
        resources["externalsecret/clickhouse-sink-credentials"]["status"]["conditions"][0]["status"] = "True"

        resources["secret/clickhouse-sink-credentials"]["data"]["password"] = "not-base64"
        if readiness.live_checks(readiness.merge(public_values, private_overlay), Path(__file__), "urban-platform", True)[1].passed:
            raise SystemExit("an incomplete materialized ClickHouse credential Secret was accepted as ready")
        resources["secret/clickhouse-sink-credentials"]["data"]["password"] = "cGFzcw=="

        resources["externalsecret/registry-credentials"]["spec"]["target"]["name"] = "wrong-target"
        if readiness.live_checks(readiness.merge(public_values, private_overlay), Path(__file__), "urban-platform", True)[1].passed:
            raise SystemExit("an ExternalSecret targeting the wrong registry Secret was accepted as ready")
        resources["externalsecret/registry-credentials"]["spec"]["target"]["name"] = "registry-credentials"

        resources["clustersecretstore/vault"]["status"]["conditions"][0]["status"] = "False"
        if readiness.live_checks(readiness.merge(public_values, private_overlay), Path(__file__), "urban-platform", True)[1].passed:
            raise SystemExit("an unready external secret store was accepted as ready")
        resources["clustersecretstore/vault"]["status"]["conditions"][0]["status"] = "True"

        resources["kafkaconnector/clickhouse-bemobile-sink"]["spec"]["config"]["consumer.override.group.id"] = "drifted-group"
        if readiness.live_checks(readiness.merge(public_values, private_overlay), Path(__file__), "urban-platform", True)[1].passed:
            raise SystemExit("a reconciled but drifted sink consumer group was accepted as ready")

    print("Kafka-to-ClickHouse readiness synthetic static tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
