"""Tests for the EvidenceChunk -> EvidenceDocumentRead mapper (RAG-v2-M1-B).

Covers:
- evidence_chunk_to_document maps fields correctly
- No excerpt → generated from content
- Long content → excerpt truncated
- Mapper does not mutate chunk
- Mapper output evidence_only=True
- Mapper does not call DB / LLM / ranking_engine / simulation_service /
  prediction_calibration
- EvidenceChunk -> EvidenceDocumentRead -> map_evidence_document chain works
- retrieval_score enters RetrievedEvidence but not EvidenceCitation
"""

from __future__ import annotations

import copy
from datetime import datetime

import pytest

from app.schemas.evidence import (
    EvidenceChunk,
    EvidenceCitation,
    EvidenceDocumentRead,
    RetrievedEvidence,
)
from app.services.evidence_chunk_mapper import (
    EXCERPT_MAX_CHARS,
    evidence_chunk_to_document,
)
from app.services.evidence_document_mapper import map_evidence_document


def _make_chunk(**overrides) -> EvidenceChunk:
    defaults = {
        "chunk_id": "manual_note:42:0",
        "source_type": "manual_note",
        "source_id": "42",
        "chunk_index": 0,
        "chunk_count": 3,
        "title": "Scouting summary",
        "content": "Defensive versatility stands out in transition.",
        "entity_type": "prospect",
        "entity_id": 101,
        "prospect_id": 101,
        "prospect_name": "Keaton Sample",
        "team_id": 10,
        "team_abbr": "SAS",
        "year": 2026,
        "url": "https://example.test/note/42",
        "source_name": "DraftMind Manual",
        "publisher": "DraftMind",
        "author": "Analyst",
        "published_at": datetime(2026, 6, 15, 12, 0, 0),
        "confidence": 0.8,
        "retrieval_score": 0.72,
        "relevance_reason": "Explains defensive upside.",
        "tags": ["defense", "transition"],
    }
    defaults.update(overrides)
    return EvidenceChunk(**defaults)


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------


def test_mapper_returns_evidence_document_read() -> None:
    chunk = _make_chunk()
    doc = evidence_chunk_to_document(chunk)
    assert isinstance(doc, EvidenceDocumentRead)


def test_mapper_maps_identity_fields() -> None:
    chunk = _make_chunk()
    doc = evidence_chunk_to_document(chunk)
    assert doc.source_type == "manual_note"
    assert doc.source_id == "manual_note:42:0"  # chunk_id → source_id


def test_mapper_maps_entity_fields() -> None:
    chunk = _make_chunk()
    doc = evidence_chunk_to_document(chunk)
    assert doc.entity_type == "prospect"
    assert doc.entity_id == 101
    assert doc.prospect_id == 101
    assert doc.prospect_name == "Keaton Sample"
    assert doc.team_id == 10
    assert doc.team_abbr == "SAS"
    assert doc.year == 2026


def test_mapper_maps_content_fields() -> None:
    chunk = _make_chunk()
    doc = evidence_chunk_to_document(chunk)
    assert doc.title == "Scouting summary"
    # chunk has no explicit excerpt → generated from content
    assert doc.excerpt == "Defensive versatility stands out in transition."


def test_mapper_maps_source_metadata() -> None:
    chunk = _make_chunk()
    doc = evidence_chunk_to_document(chunk)
    assert doc.url == "https://example.test/note/42"
    assert doc.source_name == "DraftMind Manual"
    assert doc.publisher == "DraftMind"
    assert doc.author == "Analyst"
    assert doc.published_at == "2026-06-15T12:00:00"


def test_mapper_maps_retrieval_metadata() -> None:
    chunk = _make_chunk()
    doc = evidence_chunk_to_document(chunk)
    assert doc.confidence == 0.8
    assert doc.retrieval_score == 0.72
    assert doc.relevance_reason == "Explains defensive upside."


def test_mapper_maps_tags() -> None:
    chunk = _make_chunk()
    doc = evidence_chunk_to_document(chunk)
    assert doc.tags == ["defense", "transition"]


def test_mapper_output_evidence_only_true() -> None:
    chunk = _make_chunk()
    doc = evidence_chunk_to_document(chunk)
    assert doc.evidence_only is True


# ---------------------------------------------------------------------------
# Excerpt generation
# ---------------------------------------------------------------------------


def test_uses_explicit_excerpt_when_provided() -> None:
    chunk = _make_chunk(excerpt="Custom excerpt text.")
    doc = evidence_chunk_to_document(chunk)
    assert doc.excerpt == "Custom excerpt text."


def test_generates_excerpt_from_content_when_none() -> None:
    chunk = _make_chunk(excerpt=None, content="Short content.")
    doc = evidence_chunk_to_document(chunk)
    assert doc.excerpt == "Short content."


def test_truncates_long_content_excerpt() -> None:
    long_content = "A" * (EXCERPT_MAX_CHARS + 200)
    chunk = _make_chunk(excerpt=None, content=long_content)
    doc = evidence_chunk_to_document(chunk)
    assert len(doc.excerpt) == EXCERPT_MAX_CHARS
    assert doc.excerpt.endswith("...")


def test_exact_limit_content_not_truncated() -> None:
    content = "B" * EXCERPT_MAX_CHARS
    chunk = _make_chunk(excerpt=None, content=content)
    doc = evidence_chunk_to_document(chunk)
    assert doc.excerpt == content
    assert not doc.excerpt.endswith("...")


