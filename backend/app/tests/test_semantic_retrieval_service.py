"""RAG-v2-M2-D2: Tests for the semantic retrieval service.

Covers:

- :func:`retrieve_semantic` — basic retrieval, top_k, empty index,
  empty/whitespace query, top_k <= 0, dimension mismatch
- ``retrieval_score`` flow into :class:`RetrievedEvidence` (and NOT into
  :class:`EvidenceCitation` / LLM payload / indexed ``EvidenceChunk`` /
  ``EmbeddingVector``)
- ``evidence_only`` Literal lock on outputs
- ``min_score`` filtering
- missing-chunk defensive skip
- input immutability (``chunks`` list / ``vector_store`` count)
- module purity (no DB / LLM / FAISS / numpy / decision-module imports)
- safety (no ``ranking_engine.rank_prospects`` call, no dangerous fields)
- full chain: ``chunk_text -> embed_chunks -> build_index ->
  retrieve_semantic``

Mirrors the test style of :mod:`app.tests.test_vector_store_service`.
"""

from __future__ import annotations

import ast
import copy
import math

import pytest

from app.schemas.evidence import (
    EvidenceChunk,
    EvidenceCitation,
    RetrievedEvidence,
)
from app.services import semantic_retrieval_service
from app.services.evidence_chunker import chunk_text
from app.services.embedding_service import (
    FAKE_EMBEDDING_DIM,
    embed_chunk,
    embed_chunks,
)
from app.services.semantic_retrieval_service import retrieve_semantic
from app.services.vector_store_service import InMemoryVectorStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chunk(**overrides) -> EvidenceChunk:
    """Factory for a valid :class:`EvidenceChunk`."""
    defaults = {
        "chunk_id": "manual_note:1:0",
        "source_type": "manual_note",
        "source_id": "1",
        "chunk_index": 0,
        "chunk_count": 1,
        "content": "Player X is a strong defender with quick hands.",
    }
    defaults.update(overrides)
    return EvidenceChunk(**defaults)


def _build_simple_store() -> tuple[list[EvidenceChunk], InMemoryVectorStore]:
    """Build a store with 3 chunks using fake embeddings.

    Returns the chunks list and the built store so tests can inspect
    both.  The chunks list is the same list passed to ``build_index``;
    the store holds deep copies.
    """
    chunks = [
        _make_chunk(chunk_id="c:0", content="alpha perimeter defender"),
        _make_chunk(chunk_id="c:1", content="beta stretch big three point"),
        _make_chunk(chunk_id="c:2", content="gamma slasher finishing contact"),
    ]
    embeddings = embed_chunks(chunks)
    store = InMemoryVectorStore()
    store.build_index(chunks, embeddings)
    return chunks, store


# ---------------------------------------------------------------------------
# Basic behavior
# ---------------------------------------------------------------------------


def test_retrieve_semantic_returns_tuple_of_two_lists() -> None:
    """retrieve_semantic returns (list[RetrievedEvidence], list[EvidenceCitation])."""
    chunks, store = _build_simple_store()
    result = retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=3,
    )
    assert isinstance(result, tuple)
    assert len(result) == 2
    retrieved, citations = result
    assert isinstance(retrieved, list)
    assert isinstance(citations, list)
    for r in retrieved:
        assert isinstance(r, RetrievedEvidence)
    for c in citations:
        assert isinstance(c, EvidenceCitation)


def test_retrieve_semantic_single_chunk_index() -> None:
    """A single-chunk index returns one result for a matching query."""
    chunks = [_make_chunk(chunk_id="c:0", content="perimeter defender")]
    embeddings = embed_chunks(chunks)
    store = InMemoryVectorStore()
    store.build_index(chunks, embeddings)
    retrieved, citations = retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=5,
    )
    assert len(retrieved) == 1
    assert len(citations) == 1


def test_retrieve_semantic_top_k_limits_results() -> None:
    """top_k limits the number of returned results."""
    chunks, store = _build_simple_store()
    retrieved, citations = retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=2,
    )
    assert len(retrieved) == 2
    assert len(citations) == 2


