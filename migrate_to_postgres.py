#!/usr/bin/env python3
"""One-time migration: copy the existing SQLite database to PostgreSQL.

Reads from the local SQLite file (data/italian_test.db) and writes to the
PostgreSQL server configured via DB_* environment variables in `.env`.

Usage:
    source .venv/bin/activate
    python migrate_to_postgres.py

This script is idempotent: it skips rows whose primary key already exists in
the target database, so re-running it is safe.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

from app.config import DB_HOST, DB_NAME, DB_PORT, DB_PASSWORD, DB_USER
from app.database import SCHEMA, get_connection

BASE_DIR = Path(__file__).resolve().parent
SQLITE_PATH = BASE_DIR / "data" / "italian_test.db"

TABLES = [
    "users",
    "sessions",
    "vocabulary",
    "attempts",
    "ai_exercises",
    "sim_exercises",
]


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.commit()


def fetch_sqlite_rows(sqlite_conn, table: str) -> list[tuple]:
    cur = sqlite_conn.execute(f'SELECT * FROM "{table}"')
    rows = cur.fetchall()
    cur.close()
    return rows


def table_columns(pg_conn, table: str) -> list[str]:
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s ORDER BY ordinal_position",
            (table,),
        )
        return [r[0] for r in cur.fetchall()]


def existing_ids(pg_conn, table: str) -> set[int]:
    with pg_conn.cursor() as cur:
        cur.execute(f'SELECT id FROM "{table}"')
        return {int(r[0]) for r in cur.fetchall()}


def migrate_table(pg_conn, sqlite_conn, table: str) -> int:
    rows = fetch_sqlite_rows(sqlite_conn, table)
    if not rows:
        print(f"  {table}: 0 rows (nothing to copy)")
        return 0

    cols = table_columns(pg_conn, table)
    ids = existing_ids(pg_conn, table)
    placeholders = ", ".join(["%s"] * len(cols))
    col_sql = ", ".join(f'"{c}"' for c in cols)

    inserted = 0
    skipped = 0
    with pg_conn.cursor() as cur:
        for row in rows:
            row_id = int(row[0])
            if row_id in ids:
                skipped += 1
                continue
            cur.execute(
                f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})',
                row,
            )
            inserted += 1
    pg_conn.commit()
    print(f"  {table}: {len(rows)} rows → {inserted} inserted, {skipped} skipped (already present)")
    return inserted


def main() -> None:
    if not DB_HOST or not DB_USER:
        print("ERROR: DB_HOST / DB_USER not set. Copy .env.example to .env and fill them in.")
        sys.exit(1)

    if not SQLITE_PATH.exists():
        print(f"ERROR: SQLite database not found at {SQLITE_PATH}")
        sys.exit(1)

    sqlite_conn = sqlite3.connect(str(SQLITE_PATH))
    pg_conn = get_connection()

    print("Ensuring PostgreSQL schema…")
    ensure_schema(pg_conn)

    print("Copying data:")
    for table in TABLES:
        try:
            migrate_table(pg_conn, sqlite_conn, table)
        except psycopg2.Error as exc:
            print(f"  {table}: FAILED — {exc}")
            pg_conn.rollback()

    sqlite_conn.close()
    pg_conn.close()
    print("Done. Verify counts in the new database.")


if __name__ == "__main__":
    main()
