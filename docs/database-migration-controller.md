# Database Migration Controller

This is the public-safe control plane for database dump, restore, and retry
decisions during project import. It documents the automation without exposing
DSNs, passwords, database names, source service names, private node addresses,
or dump contents.

## One Command Plan

Generate the database migration controller plan before executing the database
stage:

```bash
make database-migration-plan IMPORT_REDACT=true
```

The plan writes `reports/database-migration-plan.md`. It summarizes the selected
profile, private target map status, dump directory, PostgreSQL client image,
enabled Helm database target count, engine support, phase order, and whether
the run is allowed to handle secret material.

## Automatic PostgreSQL-Family Migration

PostgreSQL, PostGIS, and TimescaleDB are automated with logical dump and restore.
The migration stage uses `pg_dump --format=custom --no-owner --no-acl` for the
source and `pg_restore --clean --if-exists --no-owner` for the target. If local
`pg_dump` and `pg_restore` are not installed, the automation uses
`MIGRATION_POSTGRES_CLIENT_IMAGE` through the selected container tool.

Execution still requires an explicit trusted-operator switch:

```bash
make import-migrate PROJECT_PATH=/path/to/compose-project \
  MIGRATION_STAGE=databases \
  MIGRATION_EXECUTE=true \
  MIGRATION_ALLOW_SECRET_MATERIAL=true
```

That switch is intentional because this stage reads source database passwords
and target secret references from the private operator workspace.

## Target Map Contract

The private target map is `/var/lib/urban-platform/private/db-targets.yaml` by
default. `import-auto` initializes it automatically when missing. Restores run
only for PostgreSQL-family sources that have a usable target mapping. Entries
can point at a target service and secret reference or a direct DSN in the
private file.

Optional engines such as MySQL, MariaDB, Microsoft SQL Server, MongoDB, and
SQLite are detected and scaffolded in the target map. Their runners remain
disabled until an operator-backed, managed, or external target profile is
declared.

## Profiles

`config/database-migration.yaml` defines the controller profiles:

- `lab`: allows unreachable sources to be skipped and reported, which is useful
  for rehearsals and partially running Compose projects.
- `production`: requires every source to be reachable before cutover and treats
  missing/unavailable sources as failures.

Use `MIGRATION_SKIP_UNAVAILABLE_DATABASES=false` for production migrations. Keep
database dumps under the private directory and outside Git.

## Validation

After restore, run application smoke tests and database-specific validation:

- source and target PostgreSQL major versions
- installed extension names and versions
- PostGIS availability when geospatial data exists
- TimescaleDB extension availability before hypertable restore
- row-count or application-level consistency checks for critical tables

The controller plan is not a replacement for those checks; it is the public-safe
preflight view that keeps the automatic migration path understandable.