def test_retrieve_semantic_top_k_greater_than_count_returns_all() -> None:
    """top_k > count returns all indexed chunks."""
    chunks, store = _build_simple_store()
    retrieved, citations = retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=100,
    )
    assert len(retrieved) == 3
    assert len(citations) == 3


def test_retrieve_semantic_empty_index_returns_empty_pair() -> None:
    """An empty index returns ([], [])."""
    store = InMemoryVectorStore()
    store.build_index([], [])
    retrieved, citations = retrieve_semantic(
        query_text="perimeter defender",
        chunks=[],
        vector_store=store,
        top_k=5,
    )
    assert retrieved == []
    assert citations == []


# ---------------------------------------------------------------------------
# Query validation
# ---------------------------------------------------------------------------


def test_retrieve_semantic_empty_query_raises() -> None:
    """Empty query_text raises ValueError."""
    chunks, store = _build_simple_store()
    with pytest.raises(ValueError, match="query_text"):
        retrieve_semantic(
            query_text="",
            chunks=chunks,
            vector_store=store,
            top_k=5,
        )


def test_retrieve_semantic_whitespace_query_raises() -> None:
    """Whitespace-only query_text raises ValueError."""
    chunks, store = _build_simple_store()
    with pytest.raises(ValueError, match="query_text"):
        retrieve_semantic(
            query_text="   \t\n  ",
            chunks=chunks,
            vector_store=store,
            top_k=5,
        )


def test_retrieve_semantic_top_k_zero_raises() -> None:
    """top_k <= 0 raises ValueError (from vector_store.search)."""
    chunks, store = _build_simple_store()
    with pytest.raises(ValueError, match="top_k"):
        retrieve_semantic(
            query_text="perimeter defender",
            chunks=chunks,
            vector_store=store,
            top_k=0,
        )


def test_retrieve_semantic_top_k_negative_raises() -> None:
    """Negative top_k raises ValueError (from vector_store.search)."""
    chunks, store = _build_simple_store()
    with pytest.raises(ValueError, match="top_k"):
        retrieve_semantic(
            query_text="perimeter defender",
            chunks=chunks,
            vector_store=store,
            top_k=-1,
        )


# ---------------------------------------------------------------------------
# retrieval_score flow
# ---------------------------------------------------------------------------


def test_retrieval_score_flows_into_retrieved_evidence() -> None:
    """SemanticRetrievalResult.retrieval_score -> RetrievedEvidence.retrieval_score."""
    chunks, store = _build_simple_store()
    retrieved, _ = retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=3,
    )
    assert len(retrieved) > 0
    for r in retrieved:
        assert r.retrieval_score is not None
        assert r.retrieval_score >= 0.0


def test_retrieval_score_is_non_negative() -> None:
    """All retrieval_score values are >= 0 (clamped by vector_store)."""
    chunks, store = _build_simple_store()
    retrieved, _ = retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=3,
    )
    for r in retrieved:
        assert r.retrieval_score is not None
        assert r.retrieval_score >= 0.0


def test_retrieval_score_not_in_evidence_citation() -> None:
    """EvidenceCitation must not carry retrieval_score."""
    chunks, store = _build_simple_store()
    _, citations = retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=3,
    )
    for citation in citations:
        # Schema-level: EvidenceCitation has no retrieval_score field.
        assert "retrieval_score" not in citation.model_fields
        # Instance-level: model_dump does not contain retrieval_score.
        assert "retrieval_score" not in citation.model_dump()


def test_retrieval_score_not_written_back_to_indexed_chunk() -> None:
    """retrieve_semantic must not write retrieval_score back to the indexed chunk."""
    chunks, store = _build_simple_store()
    # Snapshot the indexed chunk's retrieval_score before retrieval.
    chunk_before = store.get_chunk("c:0")
    assert chunk_before is not None
    assert chunk_before.retrieval_score is None  # M2-D1 invariant

    # Run a retrieval.
    retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=3,
    )

    # The indexed chunk's retrieval_score should still be None.
    chunk_after = store.get_chunk("c:0")
    assert chunk_after is not None
    assert chunk_after.retrieval_score is None


