# Production Readiness

The repository has two separate gates:

1. `make production-readiness` checks public repository contracts, Helm rendering,
   policy tests, CI/release controls, and private-data hygiene. It does not claim
   that a live cluster or private registry is healthy.
2. `make production-readiness-gate` runs on a private operator or release runner.
   It fails closed until the private production overlay, image-promotion evidence,
   disaster-recovery evidence, and live Kubernetes checks are all available.

## Private Evidence Manifest

Start from `config/production-evidence.example.yaml` and copy it outside Git,
for example to `/var/lib/urban-platform/private/production-evidence.yaml`.
Replace every placeholder with private values. Keep the copied manifest,
evidence index, kubeconfig, and evidence bodies outside the repository.

The image evidence index must contain one entry for every image path found after
merging the base values, `values-production.yaml`, and the private overlay:

```yaml
images:
  - path: workloads.example.image
    reference: registry.internal.example/platform/example@sha256:<64-hex-digest>
    digest: sha256:<64-hex-digest>
    vulnerabilityScan: scans/example.json
    sbom: sbom/example.spdx.json
    signatureOrAttestation: signatures/example.json
    promotionRecord: promotions/example.yaml
```

The gate verifies the digest syntax, private-registry prefix, path coverage,
and non-empty evidence files. It does not trust a report merely because its
filename exists in Git.

## Run

```bash
make production-readiness
make production-readiness-gate \
  PRODUCTION_EVIDENCE_CONFIG=/var/lib/urban-platform/private/production-evidence.yaml \
  PRODUCTION_EVIDENCE_LIVE=true \
  IMPORT_REDACT=true
```

The live portion performs read-only Kubernetes API checks for node readiness,
workload readiness, three-instance CloudNativePG clusters, and the expected
three-replica Apache Kafka/Strimzi deployment. It never prints kubeconfig
contents, credentials, node addresses, or private artifact paths.

A missing manifest, missing artifact, unpinned image, unready workload, or
unverified restore drill returns a non-zero exit code. A public repository score
of `100/100` therefore means the repository is contract-ready; it is not a
substitute for the private operational gate.
