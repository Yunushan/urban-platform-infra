# Storage Tiers

This project supports an optional hot/warm/cold storage architecture. The
default lab profile does not require separate storage classes or object storage.
Enable tiers only when the target environment provides the matching storage
backends.

Keep real storage class names, object-store endpoints, bucket names, credentials,
and retention obligations in private values or secret managers when they are
environment-sensitive.

## Tier Model

| Tier | Purpose | Typical Backend | Default State |
|---|---|---|---|
| Hot | Active read/write data | SSD, NVMe, fast replicated block storage | Disabled until a class is configured |
| Warm | Compressed or lower-traffic history | standard SSD, replicated block storage | Disabled |
| Cold | Backups, dumps, old logs, release evidence | S3-compatible object storage or archive PVCs | Disabled |

The public contract is in [`config/storage-tiers.yaml`](../config/storage-tiers.yaml).
The Helm values entry point is `storageTiers` in
[`helm/urban-platform-infra/values.yaml`](../helm/urban-platform-infra/values.yaml).

## Helm Values

Set only the tiers that exist in the target environment:

```yaml
storageTiers:
  hot:
    enabled: true
    storageClassName: fast-rwo
  warm:
    enabled: true
    storageClassName: standard-rwo
  cold:
    enabled: true
    storageClassName: archive-rwo
    objectStore:
      enabled: true
      provider: s3-compatible
      bucket: platform-archive
      prefix: urban-platform
      secretRef:
        name: object-storage-credentials
        namespace: urban-platform
        accessKeyIdKey: accessKeyId
        secretAccessKeyKey: secretAccessKey
```

If an individual workload sets its own `storage.className`, that explicit value
wins. Otherwise, stateful chart components can fall back to the enabled hot tier.

## Current Chart Behavior

The following chart resources can use `storageTiers.hot.storageClassName` as a
fallback when their explicit storage class is empty:

- CloudNativePG database clusters
- Kafka StatefulSet
- ZooKeeper StatefulSet
- Redis StatefulSet
- generic StatefulSet workloads rendered by the platform chart

Cold object-store settings are a public-safe contract for backups, imports, and
archive integrations. They do not create provider-specific credentials or bucket
resources by themselves.

## Lab Guidance

For a small lab:

```yaml
storageTiers:
  hot:
    enabled: true
    storageClassName: local-path
  warm:
    enabled: false
    storageClassName: ''
  cold:
    enabled: false
    storageClassName: ''
```

This helps PVCs bind predictably, but it does not reduce RAM usage. Large
imports still need service selection, lower replicas, or larger nodes.

## Production Guidance

For production:

- Use a durable, monitored hot storage class for active databases and messaging.
- Use warm storage for compressed analytics or medium-retention observability
  data when supported by the backend.
- Use cold object storage for database backups, import dumps, snapshots, old
  logs, and release evidence.
- Keep object-store credentials in External Secrets, SOPS, Sealed Secrets, or
  Vault.
- Test restore workflows before treating cold storage as production protection.

## Import Workflow

`import-auto` can continue to write local private dump artifacts under the
operator private directory. When cold storage is enabled in a deployment, use it
as the long-retention destination for:

- PostgreSQL dump artifacts
- migration evidence
- generated release evidence
- optional observability snapshots

The cold tier is intentionally optional so disconnected labs and no-registry
preload workflows remain simple.
