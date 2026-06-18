"""Tests for the EvidenceDocumentRead -> RetrievedEvidence / EvidenceCitation mapper."""

from __future__ import annotations

import pytest

from app.schemas.evidence import (
    EvidenceCitation,
    EvidenceDocumentRead,
    RetrievedEvidence,
)
from app.services.evidence_document_mapper import (
    evidence_document_to_citation,
    evidence_document_to_retrieved_evidence,
    map_evidence_document,
)


def _make_document(**overrides) -> EvidenceDocumentRead:
    defaults = {
        "source_type": "scouting_report",
        "source_id": "scouting:101",
        "entity_type": "prospect",
        "entity_id": 101,
        "prospect_id": 101,
        "prospect_name": "Keaton Sample",
        "team_id": None,
        "team_abbr": None,
        "year": 2026,
        "title": "Workout observation",
        "excerpt": "The player showed advanced passing feel in transition.",
        "url": "https://example.test/scouting/101",
        "source_name": "DraftMind Scouting",
        "publisher": "DraftMind",
        "author": "Analyst Name",
        "published_at": "2026-06-16",
        "confidence": 0.8,
        "retrieval_score": 0.72,
        "freshness_days": 3,
        "relevance_reason": "Explains a selected player's creation upside.",
        "conflict_note": None,
        "tags": ["passing", "transition"],
    }
    defaults.update(overrides)
    return EvidenceDocumentRead(**defaults)


def test_evidence_document_to_citation_creates_evidence_citation() -> None:
    document = _make_document()

    citation = evidence_document_to_citation(document)

    assert isinstance(citation, EvidenceCitation)
    assert citation.source_type == "scouting_report"
    assert citation.source_id == "scouting:101"
    assert citation.title == "Workout observation"
    assert citation.url == "https://example.test/scouting/101"
    assert citation.date == "2026-06-16"
    assert citation.excerpt == "The player showed advanced passing feel in transition."
    assert citation.confidence == 0.8
    assert citation.evidence_source_type == "scouting_report"
    assert citation.entity_type == "prospect"
    assert citation.entity_id == 101
    assert citation.publisher == "DraftMind"
    assert citation.author == "Analyst Name"
    assert citation.retrieved_at is None
    assert citation.freshness_days == 3
    assert citation.relevance_reason == "Explains a selected player's creation upside."
    assert citation.evidence_only is True


def test_evidence_document_to_retrieved_evidence_creates_retrieved_evidence() -> None:
    document = _make_document()

    retrieved = evidence_document_to_retrieved_evidence(document)

    assert isinstance(retrieved, RetrievedEvidence)
    assert retrieved.source_type == "scouting_report"
    assert retrieved.source_id == "scouting:101"
    assert retrieved.citation is not None
    assert isinstance(retrieved.citation, EvidenceCitation)
    assert retrieved.entity_type == "prospect"
    assert retrieved.entity_id == 101
    assert retrieved.title == "Workout observation"
    assert retrieved.excerpt == "The player showed advanced passing feel in transition."
    assert retrieved.url == "https://example.test/scouting/101"
    assert retrieved.date == "2026-06-16"
    assert retrieved.confidence == 0.8
    assert retrieved.retrieval_score == 0.72
    assert retrieved.freshness_days == 3
    assert retrieved.relevance_reason == "Explains a selected player's creation upside."
    assert retrieved.conflict_note is None
    assert retrieved.evidence_only is True


def test_map_evidence_document_returns_pair_with_shared_citation() -> None:
    document = _make_document()

    retrieved, citation = map_evidence_document(document)

    assert isinstance(retrieved, RetrievedEvidence)
    assert isinstance(citation, EvidenceCitation)
    assert retrieved.citation is citation


def test_citation_evidence_only_is_true() -> None:
    document = _make_document()

    assert evidence_document_to_citation(document).evidence_only is True


def test_retrieved_evidence_evidence_only_is_true() -> None:
    document = _make_document()

    assert evidence_document_to_retrieved_evidence(document).evidence_only is True


def test_mapper_preserves_source_type_and_source_id() -> None:
    document = _make_document(
        source_type="news_article",
        source_id="news:42",
    )

    citation = evidence_document_to_citation(document)
    retrieved = evidence_document_to_retrieved_evidence(document)

    assert citation.source_type == "news_article"
    assert citation.source_id == "news:42"
    assert retrieved.source_type == "news_article"
    assert retrieved.source_id == "news:42"


def test_mapper_preserves_title_and_excerpt() -> None:
    document = _make_document(
        title="Custom title",
        excerpt="Custom excerpt text.",
    )

    citation = evidence_document_to_citation(document)
    retrieved = evidence_document_to_retrieved_evidence(document)

    assert citation.title == "Custom title"
    assert citation.excerpt == "Custom excerpt text."
    assert retrieved.title == "Custom title"
    assert retrieved.excerpt == "Custom excerpt text."


