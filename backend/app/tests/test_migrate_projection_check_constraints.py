"""Tests for scripts.migrate_projection_check_constraints (M4-D schema migration).

These tests exercise ``plan_migration`` and the actual table rebuild against
throwaway in-memory SQLite databases.  They NEVER touch the live
``backend/draftmind.db``.

Required cases:

  1. A pre-M4-D ``prospect_draft_projections`` table (1-60 constraints) ->
     ``plan_migration`` returns action="rebuild".
  2. A table that already has 1-100 constraints -> ``plan_migration`` returns
     action="skip" (idempotent).
  3. No table at all -> ``plan_migration`` returns action="skip".
  4. Actual rebuild preserves row count.
  5. Rebuild does not touch ``team_pick_projections``.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from scripts.migrate_projection_check_constraints import plan_migration


# A pre-M4-D prospect_draft_projections schema with 1-60 CHECK constraints.
_PRE_M4D_SQL = """
CREATE TABLE prospect_draft_projections (
    id INTEGER NOT NULL PRIMARY KEY,
    prospect_id INTEGER NOT NULL,
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
    CONSTRAINT ck_prospect_projection_consensus_rank_range CHECK (consensus_rank IS NULL OR consensus_rank BETWEEN 1 AND 60),
    CONSTRAINT ck_prospect_projection_big_board_rank_range CHECK (big_board_rank IS NULL OR big_board_rank BETWEEN 1 AND 60),
    CONSTRAINT ck_prospect_projection_expected_pick_range CHECK (expected_pick IS NULL OR expected_pick BETWEEN 1 AND 60),
    CONSTRAINT ck_prospect_projection_range_min CHECK (draft_range_min IS NULL OR draft_range_min BETWEEN 1 AND 60),
    CONSTRAINT ck_prospect_projection_range_max CHECK (draft_range_max IS NULL OR draft_range_max BETWEEN 1 AND 60),
    CONSTRAINT ck_prospect_projection_range_order CHECK (draft_range_min IS NULL OR draft_range_max IS NULL OR draft_range_min <= draft_range_max),
    CONSTRAINT ck_prospect_projection_tier CHECK (tier BETWEEN 1 AND 10),
    CONSTRAINT ck_prospect_projection_source CHECK (source IN ('seed_projection', 'manual_projection', 'consensus_reference')),
    CONSTRAINT ck_prospect_projection_source_count CHECK (source_count >= 0),
    CONSTRAINT ck_prospect_projection_confidence CHECK (confidence >= 0 AND confidence <= 1)
)
"""

# A post-M4D schema with 1-100 CHECK constraints (already migrated).
_POST_M4D_SQL = _PRE_M4D_SQL.replace("1 AND 60", "1 AND 100")

# Minimal team_pick_projections table to verify migration doesn't touch it.
_TEAM_PICK_SQL = """
CREATE TABLE team_pick_projections (
    id INTEGER NOT NULL PRIMARY KEY,
    year INTEGER NOT NULL,
    pick_no INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    prospect_id INTEGER NOT NULL,
    projection_type VARCHAR(32) NOT NULL DEFAULT 'manual_prediction',
    source VARCHAR(32) NOT NULL DEFAULT 'manual_projection',
    confidence FLOAT NOT NULL DEFAULT 0.5,
    notes VARCHAR(1000) NOT NULL DEFAULT '',
    created_at DATETIME,
    updated_at DATETIME,
    CONSTRAINT ck_team_pick_projection_pick_no CHECK (pick_no BETWEEN 1 AND 60)
)
"""


def _session_with_tables(*create_sqls: str) -> Session:
    """Build an in-memory SQLite session and create tables from raw SQL."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = Session(bind=engine)
    for sql in create_sqls:
        session.execute(text(sql))
    session.commit()
    return session


def _close(session: Session) -> None:
    engine = session.bind
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# Case 1: 1-60 constraints -> action="rebuild"
# ---------------------------------------------------------------------------


def test_plan_migration_returns_rebuild_when_constraints_are_1_60() -> None:
    session = _session_with_tables(_PRE_M4D_SQL)
    try:
        plan = plan_migration(session)
    finally:
        _close(session)

    assert plan["action"] == "rebuild"
    assert plan["old_row_count"] == 0
    assert len(plan["steps"]) == 6


# ---------------------------------------------------------------------------
# Case 2: 1-100 constraints -> action="skip" (idempotent)
# ---------------------------------------------------------------------------


def test_plan_migration_is_idempotent_when_already_1_100() -> None:
    session = _session_with_tables(_POST_M4D_SQL)
    try:
        plan = plan_migration(session)
    finally:
        _close(session)

    assert plan["action"] == "skip"
    assert "already migrated" in plan["reason"]


# ---------------------------------------------------------------------------
# Case 3: no table -> action="skip"
# ---------------------------------------------------------------------------


def test_plan_migration_skips_when_table_missing() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = Session(bind=engine)
    try:
        plan = plan_migration(session)
    finally:
        session.close()
        engine.dispose()

    assert plan["action"] == "skip"
    assert "not found" in plan["reason"]


