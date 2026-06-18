"""Tests for the dev-only ManualNote seed script (RAG-v1-D1-E2)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ManualNoteRecord, Prospect, Team
from app.services.manual_note_retrieval_service import (
    retrieve_manual_note_documents,
)
from scripts.seed_manual_notes import SEED_SOURCE, SEED_YEAR, seed_manual_notes


def _count_seed_notes(db_session: Session) -> int:
    return (
        db_session.query(ManualNoteRecord)
        .filter(ManualNoteRecord.source == SEED_SOURCE)
        .count()
    )


def test_seed_creates_demo_manual_note_records(db_session: Session) -> None:
    result = seed_manual_notes(db_session)

    assert result["created_count"] > 0
    assert result["total_seed_notes"] == result["created_count"]
    assert _count_seed_notes(db_session) == result["created_count"]


def test_seed_repeat_run_does_not_duplicate(db_session: Session) -> None:
    first = seed_manual_notes(db_session)
    second = seed_manual_notes(db_session)

    assert first["created_count"] > 0
    assert second["created_count"] == 0
    assert second["skipped_count"] == first["created_count"]
    assert second["total_seed_notes"] == first["total_seed_notes"]
    assert _count_seed_notes(db_session) == first["created_count"]


def test_seed_does_not_delete_custom_notes(db_session: Session) -> None:
    """Pre-existing custom (non-manual_seed) notes must survive the seed."""
    custom = ManualNoteRecord(
        year=SEED_YEAR,
        entity_type="prospect",
        entity_id="custom_1",
        prospect_id=None,
        team_id=None,
        pick_no=None,
        title="Custom analyst note",
        body="This is a custom note that must not be deleted.",
        summary="Custom note.",
        source="manual",
        author="analyst",
        source_url=None,
        source_date="2026-06-01",
        confidence=0.9,
        tags="custom",
        relevance_reason="Custom relevance.",
        evidence_only=True,
    )
    db_session.add(custom)
    db_session.commit()

    seed_manual_notes(db_session)

    custom_still_exists = (
        db_session.query(ManualNoteRecord)
        .filter(ManualNoteRecord.source == "manual")
        .filter(ManualNoteRecord.title == "Custom analyst note")
        .first()
    )
    assert custom_still_exists is not None
    assert custom_still_exists.body == "This is a custom note that must not be deleted."


def test_seed_does_not_overwrite_custom_notes(db_session: Session) -> None:
    """Custom notes with the same title must not be overwritten by seed."""
    mikel = db_session.query(Prospect).filter(Prospect.name == "Mikel Brown Jr.").first()
    assert mikel is not None

    custom = ManualNoteRecord(
        year=SEED_YEAR,
        entity_type="prospect",
        entity_id=str(mikel.id),
        prospect_id=mikel.id,
        team_id=None,
        pick_no=None,
        title="Mikel Brown Jr. — workout passing feel",
        body="CUSTOM BODY THAT MUST NOT BE OVERWRITTEN",
        summary="Custom summary.",
        source="manual",
        author="real_analyst",
        source_url="https://custom.example.test/note",
        source_date="2026-06-01",
        confidence=0.95,
        tags="custom",
        relevance_reason="Custom relevance.",
        evidence_only=True,
    )
    db_session.add(custom)
    db_session.commit()

    result = seed_manual_notes(db_session)

    # The seed should still create its own note (different source), and the
    # custom note must be untouched.
    all_with_title = (
        db_session.query(ManualNoteRecord)
        .filter(ManualNoteRecord.title == "Mikel Brown Jr. — workout passing feel")
        .all()
    )
    sources = {row.source for row in all_with_title}
    assert "manual" in sources
    assert SEED_SOURCE in sources

    custom_row = next(row for row in all_with_title if row.source == "manual")
    assert custom_row.body == "CUSTOM BODY THAT MUST NOT BE OVERWRITTEN"
    assert custom_row.author == "real_analyst"


def test_all_seed_notes_have_evidence_only_true(db_session: Session) -> None:
    seed_manual_notes(db_session)

    seed_rows = (
        db_session.query(ManualNoteRecord)
        .filter(ManualNoteRecord.source == SEED_SOURCE)
        .all()
    )
    assert len(seed_rows) > 0
    for row in seed_rows:
        assert row.evidence_only is True


def test_all_seed_notes_have_correct_source(db_session: Session) -> None:
    seed_manual_notes(db_session)

    seed_rows = (
        db_session.query(ManualNoteRecord)
        .filter(ManualNoteRecord.source == SEED_SOURCE)
        .all()
    )
    assert len(seed_rows) > 0
    for row in seed_rows:
        assert row.source == SEED_SOURCE


def test_seed_notes_retrievable_by_retrieve_manual_note_documents(
    db_session: Session,
) -> None:
    """Seed notes must be discoverable by the retrieval service."""
    seed_manual_notes(db_session)

    mikel = db_session.query(Prospect).filter(Prospect.name == "Mikel Brown Jr.").first()
    assert mikel is not None

    documents = retrieve_manual_note_documents(
        db_session, year=SEED_YEAR, limit=50, prospect_id=mikel.id
    )

    assert len(documents) > 0
    assert all(doc.source_type == "manual_note" for doc in documents)
    # The 2025 legacy note must NOT appear (year filter).
    assert all(doc.year == SEED_YEAR for doc in documents)


def test_seed_covers_prospect_team_pick_entity_types(db_session: Session) -> None:
    seed_manual_notes(db_session)

    entity_types = {
        row.entity_type
        for row in db_session.query(ManualNoteRecord)
        .filter(ManualNoteRecord.source == SEED_SOURCE)
        .filter(ManualNoteRecord.year == SEED_YEAR)
        .all()
    }
    assert "prospect" in entity_types
    assert "team" in entity_types
    assert "pick" in entity_types


def test_seed_includes_year_filter_note(db_session: Session) -> None:
    """A 2025 note exists to verify year filtering excludes it."""
    seed_manual_notes(db_session)

    legacy_notes = (
        db_session.query(ManualNoteRecord)
        .filter(ManualNoteRecord.source == SEED_SOURCE)
        .filter(ManualNoteRecord.year == 2025)
        .all()
    )
    assert len(legacy_notes) >= 1

    # Retrieval with year=2026 must NOT return the 2025 note.
    documents = retrieve_manual_note_documents(db_session, year=SEED_YEAR, limit=50)
    legacy_titles = {doc.title for doc in documents}
    assert "Mikel Brown Jr. — 2025 legacy note" not in legacy_titles


def test_seed_graceful_skip_when_demo_prospect_missing(db_session: Session) -> None:
    """When demo prospects are missing, the script must not crash."""
    # Delete prospects to simulate missing demo data.
    db_session.query(Prospect).delete()
    db_session.commit()

    result = seed_manual_notes(db_session)

    # Should still create the pick-only note (no prospect/team dependency).
    assert result["created_count"] >= 1
    # Should not crash.
    assert result["total_seed_notes"] >= 1


def test_seed_graceful_skip_when_demo_team_missing(db_session: Session) -> None:
    """When demo teams are missing, the script must not crash."""
    # Delete teams (and prospects with FK references first).
    db_session.query(ManualNoteRecord).delete()
    db_session.query(Prospect).delete()
    db_session.query(Team).delete()
    db_session.commit()

    result = seed_manual_notes(db_session)

    # Should still create the pick-only note.
    assert result["created_count"] >= 1
    assert result["total_seed_notes"] >= 1


def test_seed_does_not_touch_ranking_systems(db_session: Session) -> None:
    """Seed must only write ManualNoteRecord, nothing else."""
    from app.models import DraftOrder, Roster, TeamNeed

    # Snapshot counts before seed.
    before = {
        "teams": db_session.query(Team).count(),
        "prospects": db_session.query(Prospect).count(),
        "draft_orders": db_session.query(DraftOrder).count(),
        "rosters": db_session.query(Roster).count(),
        "team_needs": db_session.query(TeamNeed).count(),
    }

    seed_manual_notes(db_session)

    after = {
        "teams": db_session.query(Team).count(),
        "prospects": db_session.query(Prospect).count(),
        "draft_orders": db_session.query(DraftOrder).count(),
        "rosters": db_session.query(Roster).count(),
        "team_needs": db_session.query(TeamNeed).count(),
    }

    assert before == after, (
        f"Seed modified ranking/system tables: before={before} after={after}"
    )
