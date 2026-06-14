"""Tests for scripts.migrate_add_stats_provenance (B0-K1 schema migration).

These tests exercise ``plan_migration`` against throwaway in-memory SQLite
databases.  They NEVER touch the live ``backend/draftmind.db`` and NEVER run
``--apply`` -- they only call ``plan_migration(db)`` to inspect the planned
ALTER statements.

The three required cases:

  1. A pre-B0-K1 ``prospects`` table (missing ``stats_source`` /
     ``stats_confidence``) -> ``plan_migration`` returns two ALTERs.
  2. A table that already has both columns -> ``plan_migration`` returns an
     empty list (idempotent).
  3. No ``prospects`` table at all -> ``plan_migration`` raises ``RuntimeError``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from scripts.migrate_add_stats_provenance import plan_migration


# A pre-B0-K1 prospects schema (the columns the live DB has today, before the
# ALTER).  Mirrors the columns Prospect had before B0-K1 added the two
# provenance columns.
_PRE_B0K1_PROSPECTS_SQL = """
CREATE TABLE prospects (
    id INTEGER PRIMARY KEY,
    year INTEGER,
    name VARCHAR(120),
    position VARCHAR(12),
    age FLOAT,
    height VARCHAR(24),
    weight INTEGER,
    school_or_league VARCHAR(120),
    ppg FLOAT,
    rpg FLOAT,
    apg FLOAT,
    fg_pct FLOAT,
    three_pct FLOAT,
    ft_pct FLOAT,
    stocks FLOAT,
    archetype VARCHAR(120),
    upside_score FLOAT,
    risk_score FLOAT
)
"""


def _session_with_prospects(create_sql: str) -> Session:
    """Build an in-memory SQLite session and create the prospects table from
    the given raw SQL.  StaticPool keeps every connection on the same
    in-memory DB so the table we create is visible to plan_migration."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = Session(bind=engine)
    # Create the table via the session's own transaction so the connection
    # lifecycle matches what plan_migration will use later (avoid the
    # ResourceClosedError that a `with session.connection()` context triggers
    # once it exits).
    session.execute(text(create_sql))
    session.commit()
    return session


def _close(session: Session) -> None:
    engine = session.bind
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# Case 1: missing columns -> two ALTERs
# ---------------------------------------------------------------------------


def test_plan_migration_returns_two_alters_when_columns_missing() -> None:
    session = _session_with_prospects(_PRE_B0K1_PROSPECTS_SQL)
    try:
        plan = plan_migration(session)
    finally:
        _close(session)

    assert len(plan) == 2
    planned_cols = {col for col, _sql in plan}
    assert planned_cols == {"stats_source", "stats_confidence"}
    # The generated SQL is an idempotent ALTER TABLE ADD COLUMN.
    for col, sql in plan:
        assert sql.startswith(f"ALTER TABLE prospects ADD COLUMN {col} ")
    # Sanity: types match what the migration script declares.
    sql_by_col = dict(plan)
    assert "VARCHAR(40)" in sql_by_col["stats_source"]
    assert "FLOAT" in sql_by_col["stats_confidence"]


# ---------------------------------------------------------------------------
# Case 2: columns already present -> empty plan (idempotent)
# ---------------------------------------------------------------------------


def test_plan_migration_is_idempotent_when_columns_present() -> None:
    # Same schema as above but with the two B0-K1 columns already added.
    already_migrated_sql = _PRE_B0K1_PROSPECTS_SQL.rstrip().rstrip(")")
    already_migrated_sql += ",\n    stats_source VARCHAR(40),\n    stats_confidence FLOAT\n)"
    session = _session_with_prospects(already_migrated_sql)
    try:
        plan = plan_migration(session)
    finally:
        _close(session)

    assert plan == []


def test_plan_migration_is_idempotent_after_running_alter() -> None:
    """Stronger idempotency check: actually run the planned ALTERs against a
    fresh in-memory DB, then call plan_migration again.  This proves the
    script is safe to re-run after a real --apply."""
    session = _session_with_prospects(_PRE_B0K1_PROSPECTS_SQL)
    try:
        first_plan = plan_migration(session)
        assert len(first_plan) == 2

        # Execute the ALTERs the way main() would under --apply.
        for _col, sql in first_plan:
            session.execute(text(sql))
        session.commit()

        second_plan = plan_migration(session)
        assert second_plan == []
    finally:
        _close(session)


# ---------------------------------------------------------------------------
# Case 3: no prospects table -> RuntimeError
# ---------------------------------------------------------------------------


def test_plan_migration_raises_when_prospects_table_missing() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = Session(bind=engine)
    try:
        # Empty DB -- no prospects table.
        with pytest.raises(RuntimeError, match="prospects table not found"):
            plan_migration(session)
    finally:
        session.close()
        engine.dispose()
