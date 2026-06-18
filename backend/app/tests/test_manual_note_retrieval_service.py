"""Tests for the ManualNote retrieval service (RAG-v1-C1)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.models import ManualNoteRecord, Prospect, Team
from app.schemas.evidence import EvidenceDocumentRead
from app.services.manual_note_retrieval_service import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MIN_LIMIT,
    retrieve_manual_note_documents,
)


def _make_record(db_session: Session, **overrides: Any) -> ManualNoteRecord:
    defaults = {
        "year": 2026,
        "entity_type": "prospect",
        "entity_id": "101",
        "prospect_id": None,
        "team_id": None,
        "pick_no": None,
        "title": "Workout observation",
        "body": "The player showed advanced passing feel in transition.",
        "summary": "Passing feel note.",
        "source": "manual",
        "author": "Analyst Name",
        "source_url": "https://example.test/note/101",
        "source_date": "2026-06-16",
        "confidence": 0.8,
        "tags": "passing,transition",
        "relevance_reason": "Explains a selected player's creation upside.",
        "evidence_only": True,
    }
    defaults.update(overrides)
    record = ManualNoteRecord(**defaults)
    db_session.add(record)
    db_session.commit()
    return record


def test_retrieve_returns_list_of_evidence_document_read(db_session: Session) -> None:
    _make_record(db_session)

    documents = retrieve_manual_note_documents(db_session, year=2026)

    assert isinstance(documents, list)
    assert all(isinstance(doc, EvidenceDocumentRead) for doc in documents)


def test_retrieve_filters_by_year(db_session: Session) -> None:
    _make_record(db_session, year=2025, title="Note 2025")
    _make_record(db_session, year=2026, title="Note 2026")

    documents = retrieve_manual_note_documents(db_session, year=2026)

    assert len(documents) == 1
    assert documents[0].title == "Note 2026"


def test_retrieve_only_returns_evidence_only_true(db_session: Session) -> None:
    _make_record(db_session, title="Evidence note", evidence_only=True)
    _make_record(db_session, title="Non-evidence note", evidence_only=False)

    documents = retrieve_manual_note_documents(db_session, year=2026)

    assert len(documents) == 1
    assert documents[0].title == "Evidence note"


def test_retrieve_filters_by_prospect_id(db_session: Session) -> None:
    prospect = db_session.query(Prospect).filter(Prospect.name == "Mikel Brown Jr.").one()
    _make_record(db_session, prospect_id=prospect.id, title="Note for prospect")
    _make_record(db_session, prospect_id=None, title="Note without prospect")

    documents = retrieve_manual_note_documents(
        db_session, year=2026, prospect_id=prospect.id
    )

    assert len(documents) == 1
    assert documents[0].title == "Note for prospect"


def test_retrieve_filters_by_team_id(db_session: Session) -> None:
    team = db_session.query(Team).filter(Team.abbr == "SAS").one()
    _make_record(db_session, team_id=team.id, entity_type="team", title="Note for team")
    _make_record(db_session, team_id=None, title="Note without team")

    documents = retrieve_manual_note_documents(
        db_session, year=2026, team_id=team.id
    )

    assert len(documents) == 1
    assert documents[0].title == "Note for team"


def test_retrieve_filters_by_pick_no(db_session: Session) -> None:
    _make_record(db_session, pick_no=5, entity_type="pick", title="Note for pick 5")
    _make_record(db_session, pick_no=None, title="Note without pick")

    documents = retrieve_manual_note_documents(db_session, year=2026, pick_no=5)

    assert len(documents) == 1
    assert documents[0].title == "Note for pick 5"


def test_retrieve_filters_by_entity_type(db_session: Session) -> None:
    _make_record(db_session, entity_type="prospect", title="Prospect note")
    _make_record(db_session, entity_type="team", title="Team note")

    documents = retrieve_manual_note_documents(
        db_session, year=2026, entity_type="team"
    )

    assert len(documents) == 1
    assert documents[0].title == "Team note"


def test_retrieve_combines_multiple_filters(db_session: Session) -> None:
    prospect = db_session.query(Prospect).filter(Prospect.name == "Mikel Brown Jr.").one()
    _make_record(
        db_session,
        prospect_id=prospect.id,
        entity_type="prospect",
        year=2026,
        title="Matching note",
    )
    _make_record(
        db_session,
        prospect_id=prospect.id,
        entity_type="prospect",
        year=2025,
        title="Wrong year",
    )
    _make_record(
        db_session,
        prospect_id=None,
        entity_type="team",
        year=2026,
        title="Wrong entity",
    )

    documents = retrieve_manual_note_documents(
        db_session,
        year=2026,
        prospect_id=prospect.id,
        entity_type="prospect",
    )

    assert len(documents) == 1
    assert documents[0].title == "Matching note"


def test_retrieve_empty_result_returns_empty_list(db_session: Session) -> None:
    documents = retrieve_manual_note_documents(db_session, year=2099)

    assert documents == []


def test_retrieve_default_limit_is_10(db_session: Session) -> None:
    for i in range(15):
        _make_record(db_session, title=f"Note {i}")

    documents = retrieve_manual_note_documents(db_session, year=2026)

    assert len(documents) == DEFAULT_LIMIT


def test_retrieve_limit_clamped_to_max_50(db_session: Session) -> None:
    for i in range(60):
        _make_record(db_session, title=f"Note {i}")

    documents = retrieve_manual_note_documents(db_session, year=2026, limit=100)

    assert len(documents) == MAX_LIMIT


def test_retrieve_limit_clamped_to_min_1(db_session: Session) -> None:
    _make_record(db_session, title="Note A")
    _make_record(db_session, title="Note B")

    documents = retrieve_manual_note_documents(db_session, year=2026, limit=0)

    assert len(documents) == MIN_LIMIT


def test_retrieve_limit_clamped_to_min_when_negative(db_session: Session) -> None:
    _make_record(db_session, title="Note A")
    _make_record(db_session, title="Note B")

    documents = retrieve_manual_note_documents(db_session, year=2026, limit=-5)

    assert len(documents) == MIN_LIMIT


def test_retrieve_custom_limit(db_session: Session) -> None:
    for i in range(10):
        _make_record(db_session, title=f"Note {i}")

    documents = retrieve_manual_note_documents(db_session, year=2026, limit=3)

    assert len(documents) == 3


def test_retrieve_source_type_is_manual_note(db_session: Session) -> None:
    _make_record(db_session)

    documents = retrieve_manual_note_documents(db_session, year=2026)

    assert len(documents) == 1
    assert documents[0].source_type == "manual_note"


def test_retrieve_evidence_only_is_true(db_session: Session) -> None:
    _make_record(db_session)

    documents = retrieve_manual_note_documents(db_session, year=2026)

    assert len(documents) == 1
    assert documents[0].evidence_only is True


def test_retrieve_sorts_by_updated_at_desc(db_session: Session) -> None:
    base_time = datetime(2026, 6, 1, 12, 0, 0)

    record_old = _make_record(db_session, title="Old note")
    db_session.query(ManualNoteRecord).filter_by(id=record_old.id).update(
        {"updated_at": base_time}
    )
    db_session.commit()

    record_new = _make_record(db_session, title="New note")
    db_session.query(ManualNoteRecord).filter_by(id=record_new.id).update(
        {"updated_at": base_time + timedelta(hours=1)}
    )
    db_session.commit()

    documents = retrieve_manual_note_documents(db_session, year=2026)

    assert len(documents) == 2
    assert documents[0].title == "New note"
    assert documents[1].title == "Old note"


def test_retrieve_sorts_by_created_at_desc_when_updated_at_ties(
    db_session: Session,
) -> None:
    base_time = datetime(2026, 6, 1, 12, 0, 0)

    record_first = _make_record(db_session, title="First note")
    db_session.query(ManualNoteRecord).filter_by(id=record_first.id).update(
        {"updated_at": base_time, "created_at": base_time}
    )
    db_session.commit()

    record_second = _make_record(db_session, title="Second note")
    db_session.query(ManualNoteRecord).filter_by(id=record_second.id).update(
        {"updated_at": base_time, "created_at": base_time + timedelta(hours=1)}
    )
    db_session.commit()

    documents = retrieve_manual_note_documents(db_session, year=2026)

    assert len(documents) == 2
    assert documents[0].title == "Second note"
    assert documents[1].title == "First note"


def test_retrieve_sorts_by_id_desc_when_timestamps_tie(db_session: Session) -> None:
    base_time = datetime(2026, 6, 1, 12, 0, 0)

    record_a = _make_record(db_session, title="Note A")
    record_b = _make_record(db_session, title="Note B")
    db_session.query(ManualNoteRecord).filter(
        ManualNoteRecord.id.in_([record_a.id, record_b.id])
    ).update({"updated_at": base_time, "created_at": base_time}, synchronize_session=False)
    db_session.commit()

    documents = retrieve_manual_note_documents(db_session, year=2026)

    assert len(documents) == 2
    # Higher id comes first.
    assert documents[0].source_id == str(max(record_a.id, record_b.id))
    assert documents[1].source_id == str(min(record_a.id, record_b.id))


def test_retrieve_does_not_call_ranking_engine(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_rank_prospects(*args: object, **kwargs: object) -> None:
        raise AssertionError("retrieval service must not call ranking_engine")

    monkeypatch.setattr(
        "app.services.ranking_engine.rank_prospects",
        fail_rank_prospects,
    )
    _make_record(db_session)

    documents = retrieve_manual_note_documents(db_session, year=2026)

    assert len(documents) == 1


def test_retrieval_service_does_not_import_selection_system() -> None:
    import app.services.manual_note_retrieval_service as service_module

    forbidden_module_attrs = {
        "ranking_engine",
        "simulation_service",
        "prediction_calibration",
        "rank_prospects",
        "simulate_draft",
    }

    module_attrs = set(vars(service_module).keys())
    assert forbidden_module_attrs.isdisjoint(module_attrs)


def test_retrieval_service_does_not_import_llm_provider() -> None:
    import app.services.manual_note_retrieval_service as service_module

    forbidden_llm_attrs = {
        "evidence_llm_provider",
        "evidence_llm_explanation_service",
        "evidence_explanation_service",
    }

    module_attrs = set(vars(service_module).keys())
    assert forbidden_llm_attrs.isdisjoint(module_attrs)


def test_retrieve_does_not_commit_or_flush(db_session: Session) -> None:
    """The retrieval service must be read-only: no commit, no flush."""
    _make_record(db_session)

    original_commit = db_session.commit
    original_flush = db_session.flush

    def fail_commit(*args: object, **kwargs: object) -> None:
        raise AssertionError("retrieval service must not call commit")

    def fail_flush(*args: object, **kwargs: object) -> None:
        raise AssertionError("retrieval service must not call flush")

    db_session.commit = fail_commit  # type: ignore[method-assign]
    db_session.flush = fail_flush  # type: ignore[method-assign]

    try:
        documents = retrieve_manual_note_documents(db_session, year=2026)
        assert len(documents) == 1
    finally:
        db_session.commit = original_commit  # type: ignore[method-assign]
        db_session.flush = original_flush  # type: ignore[method-assign]


def test_retrieve_output_does_not_expose_dangerous_fields(
    db_session: Session,
) -> None:
    forbidden_fields = {
        "recommended_player",
        "replacement_player",
        "new_selected_player",
        "rerank_score",
        "new_score",
        "score_adjustment",
        "ranking_weight",
        "selection_override",
        "final_score_delta",
        "prediction_sort_delta",
        "should_have_selected",
        "better_pick",
    }

    _make_record(db_session)
    documents = retrieve_manual_note_documents(db_session, year=2026)

    for doc in documents:
        assert forbidden_fields.isdisjoint(doc.model_dump())


def test_retrieve_chains_into_evidence_document_mapper(db_session: Session) -> None:
    """Retrieval output must be consumable by the B1 mapper without error."""
    from app.services.evidence_document_mapper import map_evidence_document

    _make_record(db_session)
    documents = retrieve_manual_note_documents(db_session, year=2026)

    for doc in documents:
        retrieved, citation = map_evidence_document(doc)
        assert retrieved.source_type == "manual_note"
        assert retrieved.evidence_only is True
        assert citation.source_type == "manual_note"
        assert citation.evidence_only is True


def test_retrieve_preserves_prospect_id_in_output(db_session: Session) -> None:
    prospect = db_session.query(Prospect).filter(Prospect.name == "Mikel Brown Jr.").one()
    _make_record(db_session, prospect_id=prospect.id)

    documents = retrieve_manual_note_documents(
        db_session, year=2026, prospect_id=prospect.id
    )

    assert len(documents) == 1
    assert documents[0].prospect_id == prospect.id


def test_retrieve_preserves_year_in_output(db_session: Session) -> None:
    _make_record(db_session, year=2026)

    documents = retrieve_manual_note_documents(db_session, year=2026)

    assert len(documents) == 1
    assert documents[0].year == 2026
