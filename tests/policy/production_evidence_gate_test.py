#!/usr/bin/env python3
"""Exercise the private production evidence gate with synthetic local evidence."""
from __future__ import annotations

import hashlib
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import production_evidence_gate as gate


DIGEST = "sha256:" + ("a" * 64)
RELEASE_TAG = "v1.2.3"
SOURCE_REVISION = "0123456789abcdef0123456789abcdef01234567"
DEPLOYMENT_ID = "123e4567-e89b-42d3-a456-426614174000"
CLUSTER_UID = "87f5bf7c-5617-4d7d-8435-4d398b24f501"
TRUSTED_APPROVERS = frozenset({"synthetic-reviewer"})


def write_yaml(path: Path, value: dict) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def descriptor(path: Path) -> dict[str, str]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "path": path.name,
        "sha256": f"sha256:{digest}",
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "approvedBy": "synthetic-reviewer",
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="urban-production-evidence-") as directory:
        root = Path(directory)
        evidence_root = root / "images"
        dr_root = root / "dr"
        evidence_root.mkdir()
        dr_root.mkdir()
        for name in gate.REQUIRED_DR_ARTIFACTS:
            (dr_root / f"{name}.txt").write_text("synthetic evidence\n", encoding="utf-8")
        base_values = root / "values.yaml"
        public_values = root / "values-production.yaml"
        private_values = root / "values-private.yaml"
        write_yaml(base_values, {"global": {"imageRegistry": ""}, "workloads": {"demo": {"image": {"repository": "example-app-demo", "tag": "0.1.0"}}}})
        write_yaml(
            public_values,
            {
                "databases": {
                    "enabled": True,
                    "topology": {"mode": "per-service"},
                    "instances": {
                        f"database-{index}": {"enabled": True, "engine": "postgresql"}
                        for index in range(18)
                    },
                },
                "messaging": {
                    "kafka": {
                        "enabled": True,
                        "provider": "strimzi",
                        "mode": "operator",
                        "replicas": 3,
                        "strimzi": {"kafkaVersion": "4.3.0"},
                    }
                },
                "storageTiers": {"hot": {"storageClassName": "production-durable"}},
                "networkPolicy": {"enabled": True, "defaultDeny": {"enabled": True}},
                "namespace": {
                    "podSecurity": {"version": "v1.34"},
                    "resourceQuota": {
                        "enabled": True,
                        "hard": {
                            "requests.cpu": "12",
                            "requests.memory": "32Gi",
                            "limits.cpu": "20",
                            "limits.memory": "40Gi",
                            "requests.storage": "2Ti",
                            "persistentvolumeclaims": "100",
                            "pods": "300",
                        },
                    },
                    "limitRange": {
                        "enabled": True,
                        "default": {"cpu": "1", "memory": "1Gi", "ephemeral-storage": "2Gi"},
                        "defaultRequest": {"cpu": "100m", "memory": "256Mi", "ephemeral-storage": "512Mi"},
                    },
                },
                "autoscaling": {"enabled": True},
                "ingress": {
                    "enabled": True,
                    "className": "traefik",
                    "tls": {
                        "enabled": True,
                        "secretName": "synthetic-tls",
                        "certManager": {"enabled": True},
                    },
                },
                "secretManagement": {
                    "enabled": True,
                    "provider": "external-secrets",
                    "externalSecrets": {
                        "synthetic": {
                            "enabled": True,
                            "targetName": "synthetic-secret",
                            "namespace": "urban-platform",
                            "type": "Opaque",
                            "data": [{"secretKey": "token"}],
                        }
                    },
                },
            },
        )
        write_yaml(
            private_values,
            {
                "global": {
                    "imageRegistry": "registry.internal/platform",
                    "releaseIdentity": {
                        "enabled": True,
                        "tag": RELEASE_TAG,
                        "sourceRevision": SOURCE_REVISION,
                        "deploymentId": DEPLOYMENT_ID,
                    },
                },
                "workloads": {
                    "demo": {
                        "image": {
                            "repository": "demo",
                            "tag": "1.0.0",
                            "digest": DIGEST,
                        }
                    }
                },
            },
        )
        for name in ("scan.txt", "sbom.txt", "signature.txt", "promotion.txt"):
            (evidence_root / name).write_text("synthetic evidence\n", encoding="utf-8")
        index = evidence_root / "index.yaml"
        write_yaml(
            index,
            {
                "version": 2,
                "images": [
                    {
                        "path": "workloads.demo.image",
                        "reference": f"registry.internal/platform/demo@{DIGEST}",
                        "digest": DIGEST,
                        "vulnerabilityScan": descriptor(evidence_root / "scan.txt"),
                        "sbom": descriptor(evidence_root / "sbom.txt"),
                        "signatureOrAttestation": descriptor(evidence_root / "signature.txt"),
                        "promotionRecord": descriptor(evidence_root / "promotion.txt"),
                    }
                ],
            },
        )
        config_path = root / "evidence.yaml"
        kubeconfig = root / "operator.kubeconfig"
        kubeconfig.write_text("synthetic kubeconfig\n", encoding="utf-8")
        config = {
            "version": 4,
            "attestation": {
                "issuedAt": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            },
            "release": {
                "tag": RELEASE_TAG,
                "owner": "release-owner",
                "sourceRevision": SOURCE_REVISION,
                "deploymentId": DEPLOYMENT_ID,
                "valuesOverlay": str(private_values),
                "valuesOverlaySha256": gate.file_digest(private_values),
            },
            "registry": {
                "privateRegistry": "registry.internal/platform",
                "evidenceRoot": str(evidence_root),
                "imageEvidenceIndex": "index.yaml",
                "imageEvidenceIndexSha256": gate.file_digest(index),
                "maximumEvidenceAgeDays": 30,
            },
            "disasterRecovery": {
                "evidenceRoot": str(dr_root),
                "maximumEvidenceAgeDays": 180,
                "artifacts": {
                    name: descriptor(dr_root / f"{name}.txt")
                    for name in gate.REQUIRED_DR_ARTIFACTS
                },
            },
            "liveCluster": {
                "required": True,
                "kubeconfig": str(kubeconfig),
                "clusterUid": CLUSTER_UID,
                "namespace": "urban-platform",
                "minimumReadyNodes": 3,
                "failureDomainLabel": "kubernetes.io/hostname",
                "expectedPodSecurityVersion": "v1.34",
                "expectedPostgresClusters": 18,
                "expectedKafkaVersion": "4.3.0",
                "expectedPodDisruptionBudgets": ["synthetic-pdb"],
                "expectedAutoscalers": ["synthetic-hpa"],
                "ingressProbe": {
                    "required": True,
                    "httpsUrl": "https://synthetic.example/login",
                    "httpUrl": "http://synthetic.example/login",
                    "expectedHttpsStatusCodes": [200],
                    "expectedHttpStatusCodes": [308],
                    "requireHttpRedirect": True,
                    "tlsVerify": True,
                },
            },
        }
        write_yaml(config_path, config)
        loaded = gate.load_yaml(config_path)
        attestation_ok, _ = gate.validate_attestation_window(loaded)
        expired = deepcopy(loaded)
        expired["attestation"]["issuedAt"] = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).isoformat()
        expired["attestation"]["expiresAt"] = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()
        expired_ok, _ = gate.validate_attestation_window(expired)
        if not attestation_ok or expired_ok:
            raise SystemExit("production evidence gate did not enforce the signed attestation window")
        public_key = root / "evidence.pub"
        bundle = root / "evidence.sigstore.json"
        public_key.write_text("synthetic public key\n", encoding="utf-8")
        bundle.write_text(
            '{"mediaType":"application/vnd.dev.sigstore.bundle.v0.3+json"}\n',
            encoding="utf-8",
        )
        trust_path = root / "trust.yaml"
        write_yaml(
            trust_path,
            {
                "version": 2,
                "provider": "cosign-key-bundle",
                "evidenceManifest": {
                    "publicKey": str(public_key),
                    "bundle": str(bundle),
                },
                "trustedApprovers": sorted(TRUSTED_APPROVERS),
            },
        )
        with (
            patch.object(gate.shutil, "which", return_value="cosign"),
            patch.object(
                gate.subprocess,
                "run",
                side_effect=[
                    SimpleNamespace(returncode=0, stdout='{"gitVersion":"v3.1.3"}'),
                    SimpleNamespace(returncode=0, stdout=""),
                ],
            ),
        ):
            trust_ok, _, trust_policy = gate.validate_trust_policy(trust_path, config_path)
        if not trust_ok or trust_policy is None:
            raise SystemExit("production evidence gate rejected a valid standardized Sigstore bundle")
        with (
            patch.object(gate.shutil, "which", return_value="cosign"),
            patch.object(
                gate.subprocess,
                "run",
                side_effect=[
                    SimpleNamespace(returncode=0, stdout='{"gitVersion":"v3.1.3"}'),
                    SimpleNamespace(returncode=1, stdout=""),
                ],
            ),
        ):
            invalid_bundle_ok, _, _ = gate.validate_trust_policy(trust_path, config_path)
        if invalid_bundle_ok:
            raise SystemExit("production evidence gate accepted an invalid standardized bundle")
        with (
            patch.object(gate.shutil, "which", return_value="cosign"),
            patch.object(
                gate.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout='{"gitVersion":"v3.1.2"}'),
            ),
        ):
            vulnerable_cosign_ok, _, _ = gate.validate_trust_policy(trust_path, config_path)
        if vulnerable_cosign_ok:
            raise SystemExit("production evidence gate accepted a vulnerable Cosign version")
        bundle.write_text('{"base64Signature":"legacy"}\n', encoding="utf-8")
        legacy_bundle_ok, _, _ = gate.validate_trust_policy(trust_path, config_path)
        bundle.write_text(
            '{"mediaType":"application/vnd.dev.sigstore.bundle.v0.3+json"}\n',
            encoding="utf-8",
        )
        if legacy_bundle_ok:
            raise SystemExit("production evidence gate accepted a legacy Sigstore bundle")
        clean_checkout_results = [
            SimpleNamespace(returncode=0, stdout=f"{gate.ROOT}\n"),
            SimpleNamespace(returncode=0, stdout=f"{SOURCE_REVISION}\n"),
            SimpleNamespace(returncode=0, stdout=""),
        ]
        with (
            patch.object(gate.shutil, "which", return_value="git"),
            patch.object(gate.subprocess, "run", side_effect=clean_checkout_results),
        ):
            clean_source_ok, _ = gate.validate_source_checkout(SOURCE_REVISION)
        dirty_checkout_results = [
            SimpleNamespace(returncode=0, stdout=f"{gate.ROOT}\n"),
            SimpleNamespace(returncode=0, stdout=f"{SOURCE_REVISION}\n"),
            SimpleNamespace(returncode=0, stdout=" M scripts/production_evidence_gate.py\n"),
        ]
        with (
            patch.object(gate.shutil, "which", return_value="git"),
            patch.object(gate.subprocess, "run", side_effect=dirty_checkout_results),
        ):
            dirty_source_ok, _ = gate.validate_source_checkout(SOURCE_REVISION)
        if not clean_source_ok or dirty_source_ok:
            raise SystemExit("production evidence gate did not bind evidence to a clean source checkout")
        release_ok, _, private_overlay = gate.validate_release(loaded, root)
        image_ok, _, image_count = gate.validate_registry(
            loaded,
            root,
            base_values,
            public_values,
            private_overlay,
            TRUSTED_APPROVERS,
        )
        dr_ok, _, dr_count = gate.validate_dr(loaded, root, TRUSTED_APPROVERS)

        placeholder_release = deepcopy(loaded)
        placeholder_release["release"]["tag"] = "v0.0.0"
        placeholder_release_ok, _, _ = gate.validate_release(placeholder_release, root)
        if placeholder_release_ok:
            raise SystemExit("production evidence gate accepted a placeholder release identity")

        private_values.write_text(private_values.read_text(encoding="utf-8") + "# tampered\n", encoding="utf-8")
        tampered_overlay_ok, _, _ = gate.validate_release(loaded, root)
        write_yaml(
            private_values,
            {
                "global": {
                    "imageRegistry": "registry.internal/platform",
                    "releaseIdentity": {
                        "enabled": True,
                        "tag": RELEASE_TAG,
                        "sourceRevision": SOURCE_REVISION,
                        "deploymentId": DEPLOYMENT_ID,
                    },
                },
                "workloads": {
                    "demo": {
                        "image": {
                            "repository": "demo",
                            "tag": "1.0.0",
                            "digest": DIGEST,
                        }
                    }
                },
            },
        )
        if tampered_overlay_ok:
            raise SystemExit("production evidence gate accepted a checksum-invalid private overlay")

        untrusted_dr_ok, _, _ = gate.validate_dr(
            loaded,
            root,
            frozenset({"different-reviewer"}),
        )
        if untrusted_dr_ok:
            raise SystemExit("production evidence gate accepted an approver outside the trust policy")

        original_index_text = index.read_text(encoding="utf-8")
        index.write_text(original_index_text + "# tampered\n", encoding="utf-8")
        tampered_index_ok, _, _ = gate.validate_registry(
            loaded,
            root,
            base_values,
            public_values,
            private_overlay,
            TRUSTED_APPROVERS,
        )
        index.write_text(original_index_text, encoding="utf-8")
        if tampered_index_ok:
            raise SystemExit("production evidence gate accepted a checksum-invalid evidence index")

        scan_path = evidence_root / "scan.txt"
        scan_path.write_text("tampered evidence\n", encoding="utf-8")
        tampered_image_ok, _, _ = gate.validate_registry(
            loaded,
            root,
            base_values,
            public_values,
            private_overlay,
            TRUSTED_APPROVERS,
        )
        scan_path.write_text("synthetic evidence\n", encoding="utf-8")
        if tampered_image_ok:
            raise SystemExit("production evidence gate accepted checksum-invalid image evidence")

        stale_config = deepcopy(loaded)
        stale_config["disasterRecovery"]["artifacts"]["databaseRestore"]["capturedAt"] = "2020-01-01T00:00:00Z"
        stale_dr_ok, _, _ = gate.validate_dr(stale_config, root, TRUSTED_APPROVERS)
        if stale_dr_ok:
            raise SystemExit("production evidence gate accepted stale disaster-recovery evidence")

        aliased_dr_config = deepcopy(loaded)
        shared_dr_descriptor = aliased_dr_config["disasterRecovery"]["artifacts"]["rtoRpo"]
        aliased_dr_config["disasterRecovery"]["artifacts"] = {
            name: deepcopy(shared_dr_descriptor) for name in gate.REQUIRED_DR_ARTIFACTS
        }
        aliased_dr_ok, _, _ = gate.validate_dr(aliased_dr_config, root, TRUSTED_APPROVERS)
        if aliased_dr_ok:
            raise SystemExit("production evidence gate accepted one file for every DR control")

        index_value = gate.load_yaml(index)
        original_sbom = deepcopy(index_value["images"][0]["sbom"])
        index_value["images"][0]["sbom"] = deepcopy(index_value["images"][0]["vulnerabilityScan"])
        write_yaml(index, index_value)
        loaded["registry"]["imageEvidenceIndexSha256"] = gate.file_digest(index)
        aliased_image_ok, _, _ = gate.validate_registry(
            loaded,
            root,
            base_values,
            public_values,
            private_overlay,
            TRUSTED_APPROVERS,
        )
        index_value["images"][0]["sbom"] = original_sbom
        write_yaml(index, index_value)
        loaded["registry"]["imageEvidenceIndexSha256"] = gate.file_digest(index)
        if aliased_image_ok:
            raise SystemExit("production evidence gate accepted one file for multiple image controls")

        index_value = gate.load_yaml(index)
        index_value["images"][0]["reference"] = f"registry.internal/platform/other@{DIGEST}"
        write_yaml(index, index_value)
        loaded["registry"]["imageEvidenceIndexSha256"] = gate.file_digest(index)
        wrong_reference_ok, _, _ = gate.validate_registry(
            loaded,
            root,
            base_values,
            public_values,
            private_overlay,
            TRUSTED_APPROVERS,
        )
        index_value["images"][0]["reference"] = f"registry.internal/platform/demo@{DIGEST}"
        write_yaml(index, index_value)
        loaded["registry"]["imageEvidenceIndexSha256"] = gate.file_digest(index)
        if wrong_reference_ok:
            raise SystemExit("production evidence gate accepted evidence for the wrong image repository")

        disabled_ok, _ = gate.validate_live(
            {"liveCluster": {"required": False}},
            run_live=False,
        )
        if disabled_ok:
            raise SystemExit("production evidence gate allowed live verification to be disabled")
        not_requested_ok, _ = gate.validate_live(loaded, run_live=False)
        if not_requested_ok:
            raise SystemExit("production evidence gate passed without --live")

        with patch.object(
            gate.subprocess,
            "run",
            side_effect=gate.subprocess.TimeoutExpired(["kubectl"], 30),
        ):
            kubectl_result, kubectl_detail = gate.kubectl_json(
                "kubectl",
                kubeconfig,
                "urban-platform",
                "pods",
            )
        if kubectl_result is not None or kubectl_detail != "Kubernetes API query failed":
            raise SystemExit("production evidence gate did not fail closed on a Kubernetes API timeout")

        probe_results = [(True, "synthetic HTTPS probe"), (True, "synthetic HTTP redirect probe")]
        with patch.object(gate, "probe_http_endpoint", side_effect=probe_results) as probe:
            ingress_probe_ok, _ = gate.validate_ingress_probe(
                loaded["liveCluster"],
                root,
            )
        if not ingress_probe_ok or probe.call_count != 2:
            raise SystemExit("production evidence gate did not execute both signed ingress probes")

        insecure_probe = deepcopy(loaded["liveCluster"])
        insecure_probe["ingressProbe"]["tlsVerify"] = False
        insecure_probe_ok, _ = gate.validate_ingress_probe(insecure_probe, root)
        if insecure_probe_ok:
            raise SystemExit("production evidence gate accepted an ingress probe with TLS verification disabled")

        with patch.object(
            gate,
            "probe_http_endpoint",
            side_effect=[(True, "synthetic HTTPS probe"), (False, "synthetic redirect failure")],
        ):
            failed_redirect_ok, _ = gate.validate_ingress_probe(loaded["liveCluster"], root)
        if failed_redirect_ok:
            raise SystemExit("production evidence gate accepted an unavailable HTTP-to-HTTPS redirect")

        nodes = [
            {
                "metadata": {
                    "name": f"node-{index}",
                    "labels": {"kubernetes.io/hostname": f"node-{index}"},
                },
                "spec": {},
                "status": {"conditions": [{"type": "Ready", "status": "True"}]},
            }
            for index in range(3)
        ]
        workloads = [
            {
                "kind": "Deployment",
                "metadata": {"generation": 2},
                "spec": {"replicas": 3},
                "status": {
                    "observedGeneration": 2,
                    "readyReplicas": 3,
                    "availableReplicas": 3,
                    "updatedReplicas": 3,
                    "unavailableReplicas": 0,
                },
            },
            {
                "kind": "StatefulSet",
                "metadata": {"generation": 2},
                "spec": {"replicas": 3},
                "status": {
                    "observedGeneration": 2,
                    "readyReplicas": 3,
                    "currentReplicas": 3,
                    "updatedReplicas": 3,
                },
            },
        ]
        clusters = [
            {
                "spec": {"instances": 3, "backup": {"barmanObjectStore": {"destinationPath": "redacted"}}},
                "status": {
                    "readyInstances": 3,
                    "currentPrimary": f"database-{index}-1",
                    "conditions": [{"type": "Ready", "status": "True"}],
                },
            }
            for index in range(18)
        ]
        scheduled_backups = [
            {"spec": {"schedule": "0 0 */6 * * *", "suspend": False}}
            for _ in range(18)
        ]

        def fake_kubectl_json(_kubectl: str, _kubeconfig: Path, _namespace: str | None, resource: str):
            resources = {
                "nodes": {"items": nodes},
                "namespace/urban-platform": {
                    "metadata": {
                        "labels": {
                            "pod-security.kubernetes.io/enforce": "restricted",
                            "pod-security.kubernetes.io/audit": "restricted",
                            "pod-security.kubernetes.io/warn": "restricted",
                            "pod-security.kubernetes.io/enforce-version": "v1.34",
                            "pod-security.kubernetes.io/audit-version": "v1.34",
                            "pod-security.kubernetes.io/warn-version": "v1.34",
                        }
                    }
                },
                "configmap/urban-platform-release-identity": {
                    "data": {
                        "releaseTag": RELEASE_TAG,
                        "sourceRevision": SOURCE_REVISION,
                        "deploymentId": DEPLOYMENT_ID,
                    }
                },
                "namespace/kube-system": {"metadata": {"uid": CLUSTER_UID}},
                "deployments,statefulsets": {"items": workloads},
                "pods": {
                    "items": [
                        {
                            "spec": {
                                "containers": [
                                    {
                                        "name": "application",
                                        "image": f"registry.internal/platform/demo@{DIGEST}",
                                    }
                                ]
                            },
                            "status": {
                                "phase": "Running",
                                "containerStatuses": [
                                    {
                                        "name": "application",
                                        "ready": True,
                                        "imageID": f"registry.internal/platform/demo@{DIGEST}",
                                    }
                                ],
                            }
                        }
                    ]
                },
                "storageclass/production-durable": {
                    "provisioner": "synthetic.csi.example",
                    "allowVolumeExpansion": True,
                    "reclaimPolicy": "Retain",
                },
                "persistentvolumeclaims": {
                    "items": [
                        {
                            "spec": {"storageClassName": "production-durable"},
                            "status": {"phase": "Bound"},
                        }
                    ]
                },
                "networkpolicy/urban-platform-default-deny": {
                    "spec": {
                        "podSelector": {},
                        "policyTypes": ["Ingress", "Egress"],
                    }
                },
                "resourcequotas": {
                    "items": [
                        {
                            "metadata": {"name": "quota"},
                            "spec": {
                                "hard": {
                                    "requests.cpu": "12",
                                    "requests.memory": "32Gi",
                                    "limits.cpu": "20",
                                    "limits.memory": "40Gi",
                                    "requests.storage": "2Ti",
                                    "persistentvolumeclaims": "100",
                                    "pods": "300",
                                }
                            },
                        }
                    ]
                },
                "limitranges": {
                    "items": [
                        {
                            "metadata": {"name": "limits"},
                            "spec": {
                                "limits": [
                                    {
                                        "type": "Container",
                                        "default": {"cpu": "1", "memory": "1Gi", "ephemeral-storage": "2Gi"},
                                        "defaultRequest": {"cpu": "100m", "memory": "256Mi", "ephemeral-storage": "512Mi"},
                                    }
                                ]
                            },
                        }
                    ]
                },
                "poddisruptionbudgets.policy": {
                    "items": [
                        {"metadata": {"name": "synthetic-pdb"}, "status": {"currentHealthy": 3, "desiredHealthy": 2}}
                    ]
                },
                "horizontalpodautoscalers.autoscaling": {
                    "items": [
                        {
                            "metadata": {"name": "synthetic-hpa"},
                            "status": {
                                "conditions": [
                                    {"type": "AbleToScale", "status": "True"},
                                    {"type": "ScalingActive", "status": "True"},
                                ]
                            }
                        }
                    ]
                },
                "ingresses.networking.k8s.io": {
                    "items": [
                        {
                            "metadata": {
                                "name": "webserver",
                                "annotations": {
                                    "traefik.ingress.kubernetes.io/router.entrypoints": "websecure",
                                },
                            },
                            "spec": {"ingressClassName": "traefik", "tls": [{"secretName": "synthetic-tls"}]},
                        },
                        {
                            "metadata": {
                                "name": "webserver-redirect",
                                "annotations": {
                                    "traefik.ingress.kubernetes.io/router.entrypoints": "web",
                                    "traefik.ingress.kubernetes.io/router.middlewares": "urban-platform-redirect-https@kubernetescrd",
                                },
                            },
                            "spec": {"ingressClassName": "traefik", "rules": [{"http": {}}]},
                        },
                    ]
                },
                "clusters.postgresql.cnpg.io": {"items": clusters},
                "scheduledbackups.postgresql.cnpg.io": {"items": scheduled_backups},
                "certificates.cert-manager.io": {
                    "items": [
                        {
                            "spec": {"secretName": "synthetic-tls"},
                            "status": {
                                "conditions": [{"type": "Ready", "status": "True"}]
                            },
                        }
                    ]
                },
                "secret/synthetic-tls": {
                    "type": "kubernetes.io/tls",
                    "data": {"tls.crt": "c3ludGhldGlj", "tls.key": "c3ludGhldGlj"},
                },
                "secret/synthetic-secret": {
                    "type": "Opaque",
                    "data": {"token": "c3ludGhldGlj"},
                },
            }
            if resource == "externalsecret/synthetic":
                return {
                    "spec": {"target": {"name": "synthetic-secret"}},
                    "status": {"conditions": [{"type": "Ready", "status": "True"}]}
                }, "ok"
            value = resources.get(resource)
            return (value, "ok") if value is not None else (None, "unexpected synthetic query")

        def fake_wrong_ingress_class(
            kubectl: str,
            kubeconfig_path: Path,
            namespace: str | None,
            resource: str,
        ):
            value, detail = fake_kubectl_json(kubectl, kubeconfig_path, namespace, resource)
            if resource == "ingresses.networking.k8s.io" and value is not None:
                drifted = deepcopy(value)
                drifted["items"][0]["spec"]["ingressClassName"] = "nginx"
                return drifted, detail
            return value, detail

        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_wrong_ingress_class),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            wrong_ingress_class_ok, _ = gate.validate_live(
                loaded,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if wrong_ingress_class_ok:
            raise SystemExit("production evidence gate accepted an ingress using the wrong class")

        def fake_drifted_quota(
            kubectl: str,
            kubeconfig_path: Path,
            namespace: str | None,
            resource: str,
        ):
            value, detail = fake_kubectl_json(kubectl, kubeconfig_path, namespace, resource)
            if resource == "resourcequotas" and value is not None:
                drifted = deepcopy(value)
                drifted["items"][0]["spec"]["hard"]["pods"] = "299"
                return drifted, detail
            return value, detail

        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_drifted_quota),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            drifted_quota_ok, _ = gate.validate_live(
                loaded,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if drifted_quota_ok:
            raise SystemExit("production evidence gate accepted a drifted production ResourceQuota")

        def fake_extra_quota(
            kubectl: str,
            kubeconfig_path: Path,
            namespace: str | None,
            resource: str,
        ):
            value, detail = fake_kubectl_json(kubectl, kubeconfig_path, namespace, resource)
            if resource == "resourcequotas" and value is not None:
                drifted = deepcopy(value)
                drifted["items"][0]["spec"]["hard"]["services"] = "1"
                return drifted, detail
            return value, detail

        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_extra_quota),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            extra_quota_ok, _ = gate.validate_live(
                loaded,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if extra_quota_ok:
            raise SystemExit("production evidence gate accepted an unreviewed ResourceQuota ceiling")

        def fake_extra_limit(
            kubectl: str,
            kubeconfig_path: Path,
            namespace: str | None,
            resource: str,
        ):
            value, detail = fake_kubectl_json(kubectl, kubeconfig_path, namespace, resource)
            if resource == "limitranges" and value is not None:
                drifted = deepcopy(value)
                drifted["items"][0]["spec"]["limits"][0]["default"]["hugepages-2Mi"] = "1Gi"
                return drifted, detail
            return value, detail

        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_extra_limit),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            extra_limit_ok, _ = gate.validate_live(
                loaded,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if extra_limit_ok:
            raise SystemExit("production evidence gate accepted an unreviewed LimitRange default")

        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_kubectl_json),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            live_ok, _ = gate.validate_live(
                loaded,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if not live_ok:
            raise SystemExit("production evidence gate rejected a healthy TLS-backed synthetic cluster")

        def fake_missing_tls_secret(
            kubectl: str,
            kubeconfig_path: Path,
            namespace: str | None,
            resource: str,
        ):
            if resource == "secret/synthetic-tls":
                return None, "synthetic TLS Secret is missing"
            return fake_kubectl_json(kubectl, kubeconfig_path, namespace, resource)

        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_missing_tls_secret),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            missing_tls_secret_ok, _ = gate.validate_live(
                loaded,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if missing_tls_secret_ok:
            raise SystemExit("production evidence gate accepted an ingress with a missing TLS Secret")

        def fake_missing_external_target_secret(
            kubectl: str,
            kubeconfig_path: Path,
            namespace: str | None,
            resource: str,
        ):
            if resource == "secret/synthetic-secret":
                return None, "synthetic target Secret is missing"
            return fake_kubectl_json(kubectl, kubeconfig_path, namespace, resource)

        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_missing_external_target_secret),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            missing_external_target_ok, _ = gate.validate_live(
                loaded,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if missing_external_target_ok:
            raise SystemExit("production evidence gate accepted an ExternalSecret without its target Secret")

        def fake_unprotected_plaintext_ingress(
            kubectl: str,
            kubeconfig_path: Path,
            namespace: str | None,
            resource: str,
        ):
            value, detail = fake_kubectl_json(kubectl, kubeconfig_path, namespace, resource)
            if resource == "ingresses.networking.k8s.io" and value is not None:
                unprotected = deepcopy(value)
                unprotected["items"][1]["metadata"]["annotations"][
                    "traefik.ingress.kubernetes.io/router.middlewares"
                ] = "urban-platform-some-other-middleware@kubernetescrd"
                return unprotected, detail
            return value, detail

        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_unprotected_plaintext_ingress),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            unprotected_plaintext_ok, _ = gate.validate_live(
                loaded,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if unprotected_plaintext_ok:
            raise SystemExit("production evidence gate accepted an unprotected plaintext ingress")

        def fake_wrong_release_identity(
            kubectl: str,
            kubeconfig_path: Path,
            namespace: str | None,
            resource: str,
        ):
            value, detail = fake_kubectl_json(kubectl, kubeconfig_path, namespace, resource)
            if resource == "configmap/urban-platform-release-identity" and value is not None:
                wrong = deepcopy(value)
                wrong["data"]["sourceRevision"] = "c" * 40
                return wrong, detail
            return value, detail

        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_wrong_release_identity),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            wrong_release_identity_ok, _ = gate.validate_live(
                loaded,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if wrong_release_identity_ok:
            raise SystemExit("production evidence gate accepted a drifted live release identity")

        def fake_unapproved_pod_image(
            kubectl: str,
            kubeconfig_path: Path,
            namespace: str | None,
            resource: str,
        ):
            value, detail = fake_kubectl_json(kubectl, kubeconfig_path, namespace, resource)
            if resource == "pods" and value is not None:
                unapproved = deepcopy(value)
                unapproved["items"][0]["spec"]["containers"][0]["image"] = (
                    f"registry.internal/platform/unapproved@{DIGEST}"
                )
                return unapproved, detail
            return value, detail

        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_unapproved_pod_image),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            unapproved_pod_image_ok, _ = gate.validate_live(
                loaded,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if unapproved_pod_image_ok:
            raise SystemExit("production evidence gate accepted a pod image outside the approved digest allowlist")

        def fake_substituted_runtime_image(
            kubectl: str,
            kubeconfig_path: Path,
            namespace: str | None,
            resource: str,
        ):
            value, detail = fake_kubectl_json(kubectl, kubeconfig_path, namespace, resource)
            if resource == "pods" and value is not None:
                substituted = deepcopy(value)
                substituted["items"][0]["status"]["containerStatuses"][0]["imageID"] = (
                    f"registry.internal/platform/demo@sha256:{'f' * 64}"
                )
                return substituted, detail
            return value, detail

        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_substituted_runtime_image),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            substituted_runtime_image_ok, _ = gate.validate_live(
                loaded,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if substituted_runtime_image_ok:
            raise SystemExit("production evidence gate accepted a substituted runtime image ID")

        def fake_wrong_cluster_uid(
            kubectl: str,
            kubeconfig_path: Path,
            namespace: str | None,
            resource: str,
        ):
            value, detail = fake_kubectl_json(kubectl, kubeconfig_path, namespace, resource)
            if resource == "namespace/kube-system" and value is not None:
                wrong = deepcopy(value)
                wrong["metadata"]["uid"] = "f469a702-61cf-48b3-9ad0-8cc55dff8ff0"
                return wrong, detail
            return value, detail

        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_wrong_cluster_uid),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            wrong_cluster_uid_ok, _ = gate.validate_live(
                loaded,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if wrong_cluster_uid_ok:
            raise SystemExit("production evidence gate accepted evidence for a different cluster UID")

        def fake_missing_container_status(
            kubectl: str,
            kubeconfig_path: Path,
            namespace: str | None,
            resource: str,
        ):
            value, detail = fake_kubectl_json(kubectl, kubeconfig_path, namespace, resource)
            if resource == "pods" and value is not None:
                missing = deepcopy(value)
                missing["items"][0]["status"]["containerStatuses"] = []
                return missing, detail
            return value, detail

        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_missing_container_status),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            missing_container_status_ok, _ = gate.validate_live(
                loaded,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if missing_container_status_ok:
            raise SystemExit("production evidence gate accepted a Running pod without container readiness")

        def fake_unrelated_certificate(
            kubectl: str,
            kubeconfig_path: Path,
            namespace: str | None,
            resource: str,
        ):
            value, detail = fake_kubectl_json(kubectl, kubeconfig_path, namespace, resource)
            if resource == "certificates.cert-manager.io" and value is not None:
                unrelated = deepcopy(value)
                unrelated["items"][0]["spec"]["secretName"] = "unrelated-tls"
                return unrelated, detail
            return value, detail

        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_unrelated_certificate),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            unrelated_certificate_ok, _ = gate.validate_live(
                loaded,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if unrelated_certificate_ok:
            raise SystemExit("production evidence gate accepted an unrelated Ready certificate")

        def fake_two_node_kubectl_json(
            kubectl: str,
            kubeconfig_path: Path,
            namespace: str | None,
            resource: str,
        ):
            value, detail = fake_kubectl_json(kubectl, kubeconfig_path, namespace, resource)
            if resource == "nodes" and value is not None:
                return {"items": nodes[:2]}, detail
            return value, detail

        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_two_node_kubectl_json),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            two_node_ok, _ = gate.validate_live(
                loaded,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if two_node_ok:
            raise SystemExit("production evidence gate accepted fewer than three Ready nodes")

        wrong_count = gate.load_yaml(config_path)
        wrong_count["liveCluster"]["expectedPostgresClusters"] = 1
        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_kubectl_json),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            wrong_count_ok, _ = gate.validate_live(
                wrong_count,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if wrong_count_ok:
            raise SystemExit("production evidence gate trusted a lowered PostgreSQL cluster count")

        wrong_kafka_version = gate.load_yaml(config_path)
        wrong_kafka_version["liveCluster"]["expectedKafkaVersion"] = "4.2.0"
        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_kubectl_json),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            wrong_kafka_version_ok, _ = gate.validate_live(
                wrong_kafka_version,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if wrong_kafka_version_ok:
            raise SystemExit("production evidence gate trusted a mismatched Kafka version claim")

        wrong_psa_version = gate.load_yaml(config_path)
        wrong_psa_version["liveCluster"]["expectedPodSecurityVersion"] = "v1.35"
        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_kubectl_json),
            patch.object(gate, "validate_kafka_data_path", return_value=(True, "synthetic pass")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            wrong_psa_version_ok, _ = gate.validate_live(
                wrong_psa_version,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if wrong_psa_version_ok:
            raise SystemExit("production evidence gate trusted a mismatched Pod Security version claim")

        with (
            patch.object(gate.shutil, "which", return_value="kubectl"),
            patch.object(gate.kafka_readiness, "kubectl_api_ready", return_value=True),
            patch.object(gate, "kubectl_json", side_effect=fake_kubectl_json),
            patch.object(gate, "validate_kafka_data_path", return_value=(False, "synthetic failure")),
            patch.object(gate, "validate_ingress_probe", return_value=(True, "synthetic ingress pass")),
        ):
            failed_data_path_ok, _ = gate.validate_live(
                loaded,
                run_live=True,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
            )
        if failed_data_path_ok:
            raise SystemExit("production evidence gate ignored a failed Kafka-to-ClickHouse path")

        gate_report = root / "gate-report.md"
        with (
            patch.object(
                gate,
                "validate_trust_policy",
                return_value=(
                    True,
                    "synthetic trust pass",
                    gate.TrustPolicy("cosign", TRUSTED_APPROVERS),
                ),
            ),
            patch.object(gate, "validate_source_checkout", return_value=(True, "synthetic source pass")),
            patch.object(gate, "validate_live", return_value=(True, "synthetic live pass")),
        ):
            gate_result = gate.main(
                [
                    "--config",
                    str(config_path),
                    "--trust-policy",
                    str(trust_path),
                    "--base-values",
                    str(base_values),
                    "--values",
                    str(public_values),
                    "--output",
                    str(gate_report),
                    "--live",
                ]
            )
        if gate_result != 0 or "Operational evidence score: `100/100`" not in gate_report.read_text(encoding="utf-8"):
            raise SystemExit("production evidence gate CLI did not enforce the signed version 4 pass path")

        if not (
            trust_ok
            and attestation_ok
            and clean_source_ok
            and release_ok
            and image_ok
            and dr_ok
            and live_ok
            and image_count == 1
            and dr_count == len(gate.REQUIRED_DR_ARTIFACTS)
        ):
            raise SystemExit("synthetic production evidence gate test failed")
    print("Production evidence gate synthetic pass-path test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
