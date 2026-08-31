# Production Readiness

The repository has three separate gates:

1. `make production-readiness` checks public repository contracts, Helm rendering,
   policy tests, CI/release controls, and private-data hygiene. It does not claim
   that a live cluster or private registry is healthy.
2. `make production-readiness-gate` runs on a private operator or release runner.
   It fails closed until the private production overlay, image-promotion evidence,
   disaster-recovery evidence, and live Kubernetes checks are all available.
3. `make kafka-clickhouse-readiness` scores the Kafka-to-ClickHouse data path
   independently. It requires private deployment inputs and read-only live
   evidence to meet its mandatory `100/100` threshold.

## Private Evidence Manifest

Start from the version 4 `config/production-evidence.example.yaml` and the
separate `config/production-evidence-trust.example.yaml`. Copy both outside Git,
for example to `/var/lib/urban-platform/private/`. Replace every placeholder
with private values. Keep the copied manifest, trust policy, evidence index,
kubeconfig, standardized Sigstore bundle, and evidence bodies outside the repository.

The evidence manifest records the exact SHA-256 of the private values overlay
and image evidence index. Sign the exact completed manifest bytes with Cosign;
keep the signing private key in the approved signing system and configure only
the trusted public key, standardized bundle, and approver allowlist in the
root-owned trust policy:

```bash
cosign sign-blob \
  --yes \
  --key /secure/signing/production-evidence.key \
  --bundle /private/production/production-evidence.sigstore.json \
  /private/production/production-evidence.yaml
```

The verifier requires Cosign `3.1.3` or newer and rejects legacy bundles. The
bundle must use `application/vnd.dev.sigstore.bundle.v0.3+json`.

Version 4 attestations are deliberately short-lived. Set `attestation.issuedAt`
and `attestation.expiresAt` no more than 24 hours apart, generate a fresh UUIDv4
for `release.deploymentId`, and bind `liveCluster.clusterUid` to the UID of the
target cluster's `kube-system` Namespace. The gate also requires its repository
checkout to be clean and exactly at the signed `release.sourceRevision`.
Set `liveCluster.expectedPodSecurityVersion` to the same pinned Kubernetes minor
used by `namespace.podSecurity.version`; the live gate verifies all three PSA
version labels against that value.

The private production overlay must also bind the deployment to the same
release identity recorded in the signed evidence manifest:

```yaml
global:
  releaseIdentity:
    enabled: true
    tag: v1.2.3
    sourceRevision: 0123456789abcdef0123456789abcdef01234567
    deploymentId: 123e4567-e89b-42d3-a456-426614174000
```

Helm publishes that identity as `ConfigMap/urban-platform-release-identity`.
The live gate rejects a cluster whose ConfigMap differs from the signed tag,
source revision, or deployment ID, and rejects a Kubernetes API whose cluster
UID differs from the signed target. It also rejects every pod container, init container, or
ephemeral container whose declared image is not an exact approved
private-registry digest reference, or whose runtime status lacks an immutable
image ID.

The image evidence index must contain one entry for every image path found after
merging the base values, `values-production.yaml`, and the private overlay:

```yaml
images:
  - path: workloads.example.image
    reference: registry.internal.example/platform/example@sha256:<64-hex-digest>
    digest: sha256:<64-hex-digest>
    vulnerabilityScan:
      path: scans/example.json
      sha256: sha256:<64-hex-digest>
      capturedAt: '2026-08-25T09:00:00Z'
      approvedBy: security-reviewer
    sbom:
      path: sbom/example.spdx.json
      sha256: sha256:<64-hex-digest>
      capturedAt: '2026-08-25T09:00:00Z'
      approvedBy: security-reviewer
    signatureOrAttestation:
      path: signatures/example.json
      sha256: sha256:<64-hex-digest>
      capturedAt: '2026-08-25T09:00:00Z'
      approvedBy: release-reviewer
    promotionRecord:
      path: promotions/example.yaml
      sha256: sha256:<64-hex-digest>
      capturedAt: '2026-08-25T09:00:00Z'
      approvedBy: release-reviewer
```

