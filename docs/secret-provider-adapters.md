# Secret Provider Adapters

Secret provider adapters define how imported or chart-managed runtime secrets
reach Kubernetes without committing private values. They are optional and
disabled by default.

## Profiles

`config/secret-provider-adapters.yaml` defines these public-safe profiles:

- `kubernetes-direct`: direct Kubernetes Secret import for lab or emergency
  migration. It requires `MIGRATION_ALLOW_SECRET_MATERIAL=true`.
- `external-secrets`: External Secrets Operator renders `ExternalSecret`
  resources that pull values from a configured `SecretStore` or
  `ClusterSecretStore`.
- `vault`: Vault-backed External Secrets profile. This is the recommended
  enterprise path when Vault is the source of truth.
- `sops`: Git-encrypted files with SOPS and age. This is a Git workflow, not an
  automatic cluster sync path.
- `sealed-secrets`: GitOps-friendly sealed manifests generated with the target
  cluster public certificate.

## Import Integration

The migration workflow defaults to direct Kubernetes Secret import only after
the operator explicitly allows secret material:

```bash
make import-auto PROJECT_PATH=/path/to/compose-project \
  MIGRATION_ALLOW_SECRET_MATERIAL=true
```

To avoid applying plain Kubernetes Secret manifests during import, select an
automatic runtime-sync provider:

```bash
make import-auto PROJECT_PATH=/path/to/compose-project \
  MIGRATION_SECRET_PROVIDER=external-secrets \
  MIGRATION_SECRET_STORE_NAME=vault \
  MIGRATION_SECRET_STORE_KIND=ClusterSecretStore \
  MIGRATION_SECRET_REMOTE_PREFIX=example/urban-platform/import
```

With `MIGRATION_SECRET_PROVIDER=external-secrets` or
`MIGRATION_SECRET_PROVIDER=vault`, the import stage applies `ExternalSecret`
resources instead of plain `Secret` objects. The remote provider must already
contain matching keys under `MIGRATION_SECRET_REMOTE_PREFIX`. The generated
Kubernetes objects do not include secret values.

`MIGRATION_SECRET_PROVIDER=sops` and
`MIGRATION_SECRET_PROVIDER=sealed-secrets` are plan/handoff modes. They prevent
plain Secret application and require the chosen Git encryption workflow to
produce the final encrypted artifacts.

## Helm Integration

The Helm chart keeps `secretManagement.enabled=false` by default. When External
Secrets Operator is installed and a store exists, enable only the mappings you
need:

```yaml
secretManagement:
  enabled: true
  provider: external-secrets
  secretStoreRef:
    name: vault
    kind: ClusterSecretStore
  externalSecrets:
    registryCredentials:
      enabled: true
    ingressTls:
      enabled: true
```

## Production Guidance

For premium or enterprise deployments, prefer Vault or a managed cloud secret
manager through External Secrets Operator. Use SOPS or Sealed Secrets when
GitOps ownership requires encrypted manifests in Git. Keep direct Kubernetes
Secret import as a controlled lab or emergency path only.
