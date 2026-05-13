"""Apply pending Postgres migrations.

Usage:
    export CYBERALERTX_PG_URL="postgresql://..."
    python -m cyberalertx.tools.pg_migrate           # apply pending
    python -m cyberalertx.tools.pg_migrate --status  # list applied / pending

Idempotent: every `CREATE` in the migration files uses `IF NOT EXISTS`,
and we record applied versions in `schema_migrations` so a re-run is a
no-op even if the bookkeeping is fresh.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List

from sqlalchemy import text

from ..storage.pg.engine import get_engine

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "storage" / "pg" / "migrations"


def _list_files() -> List[Path]:
    return sorted(p for p in MIGRATIONS_DIR.glob("*.sql") if p.is_file())


def _ensure_bookkeeping() -> set[str]:
    """Make sure schema_migrations exists, return the set of applied versions."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     VARCHAR(64) PRIMARY KEY,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        applied = {row[0] for row in conn.execute(
            text("SELECT version FROM schema_migrations")
        )}
    return applied


def _apply(file: Path) -> None:
    """Apply one migration in a single transaction. Records the version."""
    sql = file.read_text(encoding="utf-8")
    engine = get_engine()
    with engine.begin() as conn:
        # SQLAlchemy's text() executes one statement per call; we use
        # `exec_driver_sql` to let psycopg run the whole script. The
        # script is trusted (we wrote it), so no parameterization concern.
        conn.exec_driver_sql(sql)
        conn.execute(
            text("INSERT INTO schema_migrations (version) VALUES (:v) "
                 "ON CONFLICT (version) DO NOTHING"),
            {"v": file.stem},
        )


def status() -> int:
    files = _list_files()
    applied = _ensure_bookkeeping()
    pending = [f for f in files if f.stem not in applied]
    print(f"Migrations dir : {MIGRATIONS_DIR}")
    print(f"Found          : {len(files)}")
    print(f"Applied        : {len(applied)}")
    print(f"Pending        : {len(pending)}")
    for f in files:
        marker = "✓" if f.stem in applied else " "
        print(f"  [{marker}] {f.name}")
    return 0


def migrate() -> int:
    files = _list_files()
    if not files:
        print(f"No migrations found in {MIGRATIONS_DIR}", file=sys.stderr)
        return 1
    applied = _ensure_bookkeeping()
    pending = [f for f in files if f.stem not in applied]
    if not pending:
        print("No pending migrations.")
        return 0
    for f in pending:
        print(f"Applying {f.name}...")
        try:
            _apply(f)
        except Exception as exc:
            print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print("  done.")
    print(f"Applied {len(pending)} migration(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cyberalertx.tools.pg_migrate",
        description="Apply pending Postgres DDL migrations.",
    )
    parser.add_argument("--status", action="store_true",
                        help="Show applied / pending list and exit.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    return status() if args.status else migrate()


if __name__ == "__main__":
    raise SystemExit(main())
