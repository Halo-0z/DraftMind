"""Tests for the ManualNoteRecord DB model (RAG-v1-B2)."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ManualNoteRecord, Prospect, Team


def _make_record(**overrides) -> ManualNoteRecord:
    defaults = {
        "year": 2026,
        "entity_type": "prospect",
        "entity_id": "101",
        "title": "Workout observation",
        "body": "The player showed advanced passing feel in transition.",
        "summary": "Passing feel note.",
        "author": "Analyst Name",
        "source_url": "https://example.test/note/101",
        "source_date": "2026-06-16",
        "confidence": 0.8,
        "tags": "passing,transition",
        "relevance_reason": "Explains a selected player's creation upside.",
    }
    defaults.update(overrides)
    return ManualNoteRecord(**defaults)


def test_manual_note_record_can_be_created_and_persisted(db_session: Session) -> None:
    record = _make_record()
    db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(id=record.id).one()

    assert loaded.year == 2026
    assert loaded.entity_type == "prospect"
    assert loaded.entity_id == "101"
    assert loaded.title == "Workout observation"
    assert loaded.body == "The player showed advanced passing feel in transition."
    assert loaded.summary == "Passing feel note."
    assert loaded.author == "Analyst Name"
    assert loaded.source_url == "https://example.test/note/101"
    assert loaded.source_date == "2026-06-16"
    assert loaded.confidence == 0.8
    assert loaded.tags == "passing,transition"
    assert loaded.relevance_reason == "Explains a selected player's creation upside."


def test_manual_note_record_default_source_is_manual(db_session: Session) -> None:
    record = _make_record()
    db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(id=record.id).one()

    assert loaded.source == "manual"


def test_manual_note_record_default_evidence_only_is_true(db_session: Session) -> None:
    record = _make_record()
    db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(id=record.id).one()

    assert loaded.evidence_only is True


def test_manual_note_record_year_is_indexed(db_session: Session) -> None:
    record = _make_record(year=2025)
    db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(year=2025).one()

    assert loaded.id == record.id


def test_manual_note_record_entity_type_is_indexed(db_session: Session) -> None:
    record = _make_record(entity_type="team")
    db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(entity_type="team").one()

    assert loaded.id == record.id


def test_manual_note_record_prospect_id_can_be_set_and_indexed(
    db_session: Session,
) -> None:
    prospect = db_session.query(Prospect).filter(Prospect.name == "Mikel Brown Jr.").one()
    record = _make_record(prospect_id=prospect.id)
    db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(prospect_id=prospect.id).one()

    assert loaded.title == "Workout observation"


def test_manual_note_record_team_id_can_be_set_and_indexed(
    db_session: Session,
) -> None:
    team = db_session.query(Team).filter(Team.abbr == "SAS").one()
    record = _make_record(team_id=team.id, entity_type="team")
    db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(team_id=team.id).one()

    assert loaded.title == "Workout observation"


def test_manual_note_record_pick_no_can_be_set_and_indexed(
    db_session: Session,
) -> None:
    record = _make_record(pick_no=5, entity_type="pick")
    db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(pick_no=5).one()

    assert loaded.title == "Workout observation"


def test_manual_note_record_prospect_id_team_id_pick_no_are_nullable(
    db_session: Session,
) -> None:
    record = _make_record(prospect_id=None, team_id=None, pick_no=None)
    db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(id=record.id).one()

    assert loaded.prospect_id is None
    assert loaded.team_id is None
    assert loaded.pick_no is None


def test_manual_note_record_title_is_required(db_session: Session) -> None:
    record = _make_record(title=None)
    db_session.add(record)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_manual_note_record_body_is_required(db_session: Session) -> None:
    record = _make_record(body=None)
    db_session.add(record)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_manual_note_record_confidence_can_store_zero_to_one(
    db_session: Session,
) -> None:
    for value in [0.0, 0.5, 1.0]:
        record = _make_record(confidence=value, title=f"Note {value}")
        db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).order_by(ManualNoteRecord.id).all()
    assert loaded[-3].confidence == 0.0
    assert loaded[-2].confidence == 0.5
    assert loaded[-1].confidence == 1.0


def test_manual_note_record_confidence_can_be_null(db_session: Session) -> None:
    record = _make_record(confidence=None)
    db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(id=record.id).one()

    assert loaded.confidence is None


def test_manual_note_record_source_url_source_date_relevance_reason_are_nullable(
    db_session: Session,
) -> None:
    record = _make_record(
        source_url=None,
        source_date=None,
        relevance_reason=None,
    )
    db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(id=record.id).one()

    assert loaded.source_url is None
    assert loaded.source_date is None
    assert loaded.relevance_reason is None


def test_manual_note_record_tags_can_be_saved_and_read(db_session: Session) -> None:
    record = _make_record(tags="passing,transition,defense")
    db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(id=record.id).one()

    assert loaded.tags == "passing,transition,defense"


def test_manual_note_record_tags_default_is_empty_string(db_session: Session) -> None:
    record = ManualNoteRecord(
        year=2026,
        entity_type="prospect",
        title="Title",
        body="Body",
    )
    db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(id=record.id).one()

    assert loaded.tags == ""


def test_manual_note_record_created_at_is_set_on_insert(db_session: Session) -> None:
    record = _make_record()
    db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(id=record.id).one()

    assert isinstance(loaded.created_at, datetime)


def test_manual_note_record_updated_at_is_set_on_insert(db_session: Session) -> None:
    record = _make_record()
    db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(id=record.id).one()

    assert isinstance(loaded.updated_at, datetime)


def test_manual_note_record_updated_at_changes_on_update(db_session: Session) -> None:
    record = _make_record()
    db_session.add(record)
    db_session.commit()

    original_updated_at = record.updated_at

    record.title = "Updated title"
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(id=record.id).one()

    assert loaded.title == "Updated title"
    assert loaded.updated_at >= original_updated_at


def test_manual_note_record_entity_id_supports_string(db_session: Session) -> None:
    record = _make_record(entity_id="LAL", entity_type="team")
    db_session.add(record)
    db_session.commit()

    loaded = db_session.query(ManualNoteRecord).filter_by(entity_id="LAL").one()

    assert loaded.entity_id == "LAL"


def test_manual_note_record_can_be_filtered_by_year_and_entity_type(
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            _make_record(year=2025, entity_type="prospect", title="Note 2025"),
            _make_record(year=2026, entity_type="team", title="Note 2026 team"),
            _make_record(year=2026, entity_type="prospect", title="Note 2026 prospect"),
        ]
    )
    db_session.commit()

    prospect_2026 = (
        db_session.query(ManualNoteRecord)
        .filter_by(year=2026, entity_type="prospect")
        .all()
    )
    assert len(prospect_2026) == 1
    assert prospect_2026[0].title == "Note 2026 prospect"
