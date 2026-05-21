# Backup And Restore

This document defines the public-safe backup and restore architecture for the
platform. It intentionally avoids real bucket names, node addresses, secret
names, database names, and site-specific schedules.

Backups are disabled by default. Enabling a backup layer must be an explicit
operator decision after object storage, credentials, retention, and restore
drills are ready.

## Scope

The optional backup architecture covers:

- RKE2 embedded etcd snapshots for cluster control-plane recovery.
- CloudNativePG Barman object-store backups for PostgreSQL-family databases.
- Velero namespace and persistent-volume metadata backups.
- Imported image archive retention for RKE2 preload workflows.
- External backup adapters for host, VM, legacy Compose, and operator artifact
  backups.
- Secret source-of-truth recovery through External Secrets, SOPS, Sealed
  Secrets, Vault, or an equivalent approved system.

The chart does not create object-store buckets, cloud credentials, or plaintext
secret material. Those are environment-owned resources.

## Defaults

The committed defaults are intentionally inert:

```yaml
backup:
  enabled: false
  profile: disabled
  velero:
    enabled: false
    installOperator: false
  externalProviders:
    urbackup:
      enabled: false
      installInCluster: false
    restic:
      enabled: false
    kopia:
      enabled: false
    borg:
      enabled: false
databases:
  backup:
    enabled: false
    objectStore:
      enabled: false
    schedule:
      enabled: false
```

`make backup-plan` generates a public-safe posture report without applying
anything to the cluster:

```bash
make backup-plan
```

## Storage Targets

Use the optional hot/warm/cold storage model:

| Tier | Backup Role |
|---|---|
| Hot | Active database, Kafka, Redis, and workload PVCs |
| Warm | Medium-retention history and compressed operational data |
| Cold | Database backups, etcd snapshots, import dumps, image archives, and release evidence |

Cold storage should normally be object storage with encryption, lifecycle
rules, and immutability or object lock when the provider supports it.

## CloudNativePG Backups

CloudNativePG backup rendering is controlled by `databases.backup.enabled`.
When enabled, the chart renders `spec.backup.barmanObjectStore` only if an
object-store target and credential reference are configured. Scheduled backups
are separate and stay disabled until `databases.backup.schedule.enabled=true`.

Minimal production override shape:

```yaml
databases:
  backup:
    enabled: true
    retentionPolicy: 30d
    objectStore:
      enabled: true
      provider: s3-compatible
      bucket: example-platform-backups
      prefix: urban-platform/databases
      endpointURL: https://object-store.example.internal
      secretRef:
        name: cnpg-backup-credentials
        accessKeyIdKey: accessKeyId
        secretAccessKeyKey: secretAccessKey
    schedule:
      enabled: true
      cron: "0 0 2 * * *"
```

Keep the real bucket, endpoint, and secret reference in private values or a
private GitOps repository.

## Velero

Velero is optional and disabled in Helmfile by default. The operator chart is
installed only when `DEPLOY_ENABLE_VELERO=true` or `INSTALL_VELERO=true` is
passed intentionally.

Example operator install flags:

```bash
make install-operators \
  DEPLOY_ENABLE_VELERO=true \
  VELERO_USE_SECRET=true \
  VELERO_EXISTING_SECRET=velero-object-store \
  VELERO_BUCKET=example-platform-backups \
  VELERO_S3_URL=https://object-store.example.internal
```

Velero should not be treated as the only database backup. Use CloudNativePG
logical/operator backups for PostgreSQL-family recovery and Velero for
Kubernetes object, PVC metadata, and non-database workload recovery.

## External Backup Adapters

External backup adapters are optional and disabled by default. They are modeled
so the platform can document and validate backup intent without installing
extra services into a constrained lab cluster.

| Provider | Recommended Role | Default |
|---|---|---|
| UrBackup | Host, VM, file, Windows/Linux endpoint, and legacy Compose backup outside Kubernetes | Disabled, external only |
| restic | Encrypted backup for operator private artifacts and file-level repositories | Disabled |
| Kopia | Encrypted repository-backed file backup alternative to restic | Disabled |
| Borg | Efficient Linux-oriented encrypted repository backup alternative | Disabled |

UrBackup can be useful when the migration still depends on VM or bare-metal
hosts, but it should not replace CloudNativePG database backups or Velero
Kubernetes object recovery. For production, run the UrBackup server outside the
application cluster or on dedicated backup infrastructure.

Example public-safe values shape:

```yaml
backup:
  externalProviders:
    urbackup:
      enabled: true
      mode: external
      installInCluster: false
      endpoint: https://backup.example.internal
      secretRef:
        name: urbackup-client-credentials
    restic:
      enabled: true
      mode: operator-artifacts
      repository: s3:s3.example.internal/platform-artifacts
      secretRef:
        name: restic-repository-credentials
```

Keep real endpoints, repository URLs, and credential references in private
values or private operator records.

## RKE2 Etcd

RKE2 etcd snapshots protect the control plane. Store snapshot archives outside
the nodes when production recovery matters. Keep snapshot credentials and target
locations private.

Use etcd snapshots for cluster recovery, not application-level database
rollback. Database restore should use database-native backup artifacts.

## Restore Drills

Backups are not production-ready until restores are tested.

Recommended cadence:

- CloudNativePG database restore: monthly.
- RKE2 etcd snapshot restore: quarterly.
- Velero namespace restore: quarterly.
- External backup adapter restore: quarterly.
- Full application recovery rehearsal: before major releases and after major
  platform changes.

Every restore drill should record:

- backup artifact age
- restore target
- restore duration
- data validation result
- application smoke-test result
- operator notes and follow-up actions

Keep restore evidence private when it contains environment details.