def test_mapper_preserves_relevance_reason() -> None:
    document = _make_document(relevance_reason="Custom relevance reason.")

    citation = evidence_document_to_citation(document)
    retrieved = evidence_document_to_retrieved_evidence(document)

    assert citation.relevance_reason == "Custom relevance reason."
    assert retrieved.relevance_reason == "Custom relevance reason."


def test_mapper_preserves_confidence() -> None:
    document = _make_document(confidence=0.35)

    citation = evidence_document_to_citation(document)
    retrieved = evidence_document_to_retrieved_evidence(document)

    assert citation.confidence == 0.35
    assert retrieved.confidence == 0.35


def test_mapper_propagates_none_confidence() -> None:
    document = _make_document(confidence=None)

    citation = evidence_document_to_citation(document)
    retrieved = evidence_document_to_retrieved_evidence(document)

    assert citation.confidence is None
    assert retrieved.confidence is None


def test_mapper_handles_empty_url() -> None:
    document = _make_document(url=None)

    citation = evidence_document_to_citation(document)
    retrieved = evidence_document_to_retrieved_evidence(document)

    assert citation.url is None
    assert retrieved.url is None


def test_mapper_handles_empty_published_at() -> None:
    document = _make_document(published_at=None)

    citation = evidence_document_to_citation(document)
    retrieved = evidence_document_to_retrieved_evidence(document)

    assert citation.date is None
    assert retrieved.date is None


def test_mapper_propagates_retrieval_score_and_freshness_days() -> None:
    document = _make_document(retrieval_score=0.55, freshness_days=7)

    retrieved = evidence_document_to_retrieved_evidence(document)

    assert retrieved.retrieval_score == 0.55
    assert retrieved.freshness_days == 7


def test_mapper_propagates_conflict_note() -> None:
    document = _make_document(conflict_note="Conflicts with market projection.")

    retrieved = evidence_document_to_retrieved_evidence(document)

    assert retrieved.conflict_note == "Conflicts with market projection."


def test_mapper_retrieved_at_is_always_none() -> None:
    document = _make_document()

    citation = evidence_document_to_citation(document)

    assert citation.retrieved_at is None


def test_mapper_handles_entity_type_and_entity_id() -> None:
    document = _make_document(entity_type="team", entity_id="LAL")

    citation = evidence_document_to_citation(document)
    retrieved = evidence_document_to_retrieved_evidence(document)

    assert citation.entity_type == "team"
    assert citation.entity_id == "LAL"
    assert retrieved.entity_type == "team"
    assert retrieved.entity_id == "LAL"


def test_mapper_handles_minimal_document() -> None:
    """A document with only source_type + excerpt must map without error."""
    document = EvidenceDocumentRead(
        source_type="manual_note",
        excerpt="A minimal note excerpt.",
    )

    citation = evidence_document_to_citation(document)
    retrieved = evidence_document_to_retrieved_evidence(document)
    pair = map_evidence_document(document)

    assert citation.source_type == "manual_note"
    assert citation.title is None
    assert citation.url is None
    assert citation.confidence is None
    assert citation.evidence_only is True

    assert retrieved.source_type == "manual_note"
    assert retrieved.title is None
    assert retrieved.url is None
    assert retrieved.confidence is None
    assert retrieved.retrieval_score is None
    assert retrieved.freshness_days is None
    assert retrieved.evidence_only is True

    assert pair[0].evidence_only is True
    assert pair[1].evidence_only is True


def test_mapper_does_not_mutate_input_document() -> None:
    document = _make_document(tags=["passing"])
    original_dump = document.model_dump()

    evidence_document_to_citation(document)
    evidence_document_to_retrieved_evidence(document)
    map_evidence_document(document)

    assert document.model_dump() == original_dump


def test_mapper_does_not_call_ranking_engine(monkeypatch) -> None:
    def fail_rank_prospects(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("evidence_document_mapper must not call ranking_engine")

    monkeypatch.setattr(
        "app.services.ranking_engine.rank_prospects",
        fail_rank_prospects,
    )
    document = _make_document()

    citation = evidence_document_to_citation(document)
    retrieved = evidence_document_to_retrieved_evidence(document)
    pair = map_evidence_document(document)

    assert citation.evidence_only is True
    assert retrieved.evidence_only is True
    assert pair[0].evidence_only is True
    assert pair[1].evidence_only is True


def test_mapper_does_not_import_database_session() -> None:
    import app.services.evidence_document_mapper as mapper_module

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

    document = _make_document()
    citation = evidence_document_to_citation(document)
    retrieved = evidence_document_to_retrieved_evidence(document)

    assert forbidden_fields.isdisjoint(EvidenceCitation.model_fields)
    assert forbidden_fields.isdisjoint(RetrievedEvidence.model_fields)
    assert forbidden_fields.isdisjoint(citation.model_dump())
    assert forbidden_fields.isdisjoint(retrieved.model_dump())
