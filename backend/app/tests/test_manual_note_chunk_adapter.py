"""Tests for the ManualNoteRecord -> EvidenceChunk adapter (RAG-v2-M1-D).

Covers:
- ManualNoteRecord -> EvidenceChunk basic mapping
- evidence_only=True passes; evidence_only=False / None rejected
- chunk_id format stable; chunk_index=0; chunk_count=1
- source_type="manual_note"; source_id uses note.id
- content/excerpt mapping (summary preferred, None falls through to mapper)
- tags split, stripped, not shared mutable list
- adapter does not mutate note
- adapter does not query DB / call LLM / import ranking/simulation/prediction/recommendation
- retrieval_score stays None
- Full chain: ManualNoteRecord -> EvidenceChunk -> EvidenceDocumentRead
  -> map_evidence_document
"""

from __future__ import annotations

import ast
import copy
from datetime import datetime

import pytest

from app.models.manual_note import ManualNoteRecord
from app.schemas.evidence import (
    EvidenceChunk,
    EvidenceCitation,
    EvidenceDocumentRead,
    RetrievedEvidence,
)
from app.services.manual_note_chunk_adapter import (
    manual_note_record_to_evidence_chunk,
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


# ---------------------------------------------------------------------------
# Basic mapping
# ---------------------------------------------------------------------------


def test_adapter_returns_evidence_chunk() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record())
    assert isinstance(chunk, EvidenceChunk)


def test_adapter_source_type_is_manual_note() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record())
    assert chunk.source_type == "manual_note"


def test_adapter_source_id_uses_record_id() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record(id=42))
    assert chunk.source_id == "42"


def test_adapter_chunk_id_format_is_stable() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record(id=42))
    assert chunk.chunk_id == "manual_note:42:0"


def test_adapter_chunk_index_is_zero() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record())
    assert chunk.chunk_index == 0


def test_adapter_chunk_count_is_one() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record())
    assert chunk.chunk_count == 1


# ---------------------------------------------------------------------------
# evidence_only protection
# ---------------------------------------------------------------------------


def test_adapter_evidence_only_true_passes() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record(evidence_only=True))
    assert chunk.evidence_only is True


def test_adapter_rejects_evidence_only_false() -> None:
    with pytest.raises(ValueError, match="evidence_only"):
        manual_note_record_to_evidence_chunk(_make_record(evidence_only=False))


def test_adapter_rejects_evidence_only_none() -> None:
    with pytest.raises(ValueError, match="evidence_only"):
        manual_note_record_to_evidence_chunk(_make_record(evidence_only=None))


# ---------------------------------------------------------------------------
# content / excerpt mapping
# ---------------------------------------------------------------------------


def test_adapter_content_uses_body() -> None:
    chunk = manual_note_record_to_evidence_chunk(
        _make_record(body="Body text used as content.")
    )
    assert chunk.content == "Body text used as content."


def test_adapter_excerpt_uses_summary_when_present() -> None:
    chunk = manual_note_record_to_evidence_chunk(
        _make_record(summary="Short summary.", body="Long body text.")
    )
    assert chunk.excerpt == "Short summary."


def test_adapter_excerpt_is_none_when_summary_is_none() -> None:
    chunk = manual_note_record_to_evidence_chunk(
        _make_record(summary=None, body="Body text.")
    )
    assert chunk.excerpt is None


def test_adapter_excerpt_is_none_when_summary_is_empty() -> None:
    chunk = manual_note_record_to_evidence_chunk(
        _make_record(summary="", body="Body text.")
    )
    assert chunk.excerpt is None


def test_adapter_excerpt_is_none_when_summary_is_whitespace() -> None:
    chunk = manual_note_record_to_evidence_chunk(
        _make_record(summary="   ", body="Body text.")
    )
    assert chunk.excerpt is None


def test_adapter_title_is_preserved() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record(title="Custom title"))
    assert chunk.title == "Custom title"


# ---------------------------------------------------------------------------
# Entity / metadata mapping
# ---------------------------------------------------------------------------


def test_adapter_preserves_entity_fields() -> None:
    chunk = manual_note_record_to_evidence_chunk(
        _make_record(
            entity_type="team",
            entity_id="LAL",
            prospect_id=None,
            team_id=7,
            pick_no=5,
            year=2025,
        )
    )
    assert chunk.entity_type == "team"
    assert chunk.entity_id == "LAL"
    assert chunk.prospect_id is None
    assert chunk.team_id == 7
    assert chunk.pick_no == 5
    assert chunk.year == 2025


def test_adapter_prospect_name_and_team_abbr_are_none() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record())
    assert chunk.prospect_name is None
    assert chunk.team_abbr is None


def test_adapter_source_url_maps_to_url() -> None:
    chunk = manual_note_record_to_evidence_chunk(
        _make_record(source_url="https://example.test/note/101")
    )
    assert chunk.url == "https://example.test/note/101"