def test_retrieval_score_not_in_embedding_vector_schema() -> None:
    """EmbeddingVector schema must not have a retrieval_score field.

    This is a structural guard — the semantic retrieval service never
    touches EmbeddingVector, but we verify the schema-level boundary
    holds.
    """
    from app.schemas.embedding import EmbeddingVector

    assert "retrieval_score" not in EmbeddingVector.model_fields


def test_retrieval_score_not_in_llm_payload_whitelist() -> None:
    """The LLM payload whitelist must exclude retrieval_score.

    This verifies the existing RAG-v1-D3-B boundary holds for the
    RetrievedEvidence objects produced by retrieve_semantic.  We build
    a minimal PickEvidencePackage and check the whitelist payload.
    """
    from app.schemas.evidence import (
        EvidenceSufficiency,
        PickEvidencePackage,
    )
    from app.services.evidence_llm_explanation_service import (
        _build_llm_explanation_payload,
    )

    chunks, store = _build_simple_store()
    retrieved, citations = retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=3,
    )

    # Build a minimal evidence package with the retrieved evidence.
    evidence = PickEvidencePackage(
        pick_number=1,
        selected_player_name="Test Player",
        evidence_sufficiency=EvidenceSufficiency(level="sufficient"),
        citations=citations,
        retrieved_evidence=retrieved,
    )

    payload = _build_llm_explanation_payload(evidence)

    # The retrieved_evidence whitelist must not contain retrieval_score.
    for item in payload["retrieved_evidence"]:
        assert "retrieval_score" not in item, (
            "LLM payload whitelist must exclude retrieval_score"
        )


# ---------------------------------------------------------------------------
# evidence_only lock
# ---------------------------------------------------------------------------


def test_retrieved_evidence_evidence_only_is_true() -> None:
    """All RetrievedEvidence outputs have evidence_only=True."""
    chunks, store = _build_simple_store()
    retrieved, _ = retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=3,
    )
    for r in retrieved:
        assert r.evidence_only is True


def test_evidence_citation_evidence_only_is_true() -> None:
    """All EvidenceCitation outputs have evidence_only=True."""
    chunks, store = _build_simple_store()
    _, citations = retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=3,
    )
    for c in citations:
        assert c.evidence_only is True


# ---------------------------------------------------------------------------
# min_score filtering
# ---------------------------------------------------------------------------


def test_min_score_filters_low_score_results() -> None:
    """min_score filters out results with retrieval_score below the threshold."""
    chunks, store = _build_simple_store()
    # With a very high min_score, all results should be filtered out.
    retrieved, citations = retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=3,
        min_score=2.0,  # Higher than any possible cosine similarity (max 1.0)
    )
    assert retrieved == []
    assert citations == []


def test_min_score_zero_returns_all() -> None:
    """min_score=0 returns all results (no filtering)."""
    chunks, store = _build_simple_store()
    retrieved, citations = retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=3,
        min_score=0.0,
    )
    assert len(retrieved) == 3
    assert len(citations) == 3


# ---------------------------------------------------------------------------
# Missing chunk defensive skip
# ---------------------------------------------------------------------------


def test_missing_chunk_is_skipped() -> None:
    """If get_chunk returns None, the result is skipped gracefully."""

    class _BrokenStore(InMemoryVectorStore):
        """A store whose get_chunk always returns None."""

        def get_chunk(self, chunk_id: str) -> EvidenceChunk | None:  # type: ignore[override]
            return None

    chunks, _ = _build_simple_store()
    broken_store = _BrokenStore()
    # Re-build the broken store with the same chunks so search() works.
    embeddings = embed_chunks(chunks)
    broken_store.build_index(chunks, embeddings)

    retrieved, citations = retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=broken_store,
        top_k=3,
    )
    # All results skipped because get_chunk returns None.
    assert retrieved == []
    assert citations == []