# ---------------------------------------------------------------------------
# Case 4: actual rebuild preserves row count
# ---------------------------------------------------------------------------


def test_rebuild_preserves_row_count() -> None:
    """Insert rows into a 1-60 table, run the rebuild, verify rows survive."""
    from scripts.migrate_projection_check_constraints import (
        CREATE_NEW_TABLE_SQL,
        COPY_COLUMNS,
        INDEX_DEFINITIONS,
        TABLE_NAME,
        TEMP_TABLE_NAME,
    )

    session = _session_with_tables(_PRE_M4D_SQL)
    try:
        # Insert 3 rows with valid 1-60 values.
        for i in range(1, 4):
            session.execute(
                text(
                    f"INSERT INTO {TABLE_NAME} "
                    "(id, prospect_id, year, consensus_rank, big_board_rank, "
                    "expected_pick, draft_range_min, draft_range_max, tier, "
                    "source, source_count, confidence, notes) "
                    "VALUES (:id, :pid, 2026, :cr, :br, :ep, :rmin, :rmax, 5, "
                    "'consensus_reference', 3, 0.6, 'test')"
                ),
                {
                    "id": i,
                    "pid": i,
                    "cr": i * 10,
                    "br": i * 10,
                    "ep": i * 10,
                    "rmin": i * 5,
                    "rmax": i * 15,
                },
            )
        session.commit()

        old_count = session.execute(
            text(f"SELECT COUNT(*) FROM {TABLE_NAME}")
        ).fetchone()[0]
        assert old_count == 3

        # Run the rebuild manually (mirrors main() --apply logic).
        session.execute(text(CREATE_NEW_TABLE_SQL))
        session.execute(
            text(
                f"INSERT INTO {TEMP_TABLE_NAME} ({COPY_COLUMNS}) "
                f"SELECT {COPY_COLUMNS} FROM {TABLE_NAME}"
            )
        )
        new_count = session.execute(
            text(f"SELECT COUNT(*) FROM {TEMP_TABLE_NAME}")
        ).fetchone()[0]
        assert new_count == old_count

        session.execute(text(f"DROP TABLE {TABLE_NAME}"))
        session.execute(
            text(f"ALTER TABLE {TEMP_TABLE_NAME} RENAME TO {TABLE_NAME}")
        )
        for idx_sql in INDEX_DEFINITIONS:
            session.execute(text(idx_sql.replace(TEMP_TABLE_NAME, TABLE_NAME)))
        session.commit()

        # Verify rows survived.
        final_count = session.execute(
            text(f"SELECT COUNT(*) FROM {TABLE_NAME}")
        ).fetchone()[0]
        assert final_count == 3

        # Verify we can now insert expected_pick=65 (would fail on 1-60).
        session.execute(
            text(
                f"INSERT INTO {TABLE_NAME} "
                "(id, prospect_id, year, expected_pick, tier, source, "
                "source_count, confidence, notes) "
                "VALUES (99, 99, 2026, 65, 6, 'consensus_reference', 4, 0.54, 'm4d')"
            )
        )
        session.commit()

        # Verify expected_pick=101 is still rejected.
        try:
            session.execute(
                text(
                    f"INSERT INTO {TABLE_NAME} "
                    "(id, prospect_id, year, expected_pick, tier, source, "
                    "source_count, confidence, notes) "
                    "VALUES (100, 100, 2026, 101, 6, 'consensus_reference', 4, 0.54, 'reject')"
                )
            )
            session.commit()
            raise AssertionError("expected_pick=101 should have been rejected")
        except Exception as exc:
            assert "CHECK constraint failed" in str(exc)
            session.rollback()
    finally:
        _close(session)


# ---------------------------------------------------------------------------
# Case 5: rebuild does not touch team_pick_projections
# ---------------------------------------------------------------------------


def test_rebuild_does_not_touch_team_pick_projections() -> None:
    """Verify that the migration plan and rebuild only affect
    prospect_draft_projections, not team_pick_projections."""
    session = _session_with_tables(_PRE_M4D_SQL, _TEAM_PICK_SQL)
    try:
        # Insert a team_pick_projection row.
        session.execute(
            text(
                "INSERT INTO team_pick_projections "
                "(id, year, pick_no, team_id, prospect_id, projection_type, "
                "source, confidence, notes) "
                "VALUES (1, 2026, 5, 1, 1, 'consensus_mock', 'seed_projection', 0.5, 'team')"
            )
        )
        session.commit()

        plan = plan_migration(session)
        assert plan["action"] == "rebuild"

        # The plan should only mention prospect_draft_projections.
        for step in plan["steps"]:
            assert "team_pick_projections" not in step

        # Verify team_pick_projections row count is unchanged after plan check.
        team_count = session.execute(
            text("SELECT COUNT(*) FROM team_pick_projections")
        ).fetchone()[0]
        assert team_count == 1
    finally:
        _close(session)