def test_adapter_source_name_uses_record_source() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record(source="scout_notes"))
    assert chunk.source_name == "scout_notes"


def test_adapter_author_is_preserved() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record(author="Custom author"))
    assert chunk.author == "Custom author"


def test_adapter_publisher_and_conflict_note_are_none() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record())
    assert chunk.publisher is None
    assert chunk.conflict_note is None


def test_adapter_confidence_is_preserved() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record(confidence=0.35))
    assert chunk.confidence == 0.35


def test_adapter_confidence_none_is_preserved() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record(confidence=None))
    assert chunk.confidence is None


def test_adapter_relevance_reason_is_preserved() -> None:
    chunk = manual_note_record_to_evidence_chunk(
        _make_record(relevance_reason="Custom relevance reason.")
    )
    assert chunk.relevance_reason == "Custom relevance reason."


def test_adapter_published_at_uses_updated_at() -> None:
    ts = datetime(2026, 6, 19, 12, 0, 0)
    chunk = manual_note_record_to_evidence_chunk(
        _make_record(updated_at=ts, created_at=datetime(2026, 6, 1, 12, 0, 0))
    )
    assert chunk.published_at == ts


def test_adapter_published_at_falls_back_to_created_at() -> None:
    ts = datetime(2026, 6, 1, 12, 0, 0)
    chunk = manual_note_record_to_evidence_chunk(
        _make_record(updated_at=None, created_at=ts)
    )
    assert chunk.published_at == ts


def test_adapter_published_at_none_when_both_none() -> None:
    chunk = manual_note_record_to_evidence_chunk(
        _make_record(updated_at=None, created_at=None)
    )
    assert chunk.published_at is None


# ---------------------------------------------------------------------------
# tags handling
# ---------------------------------------------------------------------------


def test_adapter_tags_split_into_list() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record(tags="shooting,defense"))
    assert chunk.tags == ["shooting", "defense"]


def test_adapter_tags_stripped_of_whitespace() -> None:
    chunk = manual_note_record_to_evidence_chunk(
        _make_record(tags=" shooting , defense ")
    )
    assert chunk.tags == ["shooting", "defense"]


def test_adapter_empty_tags_return_empty_list() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record(tags=""))
    assert chunk.tags == []


def test_adapter_none_tags_return_empty_list() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record(tags=None))
    assert chunk.tags == []


def test_adapter_tags_drops_empty_entries() -> None:
    chunk = manual_note_record_to_evidence_chunk(
        _make_record(tags="shooting,,defense,")
    )
    assert chunk.tags == ["shooting", "defense"]


def test_adapter_tags_not_shared_with_caller() -> None:
    """The returned tags list must not be backed by the record's tag string."""
    record = _make_record(tags="shooting,defense")
    chunk = manual_note_record_to_evidence_chunk(record)
    chunk.tags.append("extra")
    assert record.tags == "shooting,defense"


# ---------------------------------------------------------------------------
# retrieval_score
# ---------------------------------------------------------------------------


def test_adapter_retrieval_score_is_none() -> None:
    chunk = manual_note_record_to_evidence_chunk(_make_record())
    assert chunk.retrieval_score is None


# ---------------------------------------------------------------------------
# No mutation of input
# ---------------------------------------------------------------------------


def test_adapter_does_not_mutate_input_record() -> None:
    record = _make_record(tags="passing,transition")
    # Snapshot the data fields (exclude SQLAlchemy internal state).
    original = {
        k: copy.deepcopy(v)
        for k, v in record.__dict__.items()
        if k != "_sa_instance_state"
    }

    manual_note_record_to_evidence_chunk(record)

    current = {
        k: v for k, v in record.__dict__.items() if k != "_sa_instance_state"
    }
    assert current == original
    assert record.tags == "passing,transition"
    assert record.title == "Workout observation"
    assert record.body == "The player showed advanced passing feel in transition."


# ---------------------------------------------------------------------------
# No DB / LLM / ranking / simulation / prediction / recommendation
# ---------------------------------------------------------------------------


def test_adapter_does_not_import_database_session() -> None:
    import app.services.manual_note_chunk_adapter as adapter_module

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


def test_adapter_module_does_not_import_llm() -> None:
    import app.services.manual_note_chunk_adapter as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "import openai" not in source
    assert "import anthropic" not in source
    assert "llm_service" not in source


