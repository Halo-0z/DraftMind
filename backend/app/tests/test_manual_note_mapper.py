"""Tests for ManualNote -> RetrievedEvidence / EvidenceCitation mapper."""

from __future__ import annotations

import pytest

from app.schemas.evidence import (
    EvidenceCitation,
    ManualNote,
    RetrievedEvidence,
)
from app.services.manual_note_mapper import (
    MANUAL_NOTE_EVIDENCE_SOURCE_TYPE,
    _excerpt_from_manual_note,
    manual_note_to_citation,
    manual_note_to_evidence_pair,
    manual_note_to_retrieved_evidence,
)


def _make_note(**overrides) -> ManualNote:
    defaults = {
        "year": 2026,
        "entity_type": "prospect",
        "entity_id": 101,
        "prospect_id": 101,
        "title": "Workout observation",
        "body": "The player showed advanced passing feel in transition.",
        "summary": "Passing feel note.",
        "author": "Analyst Name",
        "source_url": "https://example.test/note/101",
        "source_date": "2026-06-16",
        "confidence": 0.8,
        "tags": ["passing", "transition"],
        "relevance_reason": "Explains a selected player's creation upside.",
    }
    defaults.update(overrides)
    return ManualNote(**defaults)


def test_manual_note_to_citation_creates_evidence_citation() -> None:
    note = _make_note(note_id=42)

    citation = manual_note_to_citation(note)

    assert isinstance(citation, EvidenceCitation)
    assert citation.source_type == "manual"
    assert citation.source_id == "42"
    assert citation.title == "Workout observation"
    assert citation.url == "https://example.test/note/101"
    assert citation.date == "2026-06-16"
    assert citation.excerpt == "Passing feel note."
    assert citation.confidence == 0.8
    assert citation.evidence_source_type == MANUAL_NOTE_EVIDENCE_SOURCE_TYPE
    assert citation.entity_type == "prospect"
    assert citation.entity_id == 101
    assert citation.author == "Analyst Name"
    assert citation.retrieved_at is None
    assert citation.relevance_reason == "Explains a selected player's creation upside."
    assert citation.evidence_only is True


def test_manual_note_to_retrieved_evidence_creates_retrieved_evidence() -> None:
    note = _make_note(note_id=42)

    retrieved = manual_note_to_retrieved_evidence(note)

    assert isinstance(retrieved, RetrievedEvidence)
    assert retrieved.source_type == MANUAL_NOTE_EVIDENCE_SOURCE_TYPE
    assert retrieved.source_id == "42"
    assert retrieved.citation is not None
    assert isinstance(retrieved.citation, EvidenceCitation)
    assert retrieved.entity_type == "prospect"
    assert retrieved.entity_id == 101
    assert retrieved.title == "Workout observation"
    assert retrieved.excerpt == "Passing feel note."
    assert retrieved.url == "https://example.test/note/101"
    assert retrieved.date == "2026-06-16"
    assert retrieved.confidence == 0.8
    assert retrieved.retrieval_score is None
    assert retrieved.freshness_days is None
    assert retrieved.relevance_reason == "Explains a selected player's creation upside."
    assert retrieved.conflict_note is None
    assert retrieved.evidence_only is True


def test_summary_is_preferred_as_excerpt() -> None:
    note = _make_note(
        note_id=1,
        summary="Short summary.",
        body="A much longer body that should be ignored when summary exists.",
    )

    assert _excerpt_from_manual_note(note) == "Short summary."
    assert manual_note_to_retrieved_evidence(note).excerpt == "Short summary."
    assert manual_note_to_citation(note).excerpt == "Short summary."


def test_body_is_used_when_summary_is_missing() -> None:
    note = _make_note(note_id=1, summary=None, body="Body content used as excerpt.")

    assert _excerpt_from_manual_note(note) == "Body content used as excerpt."
    assert manual_note_to_retrieved_evidence(note).excerpt == "Body content used as excerpt."
    assert manual_note_to_citation(note).excerpt == "Body content used as excerpt."


def test_body_is_truncated_when_over_max_length() -> None:
    long_body = "x" * 1500
    note = _make_note(note_id=1, summary=None, body=long_body)

    excerpt = _excerpt_from_manual_note(note, max_length=1000)

    assert len(excerpt) == 1000
    assert excerpt == "x" * 1000
    assert manual_note_to_retrieved_evidence(note).excerpt == "x" * 1000
    assert manual_note_to_citation(note).excerpt == "x" * 1000


def test_body_truncation_respects_custom_max_length() -> None:
    note = _make_note(note_id=1, summary=None, body="y" * 500)

    assert _excerpt_from_manual_note(note, max_length=50) == "y" * 50


def test_citation_evidence_only_is_true() -> None:
    note = _make_note()

    assert manual_note_to_citation(note).evidence_only is True


def test_retrieved_evidence_evidence_only_is_true() -> None:
    note = _make_note()

    assert manual_note_to_retrieved_evidence(note).evidence_only is True