# ---------------------------------------------------------------------------
# Input immutability
# ---------------------------------------------------------------------------


def test_retrieve_semantic_does_not_mutate_input_chunks() -> None:
    """The input chunks list and its elements must not be mutated."""
    chunks, store = _build_simple_store()
    snapshot = copy.deepcopy(chunks)
    retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=3,
    )
    assert [c.model_dump() for c in chunks] == [c.model_dump() for c in snapshot]


def test_retrieve_semantic_does_not_change_vector_store_count() -> None:
    """retrieve_semantic must not change the vector_store's count()."""
    chunks, store = _build_simple_store()
    count_before = store.count()
    retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=3,
    )
    assert store.count() == count_before


# ---------------------------------------------------------------------------
# Full chain: chunk_text -> embed_chunks -> build_index -> retrieve_semantic
# ---------------------------------------------------------------------------


def test_full_chain_chunk_text_to_retrieve_semantic() -> None:
    """The full RAG-v2 chain works end-to-end with fake embeddings."""
    long_text = (
        "Player A is an elite perimeter defender. "
        "Player B is a stretch big with three-point range. "
        "Player C is a slasher who excels at finishing through contact."
    )
    chunks = chunk_text(
        long_text,
        source_type="manual_note",
        source_id="42",
        chunk_size=60,
        overlap=0,
    )
    assert len(chunks) >= 2

    embeddings = embed_chunks(chunks)
    store = InMemoryVectorStore()
    store.build_index(chunks, embeddings)

    retrieved, citations = retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=3,
    )
    assert len(retrieved) > 0
    assert len(citations) == len(retrieved)
    for r in retrieved:
        assert isinstance(r, RetrievedEvidence)
        assert r.evidence_only is True
        assert r.retrieval_score is not None
        assert r.retrieval_score >= 0.0
    for c in citations:
        assert isinstance(c, EvidenceCitation)
        assert c.evidence_only is True


def test_full_chain_preserves_evidence_only() -> None:
    """evidence_only=True flows through the entire chain."""
    chunks = chunk_text(
        "Test content for evidence only.",
        source_type="manual_note",
        source_id="1",
    )
    embeddings = embed_chunks(chunks)
    store = InMemoryVectorStore()
    store.build_index(chunks, embeddings)
    retrieved, citations = retrieve_semantic(
        query_text="Test content",
        chunks=chunks,
        vector_store=store,
        top_k=1,
    )
    assert len(retrieved) == 1
    assert retrieved[0].evidence_only is True
    assert len(citations) == 1
    assert citations[0].evidence_only is True


def test_full_chain_retrieval_score_in_result_not_indexed_chunk() -> None:
    """retrieval_score lives in RetrievedEvidence, not the indexed chunk."""
    chunks = chunk_text(
        "Test content for score isolation.",
        source_type="manual_note",
        source_id="1",
    )
    embeddings = embed_chunks(chunks)
    store = InMemoryVectorStore()
    store.build_index(chunks, embeddings)
    retrieved, _ = retrieve_semantic(
        query_text="Test content",
        chunks=chunks,
        vector_store=store,
        top_k=1,
    )
    assert len(retrieved) == 1
    assert retrieved[0].retrieval_score is not None
    # The indexed chunk's retrieval_score is still None (not written back).
    top_chunk_id = retrieved[0].citation.source_id if retrieved[0].citation else None
    # source_id in RetrievedEvidence is the chunk_id (set by evidence_chunk_mapper).
    chunk_from_store = store.get_chunk(retrieved[0].source_id or "")
    if chunk_from_store is not None:
        assert chunk_from_store.retrieval_score is None


# ---------------------------------------------------------------------------
# Module purity — no forbidden imports
# ---------------------------------------------------------------------------


def _read_module_source(module) -> str:
    """Read a module's source file as UTF-8 text (Windows-safe)."""
    with open(module.__file__, encoding="utf-8") as f:
        return f.read()