The gate verifies the standardized Sigstore bundle, trusted reviewer allowlist,
private-overlay and evidence-index hashes, image digest, exact private-registry
reference, complete path coverage, artifact SHA-256, and capture-time freshness. The
default maximum age is 30 days for image evidence and 180 days for DR evidence.
The gate reads artifact bytes only to calculate their digest and never includes
their contents or private paths in its public-safe report.

## Run

```bash
make production-readiness
make production-readiness-gate \
  PRODUCTION_EVIDENCE_CONFIG=/var/lib/urban-platform/private/production-evidence.yaml \
  PRODUCTION_EVIDENCE_TRUST_POLICY=/var/lib/urban-platform/private/production-evidence-trust.yaml \
  PRODUCTION_EVIDENCE_LIVE=true \
  IMPORT_REDACT=true

make kafka-clickhouse-readiness \
  KAFKA_CLICKHOUSE_PRIVATE_VALUES=/var/lib/urban-platform/private/values-production-private.yaml \
  KAFKA_CLICKHOUSE_KUBECONFIG=/root/.kube/config \
  KAFKA_CLICKHOUSE_LIVE=true

make kafka-clickhouse-reconcile \
  KAFKA_CLICKHOUSE_PRIVATE_VALUES=/var/lib/urban-platform/private/values-production-private.yaml \
  KAFKA_CLICKHOUSE_KUBECONFIG=/root/.kube/config \
  KAFKA_CLICKHOUSE_APPLY=true
```

The live portion is mandatory and cannot be disabled in a passing production
evidence manifest. It performs an authenticated `/readyz` probe, a proxy-free
GET against the signed production HTTPS endpoint, an HTTP-to-HTTPS redirect
probe, and read-only Kubernetes checks for three schedulable, pressure-free failure-domain nodes,
the signed in-cluster release identity, approved digest-only runtime images,
restricted namespace policy, fully converged workloads, three-instance
CloudNativePG clusters and scheduled backups, Ready ExternalSecrets with
correctly materialized target Secret data, a TLS Ingress plus an explicit
HTTP-to-HTTPS redirect, owned TLS material, and a full `100/100`
Kafka-to-ClickHouse data-path result. The signed live manifest must enumerate
the complete expected PodDisruptionBudget and autoscaler name sets; the gate
rejects missing, unexpected, or unhealthy entries. It never prints kubeconfig contents,
credentials, endpoint values, node addresses, or private artifact paths. The
signed `liveCluster.ingressProbe` section must contain the HTTPS and HTTP URLs,
expected response classes, and `tlsVerify: true`; a private `caBundle` may be
provided for an enterprise CA.

`kafka-clickhouse-reconcile` is plan-only unless `KAFKA_CLICKHOUSE_APPLY=true`.
Apply mode stops before mutation when its static, CRD, exact digest-pinned operator, durable
storage, failure-domain, or external secret store preflight fails. A successful
Helm reconciliation still has to pass two consecutive live gate observations.

A missing, expired, replayed, or unsigned manifest, untrusted approver, dirty
source checkout, wrong cluster UID, checksum drift, missing
artifact, unpinned image, unready workload, or unverified restore drill returns
a non-zero exit code. A public repository score
of `100/100` therefore means the repository is contract-ready; it is not a
substitute for the private operational gate.

The mutating Makefile deployment path also requires
`DEPLOY_PRIVATE_VALUES=/path/outside/the/repository` and applies that file
last. This prevents a production deployment from accidentally using only the
public profile baseline, which contains sanitized placeholders and versioned
reference tags for documentation.

Before any production cluster mutation, `make deploy` automatically runs
`production-private-preflight`. It validates the effective base, public, and
private values, requires a real release identity and registry image pull
Secret, rejects placeholder ExternalSecret paths, and requires every effective
runtime image to carry a valid `sha256` digest. The preflight is skipped for
the lab profile; the production evidence gate remains the required post-deploy
check for signed image evidence and live runtime identity.
