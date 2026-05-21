# Database Switching

Default data profile is PostgreSQL-compatible because the supplied running stack uses PostgreSQL, PostGIS, and TimescaleDB images.

Switch in config:

```bash
python3 scripts/configure.py --database postgresql
python3 scripts/configure.py --database cockroachdb
python3 scripts/configure.py --database mysql
python3 scripts/configure.py --database mariadb
python3 scripts/configure.py --database microsoft-sql-server
python3 scripts/configure.py --database mongodb
python3 scripts/configure.py --database sqlite
python3 scripts/configure.py --database opensearch
python3 scripts/configure.py --database clickhouse
```

Database families are cataloged in `config/databases.catalog.yaml` and are intentionally provider-neutral. For non-PostgreSQL engines, choose one of:

1. Operator-backed HA inside Kubernetes.
2. Managed cloud/on-prem database service.
3. External database endpoint stored in Kubernetes Secret.
4. Raw profile for legacy systems.

Do not assume a container replica count alone creates database HA. Use a proper operator, replication topology, or managed service.

## Import Automation Levels

| Engine family | Import detection | Target map | Automated dump/restore |
|---|---:|---:|---:|
| PostgreSQL, PostGIS, TimescaleDB | Yes | Yes | Yes, through `pg_dump` and `pg_restore` |
| MySQL, MariaDB | Yes | Yes | Scaffolded until the operator/managed target profile is declared |
| Microsoft SQL Server | Yes | Yes | Scaffolded until `sqlpackage`/`bcp` runner settings are declared |
| MongoDB | Yes | Yes | Scaffolded until `mongodump`/`mongorestore` runner settings are declared |
| SQLite | File-reference detection | Yes | Scaffolded for dev/single-pod or externalization paths |

The importer should not silently invent production database topology. Optional engines are recognized and written into the private database target map so the next implementation step can wire the exact operator, managed endpoint, or external service without exposing names, IPs, or credentials in public output.
