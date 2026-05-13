# Postgres migrations

Pure SQL. Applied in filename order by `cyberalertx.tools.pg_migrate`.
Idempotent: every `CREATE` uses `IF NOT EXISTS`, plus `schema_migrations`
records applied versions so re-runs are no-ops.

## Apply

```bash
export CYBERALERTX_PG_URL="postgresql://USER:PASS@HOST:5432/DB?sslmode=require"
python -m cyberalertx.tools.pg_migrate
```

## Conventions

- Filename: `NNN_short_name.sql` (zero-padded, ascending).
- Each file is one atomic logical change. Don't bundle unrelated DDL.
- DDL only. Data backfills live in `cyberalertx/tools/`.
- No down-migrations: rollback is forward-only via a new migration that
  reverses the change. Keeps the runner trivial.
