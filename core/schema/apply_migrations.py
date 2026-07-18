"""Ledger-based delta migration runner for initialized databases.

Fresh database initialization stays with Makefile DB_SQL_FILES and domain
tables.sql files. This module owns only delta application: adopting the
frozen baseline for already-initialized databases and then applying any
checked-in migrations not yet in the ledger.

The frozen baseline contains 2026_07_07_zcta_district.sql, which was
retro-edited after its original production execution to include the
boundary_year column that 2026_07_14_zcta_district_boundary_year.sql
later added via ALTER. Adoption seeds baseline entries into the ledger
without re-executing their SQL, so the retro-edited file is safely
recorded as "already applied" and only the 07_14 reconciliation runs.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from core.db import get_connection

BASELINE_PATH = Path(__file__).resolve().parent / "migrations_baseline.txt"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_FILENAME_RE = re.compile(r"^[A-Za-z0-9_]+\.sql$")
_CONCURRENTLY_RE = re.compile(r"\bCONCURRENTLY\b", re.IGNORECASE)


def _ensure_ledger(conn):
    conn.execute("CREATE SCHEMA IF NOT EXISTS core")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS core.schema_migrations (
            filename    TEXT PRIMARY KEY,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.commit()


def _parse_baseline(baseline_path):
    entries = []
    seen = set()
    for line in baseline_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not _FILENAME_RE.match(stripped):
            raise ValueError(f"Unsafe baseline entry: {stripped}")
        if stripped in seen:
            raise ValueError(f"Duplicate baseline entry: {stripped}")
        seen.add(stripped)
        entries.append(stripped)
    return entries


def _adopt_baseline(conn, baseline_entries, migrations_dir):
    for entry in baseline_entries:
        if not (migrations_dir / entry).is_file():
            raise ValueError(f"Baseline entry has no matching migration file: {entry}")
    with conn.cursor() as cur:
        for entry in baseline_entries:
            cur.execute(
                "INSERT INTO core.schema_migrations (filename) VALUES (%s)",
                (entry,),
            )
    conn.commit()


def _apply_pending(conn, migrations_dir):
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM core.schema_migrations")
        applied = {row[0] for row in cur.fetchall()}

    pending = sorted(f.name for f in migrations_dir.iterdir() if f.suffix == ".sql" and f.name not in applied)

    for filename in pending:
        sql = (migrations_dir / filename).read_text(encoding="utf-8")
        if _CONCURRENTLY_RE.search(sql):
            raise ValueError(f"Migration {filename} contains CONCURRENTLY, which cannot run inside a transaction")
        conn.execute(sql)
        conn.execute(
            "INSERT INTO core.schema_migrations (filename) VALUES (%s)",
            (filename,),
        )
        conn.commit()


def main() -> int:
    try:
        conn = get_connection()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        _ensure_ledger(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM core.schema_migrations")
            ledger_count = cur.fetchone()[0]

        if ledger_count == 0:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('cf.candidate') IS NOT NULL")
                has_sentinel = cur.fetchone()[0]

            if not has_sentinel:
                print(
                    "error: ledger is empty and base schema is not initialized "
                    "(cf.candidate not found). Run the full schema init first.",
                    file=sys.stderr,
                )
                return 1

            baseline_entries = _parse_baseline(BASELINE_PATH)
            _adopt_baseline(conn, baseline_entries, MIGRATIONS_DIR)

        _apply_pending(conn, MIGRATIONS_DIR)
        return 0

    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
