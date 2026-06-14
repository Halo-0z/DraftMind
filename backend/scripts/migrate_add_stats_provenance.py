"""B0-K1 schema migration: add stats_source / stats_confidence to prospects.

Why this exists
---------------
``Base.metadata.create_all`` only creates tables that are MISSING -- it never
adds columns to an existing table.  So the B0-K1 ``stats_source`` /
``stats_confidence`` columns on ``Prospect`` are present in the ORM model and
in every fresh (in-memory) test DB, but the live ``backend/draftmind.db`` was
created before B0-K1 and is missing both columns.  Querying ``Prospect``
against the live DB raises::

    sqlite3.OperationalError: no such column: prospects.stats_source

This script runs the corresponding ``ALTER TABLE ... ADD COLUMN`` statements
idempotently (it checks ``PRAGMA table_info`` first), so it is safe to run
repeatedly.  Both new columns are NULLable and have no default, which keeps
every existing row readable as "unknown" provenance (``stats_source IS NULL``
-> audit reports "unknown", confidence None).

The script is DRY-RUN by default.  Pass ``--apply`` to actually execute the
ALTERs.  It NEVER touches any row data -- it only adds columns.

Usage::

    cd D:\\DraftMind\\backend
    # Dry run (default) -- prints what it would do:
    D:\\anaconda\\python.exe scripts\\migrate_add_stats_provenance.py
    # Actually apply:
    D:\\anaconda\\python.exe scripts\\migrate_add_stats_provenance.py --apply

After running ``--apply``, every existing 2026 prospect reads back with
``stats_source IS NULL`` / ``stats_confidence IS NULL`` (i.e. "unknown"
provenance) until the seed / importer are re-run, which will populate
``seed_manual`` / ``nba_importer_heuristic`` respectively.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal  # noqa: E402


COLUMNS = [
    # (column_name, column_sql_type, description)
    ("stats_source", "VARCHAR(40)", "B0-K1 stats provenance source"),
    ("stats_confidence", "FLOAT", "B0-K1 stats provenance confidence"),
]


def _existing_columns(db) -> set[str]:
    result = db.execute(text("PRAGMA table_info(prospects)"))
    return {row[1] for row in result}


def plan_migration(db) -> list[tuple[str, str]]:
    """Return the list of (column_name, sql) statements that need to run."""
    existing = _existing_columns(db)
    if "prospects" not in {  # table existence check via PRAGMA
        row[0] for row in db.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='prospects'"
        ))
    }:
        raise RuntimeError(
            "prospects table not found -- the DB appears uninitialized."
        )
    todo: list[tuple[str, str]] = []
    for col, col_type, _desc in COLUMNS:
        if col in existing:
            continue
        todo.append(
            (col, f"ALTER TABLE prospects ADD COLUMN {col} {col_type}")
        )
    return todo


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually run the ALTER TABLE statements (default is dry-run)",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        todo = plan_migration(db)
        if not todo:
            print("prospects table already has stats_source / stats_confidence. "
                  "Nothing to do.")
            return

        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"=== migrate_add_stats_provenance ({mode}) ===")
        for col, sql in todo:
            print(f"  {sql}")

        if not args.apply:
            print("\nDRY-RUN: 0 columns added. Re-run with --apply to commit.")
            return

        for col, sql in todo:
            db.execute(text(sql))
        db.commit()
        print(f"\nAPPLY: added {len(todo)} column(s) to prospects.")


if __name__ == "__main__":
    main()