def test_source_id_is_none_when_note_id_is_none() -> None:
    note = _make_note(note_id=None)

    citation = manual_note_to_citation(note)
    retrieved = manual_note_to_retrieved_evidence(note)

    assert citation.source_id is None
    assert retrieved.source_id is None


def test_source_id_supports_string_note_id() -> None:
    note = _make_note(note_id="analyst-note-7")

    citation = manual_note_to_citation(note)
    retrieved = manual_note_to_retrieved_evidence(note)

    assert citation.source_id == "analyst-note-7"
    assert retrieved.source_id == "analyst-note-7"


def test_confidence_is_propagated() -> None:
    note = _make_note(confidence=0.35)

    citation = manual_note_to_citation(note)
    retrieved = manual_note_to_retrieved_evidence(note)

    assert citation.confidence == 0.35
    assert retrieved.confidence == 0.35


def test_confidence_none_is_propagated() -> None:
    note = _make_note(confidence=None)

    citation = manual_note_to_citation(note)
    retrieved = manual_note_to_retrieved_evidence(note)

    assert citation.confidence is None
    assert retrieved.confidence is None


def test_entity_type_and_entity_id_are_propagated() -> None:
    note = _make_note(entity_type="team", entity_id="LAL", note_id=5)

    citation = manual_note_to_citation(note)
    retrieved = manual_note_to_retrieved_evidence(note)

    assert citation.entity_type == "team"
    assert citation.entity_id == "LAL"
    assert retrieved.entity_type == "team"
    assert retrieved.entity_id == "LAL"


def test_mapper_does_not_call_ranking_engine(monkeypatch) -> None:
    def fail_rank_prospects(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("manual_note_mapper must not call ranking_engine")

    monkeypatch.setattr(
        "app.services.ranking_engine.rank_prospects",
        fail_rank_prospects,
    )
    note = _make_note()

    citation = manual_note_to_citation(note)
    retrieved = manual_note_to_retrieved_evidence(note)
    pair = manual_note_to_evidence_pair(note)

    assert citation.evidence_only is True
    assert retrieved.evidence_only is True
    assert pair[0].evidence_only is True
    assert pair[1].evidence_only is True


def test_mapper_does_not_import_database_session() -> None:
    import app.services.manual_note_mapper as mapper_module

    forbidden_module_attrs = {
        "database",
        "SessionLocal",
        "get_db",
        "sessionmaker",
        "sqlalchemy",
        "engine",
        "Session",
    }

    module_attrs = set(vars(mapper_module).keys())
    assert forbidden_module_attrs.isdisjoint(module_attrs)


def test_mapper_output_does_not_expose_dangerous_fields() -> None:
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
    }

    note = _make_note()
    citation = manual_note_to_citation(note)
    retrieved = manual_note_to_retrieved_evidence(note)

    assert forbidden_fields.isdisjoint(EvidenceCitation.model_fields)
    assert forbidden_fields.isdisjoint(RetrievedEvidence.model_fields)
    assert forbidden_fields.isdisjoint(citation.model_dump())
    assert forbidden_fields.isdisjoint(retrieved.model_dump())


def test_manual_note_to_evidence_pair_returns_shared_citation() -> None:
    note = _make_note(note_id=9)

    retrieved, citation = manual_note_to_evidence_pair(note)

    assert isinstance(retrieved, RetrievedEvidence)
    assert isinstance(citation, EvidenceCitation)
    assert retrieved.citation is citation
    assert retrieved.source_id == "9"
    assert citation.source_id == "9"


def test_mapper_preserves_relevance_reason() -> None:
    note = _make_note(relevance_reason="Custom relevance reason.")

    citation = manual_note_to_citation(note)
    retrieved = manual_note_to_retrieved_evidence(note)

    assert citation.relevance_reason == "Custom relevance reason."
    assert retrieved.relevance_reason == "Custom relevance reason."


def test_mapper_retrieval_score_and_freshness_days_are_none() -> None:
    note = _make_note()

    retrieved = manual_note_to_retrieved_evidence(note)

    assert retrieved.retrieval_score is None
    assert retrieved.freshness_days is None
    assert retrieved.conflict_note is None


def test_mapper_does_not_mutate_input_note() -> None:
    note = _make_note(note_id=1, tags=["passing"])
    original_dump = note.model_dump()

    manual_note_to_citation(note)
    manual_note_to_retrieved_evidence(note)
    manual_note_to_evidence_pair(note)

    assert note.model_dump() == original_dump


def test_mapper_handles_all_entity_types() -> None:
    for entity_type in [
        "prospect",
        "team",
        "pick",
        "market_projection",
        "scouting_profile",
        "news_article",
        "simulation_context",
    ]:
        note = _make_note(entity_type=entity_type, entity_id=1, note_id=1)

        citation = manual_note_to_citation(note)
        retrieved = manual_note_to_retrieved_evidence(note)

        assert citation.entity_type == entity_type
        assert retrieved.entity_type == entity_type
