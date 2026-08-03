#!/usr/bin/env python3
"""Validate the public production profile before it is rendered or deployed."""
from __future__ import annotations

import argparse
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


def validate_values(values: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    require(errors, get(values, "global", "environment") == "production", "global.environment must be production")
    require(errors, get(values, "global", "defaultReplicas", default=0) >= 3, "global.defaultReplicas must be at least 3")
    require(errors, get(values, "global", "replicaOverride", default=None) is None, "global.replicaOverride must remain null so per-service HA replicas are preserved")
    require(errors, get(values, "global", "scheduling", "topologySpread") is True, "topology spread must be enabled")
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
    require(errors, bool(get(values, "storageTiers", "hot", "storageClassName")), "production must name a durable hot StorageClass")

    require(errors, get(values, "backup", "enabled") is True, "backup automation must be enabled")
    require(errors, get(values, "backup", "profile") == "production", "backup profile must be production")
    require(errors, get(values, "backup", "velero", "enabled") is True, "Velero backup integration must be enabled")
    require(errors, get(values, "backup", "velero", "snapshotsEnabled") is True, "volume snapshots must be enabled")
    require(errors, get(values, "backup", "rke2Etcd", "enabled") is True, "RKE2 etcd backups must be enabled")
    require(errors, get(values, "backup", "imageArchives", "enabled") is True, "image archive retention must be enabled")

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
