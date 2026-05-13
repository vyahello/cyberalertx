"""PostgreSQL backend.

Shadow-write only in this PR — reads stay on JSON. SQLAlchemy Core 2.0 +
psycopg3. Managed Postgres assumed (Supabase); no Supabase SDK is used.
"""
