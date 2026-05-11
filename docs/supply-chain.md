# Supply Chain and Release Integrity

This repository ships infrastructure deployment assets, not private operational data. Release evidence must therefore prove the source, chart package, rendered manifest, and metadata without embedding credentials, production endpoints, customer data, or disclosure material.

## Article 6 Baseline

Release integrity depends on four controls:

1. The Git tag must match `helm/city-intersection-platform/Chart.yaml`.
2. Every packaged chart release must include SHA-256 checksums.
3. Every packaged chart release must include an SPDX JSON SBOM.
4. GitHub releases must produce artifact attestations with OIDC-backed signing.

The GitHub release workflow packages the Helm chart, renders the default manifest, generates `dist/SHA256SUMS`, generates `dist/city-intersection-platform.spdx.json`, and attests the evidence with GitHub artifact attestations. The GitLab tag pipeline mirrors the checksum and SBOM evidence path for private GitLab users.

## Release Evidence

Expected release evidence:

```text
dist/city-intersection-platform-<version>.tgz
dist/rendered.yaml
dist/city-intersection-platform.spdx.json
dist/SHA256SUMS
```

The checksum file is the first offline integrity check. The GitHub attestation is the provenance check that links the artifact to the repository, workflow, commit, tag, and OIDC identity used by GitHub Actions.

## Verification

After downloading release evidence:

```bash
sha256sum -c dist/SHA256SUMS
gh attestation verify dist/city-intersection-platform-0.1.0.tgz --repo OWNER/REPO
```

For private repositories, GitHub artifact attestations require a plan that supports private/internal attestations. If that is not enabled yet, keep checksums and SBOMs as required release artifacts and enable attestations before regulated production use.

## Dependency Intake

Dependabot tracks GitHub Actions and Python CI dependencies. Pull requests run dependency review where the repository plan supports it, and private repositories keep that job non-blocking until GitHub Advanced Security or equivalent policy support is available. GitLab CI images are pinned to explicit tags instead of `latest`.

## Action Pinning

Full-length commit SHA pins are the preferred enterprise control for GitHub Actions because tags can move. This repository also blocks floating `@main` and `@master` action refs. Before a regulated production release, convert approved action tags to reviewed full-length commit SHAs and keep Dependabot enabled for digest updates.

## Operator Rules

- Do not release artifacts from a dirty worktree.
- Do not attach kubeconfigs, decrypted SOPS files, private inventories, or environment files to release artifacts.
- Do not publish rendered manifests from production override files unless they have passed disclosure review.
- Treat the SBOM and checksum files as release evidence; do not edit them by hand.

## References

- GitHub artifact attestations: https://docs.github.com/en/actions/concepts/security/artifact-attestations
- GitHub OIDC hardening: https://docs.github.com/actions/concepts/security/about-security-hardening-with-openid-connect
- GitHub Actions security hardening: https://docs.github.com/actions/learn-github-actions/security-hardening-for-github-actions
- Dependency Review Action: https://github.com/actions/dependency-review-action
- SLSA provenance: https://slsa.dev/spec/v1.2/build-provenance