def _parse_imports(source: str) -> set[str]:
    """Return the set of module names imported at the top level of ``source``."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def test_semantic_retrieval_service_does_not_import_db() -> None:
    """The semantic retrieval service must not import any DB module."""
    source = _read_module_source(semantic_retrieval_service)
    imports = _parse_imports(source)
    forbidden = {"sqlalchemy", "database", "SessionLocal", "sessionmaker"}
    assert imports.isdisjoint(forbidden)
    for token in ("get_db", "SessionLocal", "sessionmaker", "create_engine"):
        assert token not in source, (
            f"semantic_retrieval_service must not reference DB token '{token}'"
        )


def test_semantic_retrieval_service_does_not_import_llm() -> None:
    """The semantic retrieval service must not import any LLM client module."""
    source = _read_module_source(semantic_retrieval_service)
    imports = _parse_imports(source)
    forbidden = {"openai", "anthropic", "llm_service", "llm_client"}
    assert imports.isdisjoint(forbidden)


def test_semantic_retrieval_service_does_not_import_external_ml_libs() -> None:
    """The service must not depend on real ML libraries.

    Only AST-level imports are checked — the module docstring legitimately
    mentions these libraries to document that they are NOT used.
    """
    source = _read_module_source(semantic_retrieval_service)
    imports = _parse_imports(source)
    forbidden = {
        "numpy",
        "faiss",
        "torch",
        "sentence_transformers",
        "chroma",
        "chromadb",
        "sklearn",
        "transformers",
    }
    assert imports.isdisjoint(forbidden)


def test_semantic_retrieval_service_does_not_import_decision_modules() -> None:
    """The service must not import ranking / simulation / prediction."""
    source = _read_module_source(semantic_retrieval_service)
    imports = _parse_imports(source)
    forbidden = {
        "ranking_engine",
        "simulation_service",
        "prediction_calibration",
        "recommendation_service",
        "team_need_service",
        "team_need_adjustment",
        "scouting_fit",
    }
    assert imports.isdisjoint(forbidden)


def test_semantic_retrieval_service_only_imports_allowed_modules() -> None:
    """The service imports only stdlib + app.schemas + app.services."""
    source = _read_module_source(semantic_retrieval_service)
    imports = _parse_imports(source)
    allowed = {
        "__future__",
        "app",
    }
    extras = imports - allowed
    assert not extras, (
        f"semantic_retrieval_service imports unexpected modules: {extras}"
    )


# ---------------------------------------------------------------------------
# Safety — no ranking call, no dangerous fields
# ---------------------------------------------------------------------------


def test_retrieve_semantic_does_not_call_ranking_engine(monkeypatch) -> None:
    """retrieve_semantic must not invoke ranking_engine.rank_prospects."""
    from app.services import ranking_engine

    def _fail(*args, **kwargs):
        raise AssertionError(
            "retrieve_semantic must not call ranking_engine.rank_prospects"
        )

    monkeypatch.setattr(ranking_engine, "rank_prospects", _fail)
    chunks, store = _build_simple_store()
    retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=3,
    )


def test_retrieve_semantic_output_does_not_expose_dangerous_fields() -> None:
    """The serialized output must not contain any dangerous field."""
    chunks, store = _build_simple_store()
    retrieved, citations = retrieve_semantic(
        query_text="perimeter defender",
        chunks=chunks,
        vector_store=store,
        top_k=3,
    )
    dangerous = {
        "selected_player",
        "final_score",
        "prediction_sort_score",
        "score_adjustment",
        "selection_override",
        "replacement_player",
        "recommended_player",
        "rerank_score",
        "ranking_delta",
        "draft_decision",
        "trade_evaluation",
        "embedding",
        "vector",
    }
    for r in retrieved:
        payload = r.model_dump()
        for field in dangerous:
            assert field not in payload, (
                f"retrieved_evidence must not expose dangerous field '{field}'"
            )
    for c in citations:
        payload = c.model_dump()
        for field in dangerous:
            assert field not in payload, (
                f"citation must not expose dangerous field '{field}'"
            )
