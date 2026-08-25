#!/usr/bin/env python3
"""Exercise the fail-closed Kafka-to-ClickHouse reconciliation workflow."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import kafka_clickhouse_readiness as readiness
from scripts import kafka_clickhouse_reconcile as reconcile


DIGEST = "sha256:" + ("b" * 64)
PRIVATE_CIDR = ".".join(("10", "253", "252", "251")) + "/32"


def private_overlay() -> dict:
    return {
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
                },
                "databaseBackupCredentials": {
                    "data": [
                        {"secretKey": "accessKeyId", "remoteRef": {"key": "production/backup/access-key-id"}},
                        {"secretKey": "secretAccessKey", "remoteRef": {"key": "production/backup/secret-access-key"}},
                    ]
                },
                "veleroBackupCredentials": {
                    "data": [
                        {"secretKey": "cloud", "remoteRef": {"key": "production/backup/velero-cloud"}},
                    ]
                },
                "ingressTls": {
                    "data": [
                        {"secretKey": "tls.crt", "remoteRef": {"key": "production/ingress/tls", "property": "tls.crt"}},
                        {"secretKey": "tls.key", "remoteRef": {"key": "production/ingress/tls", "property": "tls.key"}},
                    ]
                },
            }
        },
        "messaging": {
            "kafka": {
                "strimzi": {
                    "connect": {
                        "image": {"digest": DIGEST},
                        "networkPolicy": {"egressCidrs": [PRIVATE_CIDR]},
                        "connector": {"hostname": "clickhouse.prod.corp.internal"},
                    }
                }
            }
        },
    }


def established_crd(name: str, version: str) -> dict:
    return {
        "metadata": {"name": name},
        "spec": {"versions": [{"name": version, "served": True, "storage": True}]},
        "status": {"conditions": [{"type": "Established", "status": "True"}]},
    }


def cluster_runner(command: list[str], _timeout: int) -> reconcile.CommandResult:
    if "--raw=/readyz" in command:
        return reconcile.CommandResult(0, "ok\n")
    if "customresourcedefinitions.apiextensions.k8s.io" in command:
        return reconcile.CommandResult(
            0,
            json.dumps(
                {
                    "items": [
                        established_crd(name, version)
                        for name, version in reconcile.REQUIRED_CRDS.items()
                    ]
                }
            ),
        )
    if "storageclass" in command:
        return reconcile.CommandResult(
            0,
            json.dumps(
                {
                    "metadata": {"name": "production-durable"},
                    "provisioner": "csi.production.internal",
                    "allowVolumeExpansion": True,
                    "reclaimPolicy": "Retain",
                }
            ),
        )
    if "nodes" in command:
        return reconcile.CommandResult(
            0,
            json.dumps(
                {
                    "items": [
                        {
                            "metadata": {
                                "name": f"node-{number}",
                                "labels": {"topology.kubernetes.io/zone": f"zone-{number}"},
                            },
                            "spec": {"unschedulable": False},
                            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
                        }
                        for number in range(1, 4)
                    ]
                }
            ),
        )
    if "deployment/strimzi-cluster-operator" in command:
        return reconcile.CommandResult(
            0,
            json.dumps(
                {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "image": "quay.io/strimzi/operator:1.1.0",
                                        "env": [{"name": "STRIMZI_NAMESPACE", "value": "urban-platform"}],
                                    }
                                ]
                            }
                        }
                    },
                    "status": {"availableReplicas": 1},
                }
            ),
        )
    if any(value.startswith("clustersecretstore/") for value in command):
        return reconcile.CommandResult(
            0,
            json.dumps({"status": {"conditions": [{"type": "Ready", "status": "True"}]}}),
        )
    return reconcile.CommandResult(1)


def main() -> int:
    base = readiness.load_yaml(ROOT / "helm/urban-platform-infra/values.yaml")
    production = readiness.load_yaml(ROOT / "helm/urban-platform-infra/values-production.yaml")
    values = readiness.merge(readiness.merge(base, production), private_overlay())
    if not all(check.passed for check in readiness.static_checks(values)):
        raise SystemExit("synthetic private production profile no longer passes the static gate")
    if reconcile.enabled_placeholder_secrets(values):
        raise SystemExit("valid private secret references were rejected")

    unsafe = readiness.merge(
        values,
        {
            "secretManagement": {
                "externalSecrets": {
                    "ingressTls": {
                        "data": [
                            {"secretKey": "tls.crt", "remoteRef": {"key": "example/ingress/tls"}}
                        ]
                    }
                }
            }
        },
    )
    if "ingressTls" not in reconcile.enabled_placeholder_secrets(unsafe):
        raise SystemExit("an enabled placeholder ExternalSecret reference was accepted")

    if reconcile.helm_major("helm", runner=lambda _command, _timeout: reconcile.CommandResult(0, "v3.21\n")) != 3:
        raise SystemExit("Helm versions without a patch component are not recognized")
    if reconcile.helm_duration_seconds("20m") != 1200 or reconcile.helm_duration_seconds("0m") is not None:
        raise SystemExit("Helm timeout parsing is not fail-closed")

    preflight = reconcile.cluster_preflight(
        values,
        "kubectl",
        Path("synthetic-kubeconfig"),
        "urban-platform",
        "strimzi-system",
        runner=cluster_runner,
    )
    if not all(stage.passed for stage in preflight):
        failed = ", ".join(stage.name for stage in preflight if not stage.passed)
        raise SystemExit(f"synthetic production cluster preflight failed: {failed}")

    with tempfile.TemporaryDirectory(prefix="urban-kafka-reconcile-") as directory:
        temp = Path(directory)
        base_path = temp / "base.yaml"
        production_path = temp / "production.yaml"
        private_path = temp / "private.yaml"
        chart = temp / "chart"
        chart.mkdir()
        for path in (base_path, production_path, private_path):
            path.write_text("{}\n", encoding="utf-8")

        template = reconcile.build_template_command(
            "helm",
            "urban-platform-infra",
            chart,
            "urban-platform",
            base_path,
            production_path,
            private_path,
        )
        if template.count("--api-versions") != len(reconcile.HELM_API_VERSIONS):
            raise SystemExit("offline Helm rendering does not model every required API")

        upgrade4 = reconcile.build_upgrade_command(
            "helm",
            4,
            "urban-platform-infra",
            chart,
            "urban-platform",
            Path("synthetic-kubeconfig"),
            "20m",
            base_path,
            production_path,
            private_path,
        )
        if "--rollback-on-failure" not in upgrade4 or "--atomic" in upgrade4:
            raise SystemExit("Helm 4 reconciliation is missing rollback-on-failure")
        upgrade3 = reconcile.build_upgrade_command(
            "helm",
            3,
            "urban-platform-infra",
            chart,
            "urban-platform",
            Path("synthetic-kubeconfig"),
            "20m",
            base_path,
            production_path,
            private_path,
        )
        if "--atomic" not in upgrade3 or "--rollback-on-failure" in upgrade3:
            raise SystemExit("Helm 3 reconciliation is missing atomic rollback")

        now = [0.0]
        live_calls = [0]

        def monotonic() -> float:
            return now[0]

        def sleep(seconds: float) -> None:
            now[0] += seconds

        def synthetic_live(*_args, **_kwargs):
            live_calls[0] += 1
            passed = live_calls[0] >= 2
            return [
                readiness.Check("Live broker and topic readiness", 8, passed, "synthetic", True),
                readiness.Check("Live Connect and ClickHouse sink readiness", 8, passed, "synthetic", True),
            ]

        report = temp / "readiness.md"
        with patch.object(reconcile.readiness, "live_checks", side_effect=synthetic_live):
            passed, score = reconcile.wait_for_readiness(
                values,
                Path("synthetic-kubeconfig"),
                "urban-platform",
                92,
                report,
                timeout_seconds=60,
                poll_interval_seconds=5,
                stable_passes=2,
                sleep=sleep,
                monotonic=monotonic,
            )
        if not passed or score != 100 or live_calls[0] != 3:
            raise SystemExit("stable live readiness did not require two consecutive passing observations")
        report_text = report.read_text(encoding="utf-8")
        for private_value in ("clickhouse.prod.corp.internal", PRIVATE_CIDR, "production/clickhouse/password"):
            if private_value in report_text:
                raise SystemExit("readiness report leaked a private deployment input")

    print("Kafka-to-ClickHouse reconciliation synthetic tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
