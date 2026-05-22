# Secrets and Configuration Management

This repository must not contain real credentials, private inventories, kubeconfigs, production endpoints, or disclosure-related data. It stores only contracts, examples, and disabled-by-default integration scaffolding.

## Secret Delivery Model

Use this priority order:

1. External Secrets Operator for runtime Kubernetes secrets sourced from a managed provider.
2. SOPS/age for encrypted files that must live in Git.
3. Sealed Secrets only when the target cluster owns the decryption key and GitOps requires sealed manifests.

Do not commit plain Kubernetes `Secret` manifests. Kubernetes Secrets are API objects for confidential data, but they still require encryption at rest, least-privilege RBAC, and careful workload scoping.

## Repository Contract

The secret inventory lives in `config/secrets.contract.yaml`. It defines:

- the Kubernetes secret name expected by workloads,
- the secret type,
- whether the value is required before production,
- the approved delivery mechanism,
- an example remote reference path.

The contract intentionally does not include values.

## Private Data Audit

Run a public-safe audit before opening pull requests, publishing reports, or
sharing repository snapshots:

```bash
make private-data-audit
```

The audit writes `reports/private-data-audit.md`. It reports categories,
repository-relative paths, and line numbers only; it does not print matched
secret values, private IPs, kubeconfig content, or disclosure-prone names. The
gate checks:

- high-confidence token and private-key patterns,
- private-looking infrastructure address patterns,
- kubeconfig-like documents,
- decrypted secret artifact naming patterns,
- non-placeholder files under `secrets/` and `inventories/prod/`,
- original disclosure-prone service identifiers.

Use `python scripts/tools/private_data_audit.py --include-untracked` when you
want to scan untracked non-ignored files before sharing a working tree snapshot.
Ignored directories such as `reports/`, `dist/`, `.git/`, `.venv/`, and
`node_modules/` remain excluded by default.

## Provider Adapters

Secret provider adapter profiles live in
`config/secret-provider-adapters.yaml`. They are disabled by default and define
the supported runtime or Git-encrypted delivery modes:

- `external-secrets`: renders External Secrets Operator resources that pull
  values from a managed provider.
- `vault`: Vault-backed External Secrets profile for enterprise deployments.
- `sops`: encrypted files in Git with SOPS and age.
- `sealed-secrets`: GitOps-friendly encrypted Secret manifests.
- `kubernetes-direct`: a guarded lab or emergency path that requires
  `MIGRATION_ALLOW_SECRET_MATERIAL=true`.

See [`docs/secret-provider-adapters.md`](secret-provider-adapters.md) for the
import switches and production guidance.

## External Secrets

The Helm chart can render `ExternalSecret` resources from `secretManagement.externalSecrets`, but the feature is disabled by default:

```yaml
secretManagement:
  enabled: false
```

Enable it only after installing External Secrets Operator and creating the referenced `SecretStore` or `ClusterSecretStore` in the cluster.
During import, `MIGRATION_SECRET_PROVIDER=external-secrets` or
`MIGRATION_SECRET_PROVIDER=vault` applies `ExternalSecret` resources instead of
plain Kubernetes Secret manifests. Remote provider values must already exist
under `MIGRATION_SECRET_REMOTE_PREFIX`.

## SOPS

Use `.sops.yaml.example` as a starting point. Replace the age recipient with your public recipient, copy it to `.sops.yaml`, and encrypt only files under `secrets/`:

```bash
cp .sops.yaml.example .sops.yaml
sops encrypt --filename-override secrets/prod.sops.yaml /dev/stdin > secrets/prod.sops.yaml
```

The repository ignores decrypted outputs and the `secrets/` directory remains placeholder-only by default. Store age private keys outside the repo.

## Operational Rules

- Keep `inventories/prod/` placeholder-only in Git.
- Store bootstrap tokens in Ansible Vault, SOPS, or a managed secret provider.
- Keep registry credentials in an external provider and sync them to `registry-credentials`.
- Use cert-manager for TLS issuance when possible; otherwise sync `urban-platform-tls` through External Secrets.
- Rotate bootstrap tokens after cluster creation.
- Rotate any leaked value immediately and treat the Git history as exposed.

## References

- Kubernetes Secrets: https://kubernetes.io/docs/concepts/configuration/secret/
- External Secrets Operator: https://external-secrets.io/
- External Secrets Helm chart: https://artifacthub.io/packages/helm/external-secrets-operator/external-secrets
- SOPS: https://github.com/getsops/sops
- Sealed Secrets: https://github.com/bitnami-labs/sealed-secrets
