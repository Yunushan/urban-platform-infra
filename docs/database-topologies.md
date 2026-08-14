# Database Topologies

The chart keeps the existing per-service database layout as the default and adds
two explicit alternatives. The topology controls physical CNPG clusters; the
logical database names from `databases.instances` remain the application
contract and are preserved in the private migration target map.

| Mode | Standard PostgreSQL | PostGIS | TimescaleDB | Recommended use |
|---|---|---|---|---|
| `per-service` | One CNPG cluster per enabled instance | Separate | Separate | Maximum isolation and independent lifecycle |
| `consolidated` | One shared 3-instance CNPG cluster | Separate | Separate | Lower lab footprint and simpler standard PostgreSQL operations |
| `hybrid` | One shared 3-instance CNPG cluster | Separate | Separate | Recommended production starting point when standard PostgreSQL services can share a failure domain |

Consolidation is limited to the standard `postgresql` engine. PostGIS and
TimescaleDB retain their own images and clusters because extensions and upgrade
lifecycles should not be mixed into a generic PostgreSQL cluster.

## Select A Mode

For Helm deployment:

```bash
make deploy-auto DATABASE_TOPOLOGY=hybrid
```

For migration automation:

```bash
make import-migrate \
  PROJECT_PATH=/path/to/compose-project \
  MIGRATION_DATABASE_TOPOLOGY=hybrid \
  MIGRATION_STAGE=manifests \
  MIGRATION_EXECUTE=true
```

The equivalent public-safe overlays are:

- `examples/database-topology-consolidated.values.yaml`
- `examples/database-topology-hybrid.values.yaml`

The consolidated cluster defaults to `platform-postgres`, PostgreSQL 18, three
instances, and a shared application owner. Each enabled source PostgreSQL
database is created as a separate logical database during CNPG initialization.
The migration target map then points each service at the shared cluster while
retaining its logical database name.

The constrained lab profile may intentionally apply
`global.replicaOverride=1`; the production overlay preserves the configured
three CNPG instances.

## Operational Trade-Offs

Consolidation reduces cluster, PVC, and image overhead, but it also combines
resource contention, maintenance windows, and failure domains. Keep per-service
mode when services need independent restore schedules, strict noisy-neighbor
isolation, different PostgreSQL major versions, or separate ownership controls.

CNPG storage changes remain immutable for an existing cluster. Select the
topology before first deployment, or use the database backup/restore runbook
when moving an existing installation between modes. Do not delete live PVCs as
an upgrade shortcut.

The topology setting does not expose credentials, endpoints, node addresses, or
private inventory data. Those remain runtime/private state.
