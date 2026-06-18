"""Tests for the EvidenceDocumentRead schema (RAG-v1-B1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.evidence import EvidenceDocumentRead


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


def test_evidence_document_read_can_be_created() -> None:
    document = _make_document()

    assert document.source_type == "scouting_report"
    assert document.source_id == "scouting:101"
    assert document.prospect_id == 101
    assert document.prospect_name == "Keaton Sample"
    assert document.year == 2026
    assert document.title == "Workout observation"
    assert document.excerpt == "The player showed advanced passing feel in transition."
    assert document.url == "https://example.test/scouting/101"
    assert document.confidence == 0.8
    assert document.retrieval_score == 0.72
    assert document.freshness_days == 3
    assert document.relevance_reason == "Explains a selected player's creation upside."
    assert document.tags == ["passing", "transition"]


def test_evidence_document_read_can_be_dumped() -> None:
    document = _make_document()

    dumped = document.model_dump()

    assert dumped["source_type"] == "scouting_report"
    assert dumped["evidence_only"] is True
    assert dumped["tags"] == ["passing", "transition"]
    assert document.model_dump_json()


def test_evidence_document_read_evidence_only_defaults_to_true() -> None:
    document = EvidenceDocumentRead(
        source_type="news_article",
        excerpt="A short excerpt.",
    )

    assert document.evidence_only is True


def test_evidence_document_read_rejects_evidence_only_false() -> None:
    with pytest.raises(ValidationError):
        EvidenceDocumentRead(
            source_type="news_article",
            excerpt="A short excerpt.",
            evidence_only=False,
        )


def test_evidence_document_read_requires_excerpt() -> None:
    with pytest.raises(ValidationError):
        EvidenceDocumentRead(source_type="news_article")


def test_evidence_document_read_requires_source_type() -> None:
    with pytest.raises(ValidationError):
        EvidenceDocumentRead(excerpt="A short excerpt.")


def test_evidence_document_read_rejects_confidence_above_one() -> None:
    with pytest.raises(ValidationError):
        EvidenceDocumentRead(
            source_type="news_article",
            excerpt="Text.",
            confidence=1.01,
        )


def test_evidence_document_read_rejects_confidence_below_zero() -> None:
    with pytest.raises(ValidationError):
        EvidenceDocumentRead(
            source_type="news_article",
            excerpt="Text.",
            confidence=-0.01,
        )


def test_evidence_document_read_rejects_negative_retrieval_score() -> None:
    with pytest.raises(ValidationError):
        EvidenceDocumentRead(
            source_type="news_article",
            excerpt="Text.",
            retrieval_score=-0.01,
        )


def test_evidence_document_read_rejects_negative_freshness_days() -> None:
    with pytest.raises(ValidationError):
        EvidenceDocumentRead(
            source_type="news_article",
            excerpt="Text.",
            freshness_days=-1,
        )


def test_evidence_document_read_rejects_year_below_range() -> None:
    with pytest.raises(ValidationError):
        EvidenceDocumentRead(
            source_type="news_article",
            excerpt="Text.",
            year=1899,
        )


def test_evidence_document_read_rejects_year_above_range() -> None:
    with pytest.raises(ValidationError):
        EvidenceDocumentRead(
            source_type="news_article",
            excerpt="Text.",
            year=2101,
        )


def test_evidence_document_read_allows_empty_optional_fields() -> None:
    """A document with only source_type + excerpt must be valid."""
    document = EvidenceDocumentRead(
        source_type="manual_note",
        excerpt="A minimal note excerpt.",
    )

    assert document.source_id is None
    assert document.entity_type is None
    assert document.entity_id is None
    assert document.prospect_id is None
    assert document.prospect_name is None
    assert document.team_id is None
    assert document.team_abbr is None
    assert document.year is None
    assert document.title is None
    assert document.url is None
    assert document.source_name is None
    assert document.publisher is None
    assert document.author is None
    assert document.published_at is None
    assert document.confidence is None
    assert document.retrieval_score is None
    assert document.freshness_days is None
    assert document.relevance_reason is None
    assert document.conflict_note is None
    assert document.tags == []
    assert document.evidence_only is True


def test_evidence_document_read_tags_default_is_not_shared() -> None:
    first = EvidenceDocumentRead(source_type="news_article", excerpt="First.")
    second = EvidenceDocumentRead(source_type="news_article", excerpt="Second.")

    first.tags.append("passing")

    assert first.tags == ["passing"]
    assert second.tags == []
    assert first.tags is not second.tags


def test_evidence_document_read_does_not_expose_scoring_or_replacement_fields() -> None:
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

    assert forbidden_fields.isdisjoint(EvidenceDocumentRead.model_fields)


def test_evidence_document_read_entity_id_accepts_int_or_str() -> None:
    int_doc = EvidenceDocumentRead(
        source_type="news_article",
        excerpt="Text.",
        entity_id=101,
    )
    str_doc = EvidenceDocumentRead(
        source_type="news_article",
        excerpt="Text.",
        entity_id="LAL",
    )

    assert int_doc.entity_id == 101
    assert str_doc.entity_id == "LAL"
