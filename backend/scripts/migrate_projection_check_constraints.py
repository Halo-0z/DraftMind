"""M4-D schema migration: widen ProspectDraftProjection CHECK constraints 60→100.

Why this exists
---------------
``Base.metadata.create_all`` only creates tables that are MISSING -- it never
alters CHECK constraints on an existing table.  The live
``backend/draftmind.db`` was created when ProspectDraftProjection limited
consensus_rank / big_board_rank / expected_pick / draft_range_min /
draft_range_max to 1-60.  M4-D widened these to 1-100 to support second-round
/ UDFA-bubble market board projections, but the existing SQLite table still
carries the old 1-60 CHECK constraints.

SQLite does not support ``ALTER TABLE ... DROP CONSTRAINT``, so the only way
to change a CHECK constraint is the official "table rebuild" procedure:

1. CREATE new table with relaxed CHECK constraints
2. INSERT all rows from old table
3. Verify row count matches
4. DROP old table
5. RENAME new table to original name
6. Recreate indexes

This script is DRY-RUN by default.  Pass ``--apply`` to actually execute the
rebuild.  It NEVER touches row data -- it only rebuilds the table schema.
It ONLY touches ``prospect_draft_projections``; ``team_pick_projections`` is
not modified (its ``pick_no`` 1-60 constraint stays, because the NBA draft
only has 60 picks).

Semantic note (M4-D):
  ``expected_pick > 60`` represents a market board slot / outside-draft or
  UDFA-bubble projection.  It does NOT mean the NBA has a 65th or 84th pick.
  These values are used for eval / calibration awareness only.  The
  calibration top market prior gate remains controlled by
  ``expected_pick <= 8`` (MARKET_PRIOR_MAX_EXPECTED_PICK), so late-board
  projections do not inflate first-round selection.

Usage::

    cd D:\\DraftMind\\backend
    # Dry run (default) -- prints what it would do:
    D:\\anaconda\\python.exe scripts\\migrate_projection_check_constraints.py
    # Actually apply:
    D:\\anaconda\\python.exe scripts\\migrate_projection_check_constraints.py --apply
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


TABLE_NAME = "prospect_draft_projections"
TEMP_TABLE_NAME = "prospect_draft_projections_m4d_new"

# The new CREATE TABLE statement with widened CHECK constraints (1-100).
# This mirrors the SQLAlchemy model in app/models/projection.py exactly,
# except the CHECK constraints use 1-100 instead of 1-60.
CREATE_NEW_TABLE_SQL = f"""
CREATE TABLE {TEMP_TABLE_NAME} (
    id INTEGER NOT NULL PRIMARY KEY,
    prospect_id INTEGER NOT NULL REFERENCES prospects(id),
    year INTEGER NOT NULL,
    consensus_rank INTEGER,
    big_board_rank INTEGER,
    expected_pick INTEGER,
    draft_range_min INTEGER,
    draft_range_max INTEGER,
    tier INTEGER NOT NULL DEFAULT 5,
    source VARCHAR(32) NOT NULL DEFAULT 'manual_projection',
    source_count INTEGER NOT NULL DEFAULT 1,
    confidence FLOAT NOT NULL DEFAULT 0.5,
    last_updated DATETIME,
    notes VARCHAR(1000) NOT NULL DEFAULT '',
    created_at DATETIME,
    updated_at DATETIME,
    CONSTRAINT uq_prospect_projection_prospect_year_source UNIQUE (prospect_id, year, source),
    CONSTRAINT ck_prospect_projection_consensus_rank_range CHECK (consensus_rank IS NULL OR consensus_rank BETWEEN 1 AND 100),
    CONSTRAINT ck_prospect_projection_big_board_rank_range CHECK (big_board_rank IS NULL OR big_board_rank BETWEEN 1 AND 100),
    CONSTRAINT ck_prospect_projection_expected_pick_range CHECK (expected_pick IS NULL OR expected_pick BETWEEN 1 AND 100),
    CONSTRAINT ck_prospect_projection_range_min CHECK (draft_range_min IS NULL OR draft_range_min BETWEEN 1 AND 100),
    CONSTRAINT ck_prospect_projection_range_max CHECK (draft_range_max IS NULL OR draft_range_max BETWEEN 1 AND 100),
    CONSTRAINT ck_prospect_projection_range_order CHECK (draft_range_min IS NULL OR draft_range_max IS NULL OR draft_range_min <= draft_range_max),
    CONSTRAINT ck_prospect_projection_tier CHECK (tier BETWEEN 1 AND 10),
    CONSTRAINT ck_prospect_projection_source CHECK (source IN ('seed_projection', 'manual_projection', 'consensus_reference')),
    CONSTRAINT ck_prospect_projection_source_count CHECK (source_count >= 0),
    CONSTRAINT ck_prospect_projection_confidence CHECK (confidence >= 0 AND confidence <= 1)
)
"""

# Columns to copy (order must match between old and new table).
COPY_COLUMNS = (
    "id, prospect_id, year, consensus_rank, big_board_rank, expected_pick, "
    "draft_range_min, draft_range_max, tier, source, source_count, confidence, "
    "last_updated, notes, created_at, updated_at"
)

INDEX_DEFINITIONS = [
    # Recreate the indexes that the ORM model defines.
    f"CREATE INDEX ix_{TEMP_TABLE_NAME}_prospect_id ON {TEMP_TABLE_NAME} (prospect_id)",
    f"CREATE INDEX ix_{TEMP_TABLE_NAME}_year ON {TEMP_TABLE_NAME} (year)",
]


def _table_exists(db, table_name: str) -> bool:
    result = db.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name},
    )
    return result.fetchone() is not None


def _table_row_count(db, table_name: str) -> int:
    result = db.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
    return result.fetchone()[0]


def _get_table_sql(db, table_name: str) -> str | None:
    result = db.execute(
        text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name},
    )
    row = result.fetchone()
    return row[0] if row else None


def _already_migrated(db) -> bool:
    """Check if the table already has 1-100 constraints (idempotency check)."""
    sql = _get_table_sql(db, TABLE_NAME)
    if sql is None:
        return False
    # If the table SQL contains "1 AND 100" for the projection fields, it's
    # already migrated.  We check for "1 AND 100" rather than "1 AND 60" to
    # detect the migrated state.
    return "1 AND 100" in sql and "1 AND 60" not in sql


def plan_migration(db) -> dict:
    """Return a plan dict describing what the migration will do."""
    if not _table_exists(db, TABLE_NAME):
        return {"action": "skip", "reason": f"{TABLE_NAME} table not found"}

    if _already_migrated(db):
        return {"action": "skip", "reason": "already migrated to 1-100"}

    old_count = _table_row_count(db, TABLE_NAME)
    return {
        "action": "rebuild",
        "old_row_count": old_count,
        "steps": [
            f"CREATE TABLE {TEMP_TABLE_NAME} (with 1-100 CHECK constraints)",
            f"INSERT INTO {TEMP_TABLE_NAME} ({COPY_COLUMNS}) SELECT {COPY_COLUMNS} FROM {TABLE_NAME}",
            f"VERIFY row count: expected={old_count}",
            f"DROP TABLE {TABLE_NAME}",
            f"ALTER TABLE {TEMP_TABLE_NAME} RENAME TO {TABLE_NAME}",
            "RECREATE indexes (prospect_id, year)",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually run the table rebuild (default is dry-run)",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        plan = plan_migration(db)

        if plan["action"] == "skip":
            print(f"SKIP: {plan['reason']}")
            return

        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"=== migrate_projection_check_constraints ({mode}) ===")
        print(f"Table: {TABLE_NAME}")
        print(f"Current row count: {plan['old_row_count']}")
        print()
        print("Planned steps:")
        for i, step in enumerate(plan["steps"], 1):
            print(f"  {i}. {step}")

        if not args.apply:
            print("\nDRY-RUN: 0 changes applied. Re-run with --apply to execute.")
            return

        # --- APPLY mode: execute the table rebuild ---
        old_count = plan["old_row_count"]

        # Step 1: Create new table with relaxed constraints
        db.execute(text(CREATE_NEW_TABLE_SQL))
        print(f"  [1/6] Created {TEMP_TABLE_NAME}")

        # Step 2: Copy all rows
        db.execute(
            text(
                f"INSERT INTO {TEMP_TABLE_NAME} ({COPY_COLUMNS}) "
                f"SELECT {COPY_COLUMNS} FROM {TABLE_NAME}"
            )
        )
        print(f"  [2/6] Copied rows from {TABLE_NAME}")

        # Step 3: Verify row count
        new_count = _table_row_count(db, TEMP_TABLE_NAME)
        if new_count != old_count:
            db.rollback()
            print(
                f"  ERROR: row count mismatch! old={old_count} new={new_count}. "
                f"Rolled back."
            )
            return
        print(f"  [3/6] Verified row count: {new_count} (matches)")

        # Step 4: Drop old table
        db.execute(text(f"DROP TABLE {TABLE_NAME}"))
        print(f"  [4/6] Dropped old {TABLE_NAME}")

        # Step 5: Rename new table
        db.execute(
            text(
                f"ALTER TABLE {TEMP_TABLE_NAME} RENAME TO {TABLE_NAME}"
            )
        )
        print(f"  [5/6] Renamed {TEMP_TABLE_NAME} -> {TABLE_NAME}")

        # Step 6: Recreate indexes
        for idx_sql in INDEX_DEFINITIONS:
            # Fix index names to use the final table name
            idx_sql_final = idx_sql.replace(TEMP_TABLE_NAME, TABLE_NAME)
            db.execute(text(idx_sql_final))
        print(f"  [6/6] Recreated indexes on {TABLE_NAME}")

        db.commit()
        print(f"\nAPPLY: {TABLE_NAME} rebuilt with 1-100 CHECK constraints.")
        print(f"  Rows preserved: {old_count} -> {new_count}")


if __name__ == "__main__":
    main()
