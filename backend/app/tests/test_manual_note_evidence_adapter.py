"""Tests for the ManualNoteRecord -> EvidenceDocumentRead adapter (RAG-v1-B3)."""

from __future__ import annotations

import pytest

from app.models.manual_note import ManualNoteRecord
from app.schemas.evidence import EvidenceDocumentRead
from app.services.manual_note_evidence_adapter import (
    manual_note_record_to_evidence_document,
)


def _make_record(**overrides) -> ManualNoteRecord:
    defaults = {
        "id": 101,
        "year": 2026,
        "entity_type": "prospect",
        "entity_id": "101",
        "prospect_id": 101,
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
    return ManualNoteRecord(**defaults)


def test_adapter_creates_evidence_document_read() -> None:
    record = _make_record()

    document = manual_note_record_to_evidence_document(record)

    assert isinstance(document, EvidenceDocumentRead)


def test_adapter_source_type_is_manual_note() -> None:
    record = _make_record()

    document = manual_note_record_to_evidence_document(record)

    assert document.source_type == "manual_note"


def test_adapter_source_id_uses_record_id() -> None:
    record = _make_record(id=42)

    document = manual_note_record_to_evidence_document(record)

    assert document.source_id == "42"


def test_adapter_summary_is_preferred_as_excerpt() -> None:
    record = _make_record(
        summary="Short summary.",
        body="Much longer body text that should not be used as excerpt.",
    )

    document = manual_note_record_to_evidence_document(record)

    assert document.excerpt == "Short summary."


def test_adapter_falls_back_to_body_when_summary_is_none() -> None:
    record = _make_record(
        summary=None,
        body="Body text used as excerpt.",
    )

    document = manual_note_record_to_evidence_document(record)

    assert document.excerpt == "Body text used as excerpt."


def test_adapter_falls_back_to_body_when_summary_is_empty_string() -> None:
    record = _make_record(
        summary="",
        body="Body text used as excerpt.",
    )

    document = manual_note_record_to_evidence_document(record)

    assert document.excerpt == "Body text used as excerpt."


def test_adapter_falls_back_to_body_when_summary_is_whitespace_only() -> None:
    record = _make_record(
        summary="   ",
        body="Body text used as excerpt.",
    )

    document = manual_note_record_to_evidence_document(record)

    assert document.excerpt == "Body text used as excerpt."


def test_adapter_truncates_long_body_excerpt() -> None:
    long_body = "x" * 2000
    record = _make_record(summary=None, body=long_body)

    document = manual_note_record_to_evidence_document(record)

    assert len(document.excerpt) == 1200
    assert document.excerpt == "x" * 1200


def test_adapter_excerpt_is_never_empty_when_body_exists() -> None:
    record = _make_record(summary=None, body="A non-empty body.")

    document = manual_note_record_to_evidence_document(record)

    assert document.excerpt != ""


def test_adapter_tags_split_into_list() -> None:
    record = _make_record(tags="shooting,defense")

    document = manual_note_record_to_evidence_document(record)

    assert document.tags == ["shooting", "defense"]


def test_adapter_tags_stripped_of_whitespace() -> None:
    record = _make_record(tags=" shooting , defense ")

    document = manual_note_record_to_evidence_document(record)

    assert document.tags == ["shooting", "defense"]


def test_adapter_empty_tags_return_empty_list() -> None:
    record = _make_record(tags="")

    document = manual_note_record_to_evidence_document(record)

    assert document.tags == []


def test_adapter_none_tags_return_empty_list() -> None:
    record = _make_record(tags=None)

    document = manual_note_record_to_evidence_document(record)

    assert document.tags == []


def test_adapter_tags_drops_empty_entries() -> None:
    record = _make_record(tags="shooting,,defense,")

    document = manual_note_record_to_evidence_document(record)

    assert document.tags == ["shooting", "defense"]


def test_adapter_source_url_maps_to_url() -> None:
    record = _make_record(source_url="https://example.test/note/101")

    document = manual_note_record_to_evidence_document(record)

    assert document.url == "https://example.test/note/101"


def test_adapter_source_date_maps_to_published_at() -> None:
    record = _make_record(source_date="2026-06-16")

    document = manual_note_record_to_evidence_document(record)

    assert document.published_at == "2026-06-16"


def test_adapter_confidence_is_preserved() -> None:
    record = _make_record(confidence=0.35)

    document = manual_note_record_to_evidence_document(record)

    assert document.confidence == 0.35


def test_adapter_confidence_none_is_preserved() -> None:
    record = _make_record(confidence=None)

    document = manual_note_record_to_evidence_document(record)

    assert document.confidence is None


def test_adapter_relevance_reason_is_preserved() -> None:
    record = _make_record(relevance_reason="Custom relevance reason.")

    document = manual_note_record_to_evidence_document(record)

    assert document.relevance_reason == "Custom relevance reason."


def test_adapter_evidence_only_is_true() -> None:
    record = _make_record()

    document = manual_note_record_to_evidence_document(record)

    assert document.evidence_only is True


def test_adapter_rejects_evidence_only_false() -> None:
    record = _make_record(evidence_only=False)

    with pytest.raises(ValueError, match="evidence_only"):
        manual_note_record_to_evidence_document(record)


def test_adapter_rejects_evidence_only_none() -> None:
    record = _make_record(evidence_only=None)

    with pytest.raises(ValueError, match="evidence_only"):
        manual_note_record_to_evidence_document(record)


def test_adapter_preserves_entity_fields() -> None:
    record = _make_record(
        entity_type="team",
        entity_id="LAL",
        prospect_id=None,
        team_id=7,
        year=2025,
    )

    document = manual_note_record_to_evidence_document(record)

    assert document.entity_type == "team"
    assert document.entity_id == "LAL"
    assert document.prospect_id is None
    assert document.team_id == 7
    assert document.year == 2025


def test_adapter_preserves_title_and_author() -> None:
    record = _make_record(
        title="Custom title",
        author="Custom author",
    )

    document = manual_note_record_to_evidence_document(record)

    assert document.title == "Custom title"
    assert document.author == "Custom author"


def test_adapter_source_name_uses_record_source() -> None:
    record = _make_record(source="scout_notes")

    document = manual_note_record_to_evidence_document(record)

    assert document.source_name == "scout_notes"


def test_adapter_retrieval_score_and_freshness_days_are_none() -> None:
    """The adapter must not fabricate retrieval metadata; that is the
    retrieval service's job (RAG-v1-C)."""
    record = _make_record()

    document = manual_note_record_to_evidence_document(record)

    assert document.retrieval_score is None
    assert document.freshness_days is None


def test_adapter_publisher_and_conflict_note_are_none() -> None:
    """ManualNoteRecord has no publisher / conflict_note columns."""
    record = _make_record()

    document = manual_note_record_to_evidence_document(record)

    assert document.publisher is None
    assert document.conflict_note is None


def test_adapter_prospect_name_and_team_abbr_are_none() -> None:
    """ManualNoteRecord does not store prospect_name / team_abbr; the
    retrieval layer can enrich these later."""
    record = _make_record()

    document = manual_note_record_to_evidence_document(record)

    assert document.prospect_name is None
    assert document.team_abbr is None


def test_adapter_does_not_mutate_input_record() -> None:
    record = _make_record(tags="passing,transition")

    manual_note_record_to_evidence_document(record)

    assert record.tags == "passing,transition"
    assert record.title == "Workout observation"
    assert record.body == "The player showed advanced passing feel in transition."


def test_adapter_does_not_call_ranking_engine(monkeypatch) -> None:
    def fail_rank_prospects(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("manual_note_evidence_adapter must not call ranking_engine")

    monkeypatch.setattr(
        "app.services.ranking_engine.rank_prospects",
        fail_rank_prospects,
    )
    record = _make_record()

    document = manual_note_record_to_evidence_document(record)

    assert document.evidence_only is True


def test_adapter_does_not_import_database_session() -> None:
    import app.services.manual_note_evidence_adapter as adapter_module

    forbidden_module_attrs = {
        "database",
        "SessionLocal",
        "get_db",
        "sessionmaker",
        "sqlalchemy",
        "engine",
        "Session",
    }

    module_attrs = set(vars(adapter_module).keys())
    assert forbidden_module_attrs.isdisjoint(module_attrs)


def test_adapter_output_does_not_expose_dangerous_fields() -> None:
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

    record = _make_record()
    document = manual_note_record_to_evidence_document(record)

    assert forbidden_fields.isdisjoint(EvidenceDocumentRead.model_fields)
    assert forbidden_fields.isdisjoint(document.model_dump())


def test_adapter_chains_into_evidence_document_mapper() -> None:
    """The adapter output must be consumable by the B1 mapper without error."""
    from app.services.evidence_document_mapper import map_evidence_document

    record = _make_record()
    document = manual_note_record_to_evidence_document(record)

    retrieved, citation = map_evidence_document(document)

    assert retrieved.source_type == "manual_note"
    assert retrieved.source_id == "101"
    assert retrieved.evidence_only is True
    assert citation.source_type == "manual_note"
    assert citation.evidence_only is True
