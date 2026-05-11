# Release Guide

Releases are chart releases. They package the Helm chart and publish release evidence only; production inventories, kubeconfigs, decrypted secrets, and disclosure-sensitive data must stay out of the release artifact set.

## Local Checklist

1. Update `CHANGELOG.md` if the release changes user-visible behavior.
2. Confirm `helm/city-intersection-platform/Chart.yaml` has the intended `version`.
3. Run the local gates:

```bash
make lint
make validate
make policy
make deploy-dry-run
```

4. Package release evidence locally when Helm is available:

```bash
make release-evidence
sha256sum -c dist/SHA256SUMS
```

## Tag Release

The Git tag must match the Helm chart version exactly after removing the leading `v`.

```bash
git tag -a v0.1.0 -m "city-intersection-project v0.1.0"
git push origin v0.1.0
```

GitHub Actions packages the Helm chart on tags matching `v*.*.*`, renders the default manifest, generates SPDX SBOM metadata, writes SHA-256 checksums, uploads the evidence artifact, and creates GitHub artifact attestations. GitLab CI mirrors the checksum and SBOM evidence generation on SemVer tags.

## Verify Release Evidence

```bash
sha256sum -c dist/SHA256SUMS
gh attestation verify dist/city-intersection-platform-0.1.0.tgz --repo OWNER/REPO
```

If the repository is private and artifact attestations are not available on the current GitHub plan, keep checksums and SBOMs as mandatory release evidence and enable private attestations before regulated production use.