def test_adapter_module_does_not_import_decision_modules() -> None:
    """Verify the adapter module does not IMPORT any decision-making modules.

    Uses AST parsing so that legitimate docstring mentions of these module
    names (e.g. "does not invoke ranking_engine") are not flagged.  Only
    actual ``import`` / ``from ... import`` statements are inspected.
    """
    import app.services.manual_note_chunk_adapter as module

    source = open(module.__file__, encoding="utf-8").read()
    tree = ast.parse(source)

    forbidden_modules = {
        "ranking_engine",
        "simulation_service",
        "prediction_calibration",
        "recommendation_service",
    }

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.add(node.module.split(".")[-1])
            for alias in node.names:
                imported_names.add(alias.name)

    for forbidden in forbidden_modules:
        assert forbidden not in imported_names, (
            f"adapter module imports forbidden module '{forbidden}'"
        )


def test_adapter_does_not_call_ranking_engine(monkeypatch) -> None:
    def fail_rank_prospects(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError(
            "manual_note_chunk_adapter must not call ranking_engine"
        )

    monkeypatch.setattr(
        "app.services.ranking_engine.rank_prospects",
        fail_rank_prospects,
    )

    chunk = manual_note_record_to_evidence_chunk(_make_record())
    assert chunk.evidence_only is True


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

    chunk = manual_note_record_to_evidence_chunk(_make_record())

    assert forbidden_fields.isdisjoint(EvidenceChunk.model_fields)
    assert forbidden_fields.isdisjoint(chunk.model_dump())


# ---------------------------------------------------------------------------
# Full chain: ManualNoteRecord -> EvidenceChunk -> EvidenceDocumentRead
#             -> map_evidence_document
# ---------------------------------------------------------------------------


def test_full_chain_produces_retrieved_evidence_and_citation() -> None:
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    record = _make_record()
    chunk = manual_note_record_to_evidence_chunk(record)
    document = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(document)

    assert isinstance(retrieved, RetrievedEvidence)
    assert isinstance(citation, EvidenceCitation)


def test_full_chain_preserves_source_type() -> None:
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    record = _make_record()
    chunk = manual_note_record_to_evidence_chunk(record)
    document = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(document)

    assert retrieved.source_type == "manual_note"
    assert citation.source_type == "manual_note"


def test_full_chain_preserves_chunk_id_as_source_id() -> None:
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    record = _make_record(id=42)
    chunk = manual_note_record_to_evidence_chunk(record)
    document = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(document)

    assert retrieved.source_id == "manual_note:42:0"
    assert citation.source_id == "manual_note:42:0"


def test_full_chain_preserves_evidence_only() -> None:
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    record = _make_record()
    chunk = manual_note_record_to_evidence_chunk(record)
    document = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(document)

    assert retrieved.evidence_only is True
    assert citation.evidence_only is True


def test_full_chain_retrieval_score_stays_none_in_citation() -> None:
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    record = _make_record()
    chunk = manual_note_record_to_evidence_chunk(record)
    document = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(document)

    # retrieval_score was None on the chunk, so it stays None on the
    # RetrievedEvidence and never appears on the citation.
    assert chunk.retrieval_score is None
    assert retrieved.retrieval_score is None


def test_full_chain_excerpt_flows_through_when_summary_present() -> None:
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    record = _make_record(summary="Short summary.", body="Long body text.")
    chunk = manual_note_record_to_evidence_chunk(record)
    document = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(document)

    assert chunk.excerpt == "Short summary."
    assert document.excerpt == "Short summary."
    assert citation.excerpt == "Short summary."


def test_full_chain_excerpt_generated_from_content_when_summary_absent() -> None:
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    record = _make_record(summary=None, body="Body text for excerpt generation.")
    chunk = manual_note_record_to_evidence_chunk(record)
    document = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(document)

    # chunk.excerpt is None -> chunk_mapper generates from content.
    assert chunk.excerpt is None
    assert document.excerpt == "Body text for excerpt generation."
    assert citation.excerpt == "Body text for excerpt generation."


def test_full_chain_tags_flow_through() -> None:
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    record = _make_record(tags="shooting,defense")
    chunk = manual_note_record_to_evidence_chunk(record)
    document = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(document)

    # tags are preserved on the chunk and document; RetrievedEvidence does
    # not carry a tags field (it is not part of the read contract).
    assert chunk.tags == ["shooting", "defense"]
    assert document.tags == ["shooting", "defense"]


def test_full_chain_confidence_flows_through() -> None:
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    record = _make_record(confidence=0.65)
    chunk = manual_note_record_to_evidence_chunk(record)
    document = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(document)

    assert retrieved.confidence == 0.65


def test_full_chain_published_at_flows_through_as_iso_string() -> None:
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    ts = datetime(2026, 6, 19, 12, 0, 0)
    record = _make_record(updated_at=ts, created_at=datetime(2026, 6, 1, 12, 0, 0))
    chunk = manual_note_record_to_evidence_chunk(record)
    document = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(document)

    # chunk.published_at is datetime -> document.published_at is ISO string.
    assert chunk.published_at == ts
    assert document.published_at == ts.isoformat()