# ---------------------------------------------------------------------------
# No mutation
# ---------------------------------------------------------------------------


def test_mapper_does_not_mutate_chunk() -> None:
    chunk = _make_chunk()
    snapshot = copy.deepcopy(chunk.model_dump())
    evidence_chunk_to_document(chunk)
    assert chunk.model_dump() == snapshot


def test_mapper_does_not_mutate_tags_list() -> None:
    original_tags = ["a", "b"]
    chunk = _make_chunk(tags=original_tags)
    doc = evidence_chunk_to_document(chunk)
    doc.tags.append("c")
    assert original_tags == ["a", "b"]
    assert chunk.tags == ["a", "b"]


def test_mapper_does_not_mutate_content() -> None:
    chunk = _make_chunk(content="Original content.")
    evidence_chunk_to_document(chunk)
    assert chunk.content == "Original content."


# ---------------------------------------------------------------------------
# No DB / LLM / ranking_engine / simulation / prediction calls
# ---------------------------------------------------------------------------


def test_mapper_module_does_not_import_db() -> None:
    import app.services.evidence_chunk_mapper as module
    source = open(module.__file__, encoding="utf-8").read()
    assert "SessionLocal" not in source
    assert "get_db" not in source
    assert "from app.database" not in source
    assert "from app.models" not in source


def test_mapper_module_does_not_import_llm() -> None:
    import app.services.evidence_chunk_mapper as module
    source = open(module.__file__, encoding="utf-8").read()
    assert "import openai" not in source
    assert "import anthropic" not in source
    assert "llm_service" not in source


def test_mapper_module_does_not_import_ranking_engine() -> None:
    """Verify the mapper module does not IMPORT any decision-making modules.

    Uses AST parsing so that legitimate docstring mentions of these module
    names (e.g. "does not invoke ranking_engine") are not flagged.  Only
    actual ``import`` / ``from ... import`` statements are inspected.
    """
    import ast

    import app.services.evidence_chunk_mapper as module

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
            f"mapper module imports forbidden module '{forbidden}'"
        )


# ---------------------------------------------------------------------------
# Full chain: EvidenceChunk -> EvidenceDocumentRead -> map_evidence_document
# ---------------------------------------------------------------------------


def test_full_chain_produces_retrieved_evidence_and_citation() -> None:
    chunk = _make_chunk()
    doc = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(doc)
    assert isinstance(retrieved, RetrievedEvidence)
    assert isinstance(citation, EvidenceCitation)


def test_full_chain_preserves_source_type() -> None:
    chunk = _make_chunk(source_type="news")
    doc = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(doc)
    assert retrieved.source_type == "news"
    assert citation.source_type == "news"
    assert citation.evidence_source_type == "news"


def test_full_chain_preserves_chunk_id_as_source_id() -> None:
    chunk = _make_chunk(chunk_id="news:7:2")
    doc = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(doc)
    assert retrieved.source_id == "news:7:2"
    assert citation.source_id == "news:7:2"


def test_full_chain_preserves_evidence_only() -> None:
    chunk = _make_chunk()
    doc = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(doc)
    assert retrieved.evidence_only is True
    assert citation.evidence_only is True


def test_full_chain_retrieval_score_enters_retrieved_evidence() -> None:
    chunk = _make_chunk(retrieval_score=0.87)
    doc = evidence_chunk_to_document(chunk)
    retrieved, _ = map_evidence_document(doc)
    assert retrieved.retrieval_score == 0.87


def test_full_chain_retrieval_score_not_in_citation() -> None:
    """EvidenceCitation does not have a retrieval_score field — the score
    only lives on RetrievedEvidence for display purposes."""
    chunk = _make_chunk(retrieval_score=0.87)
    doc = evidence_chunk_to_document(chunk)
    _, citation = map_evidence_document(doc)
    assert not hasattr(citation, "retrieval_score") or citation.model_dump().get(
        "retrieval_score"
    ) is None


def test_full_chain_excerpt_flows_through() -> None:
    chunk = _make_chunk(excerpt="Custom excerpt.")
    doc = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(doc)
    assert retrieved.excerpt == "Custom excerpt."
    assert citation.excerpt == "Custom excerpt."


def test_full_chain_tags_flows_through_to_retrieved() -> None:
    """Tags are on EvidenceDocumentRead but not on RetrievedEvidence /
    EvidenceCitation — they are consumed only by the LLM payload whitelist
    in a later stage.  This test confirms tags don't break the chain."""
    chunk = _make_chunk(tags=["defense", "athleticism"])
    doc = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(doc)
    assert retrieved is not None
    assert citation is not None


def test_full_chain_confidence_flows_through() -> None:
    chunk = _make_chunk(confidence=0.9)
    doc = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(doc)
    assert retrieved.confidence == 0.9
    assert citation.confidence == 0.9


def test_full_chain_published_at_flows_through_as_date() -> None:
    chunk = _make_chunk(published_at=datetime(2026, 6, 15, 12, 0, 0))
    doc = evidence_chunk_to_document(chunk)
    retrieved, citation = map_evidence_document(doc)
    assert retrieved.date == "2026-06-15T12:00:00"
    assert citation.date == "2026-06-15T12:00:00"
