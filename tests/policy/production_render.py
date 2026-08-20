#!/usr/bin/env python3
"""Check the rendered production chart for HA, durability, and recovery controls."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml


KUBERNETES_NAME = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$")
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

    if by_kind.get("Secret"):
        errors.append("plain Kubernetes Secret manifests must not be rendered")

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
    for name in ("database-backup-credentials", "velero-backup-credentials"):
        if name not in external_secret_names:
            errors.append(f"ExternalSecret/{name}: production credential delivery is missing")

    kafka = next(iter(by_kind.get("Kafka", [])), None)
    node_pool = next(iter(by_kind.get("KafkaNodePool", [])), None)
    if not kafka or kafka.get("spec", {}).get("kafka", {}).get("version") != "4.3.0":
        errors.append("Kafka: Apache Kafka 4.3.0 is not rendered")
    if not node_pool or int(node_pool.get("spec", {}).get("replicas", 0)) < 3:
        errors.append("KafkaNodePool: production Kafka requires at least 3 replicas")
    else:
        volumes = node_pool.get("spec", {}).get("storage", {}).get("volumes", [])
        if not volumes or volumes[0].get("class") != "production-durable" or volumes[0].get("deleteClaim") is not False:
            errors.append("KafkaNodePool: durable non-deleting storage is required")

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
