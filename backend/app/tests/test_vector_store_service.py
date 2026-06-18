"""RAG-v2-M2-D1: Tests for the in-memory vector store service.

Covers:

- :meth:`InMemoryVectorStore.build_index` — alignment, uniqueness, empty
- :meth:`InMemoryVectorStore.search` — ordering, tie-break, determinism,
  dot product, clamping, top_k bounds, dimension validation
- :meth:`InMemoryVectorStore.get_chunk` — hit / miss / deep copy
- :meth:`InMemoryVectorStore.count` — correctness
- Input immutability (chunks / embeddings not mutated)
- Module purity (no DB / LLM / FAISS / numpy / decision-module imports)
- Safety (no ``retrieval_score`` write-back, no dangerous fields, no
  ranking call)
- Full chain: ``chunk_text -> embed_chunks -> build_index -> search ->
  get_chunk``

Mirrors the test style of :mod:`app.tests.test_embedding_service`.
"""

from __future__ import annotations

import ast
import copy
import math

import pytest

from app.schemas.embedding import EmbeddingVector
from app.schemas.evidence import EvidenceChunk
from app.schemas.vector_store import SemanticRetrievalResult
from app.services import vector_store_service
from app.services.embedding_service import embed_chunks
from app.services.evidence_chunker import chunk_text
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


def _make_embedding(**overrides) -> EmbeddingVector:
    """Factory for a valid :class:`EmbeddingVector` with a small dim."""
    defaults = {
        "chunk_id": "manual_note:1:0",
        "vector": [1.0, 0.0, 0.0, 0.0],
        "model_name": "fake-deterministic-v1",
        "dim": 4,
    }
    defaults.update(overrides)
    return EmbeddingVector(**defaults)


def _build_simple_store() -> InMemoryVectorStore:
    """Build a store with 3 chunks using 4-dim orthogonal-ish vectors."""
    store = InMemoryVectorStore()
    chunks = [
        _make_chunk(chunk_id="c:0", content="alpha"),
        _make_chunk(chunk_id="c:1", content="beta"),
        _make_chunk(chunk_id="c:2", content="gamma"),
    ]
    embeddings = [
        _make_embedding(chunk_id="c:0", vector=[1.0, 0.0, 0.0, 0.0]),
        _make_embedding(chunk_id="c:1", vector=[0.0, 1.0, 0.0, 0.0]),
        _make_embedding(chunk_id="c:2", vector=[0.0, 0.0, 1.0, 0.0]),
    ]
    store.build_index(chunks, embeddings)
    return store


# ---------------------------------------------------------------------------
# build_index — basic behavior
# ---------------------------------------------------------------------------


def test_build_index_creates_index() -> None:
    """build_index populates the store and count() reflects it."""
    store = _build_simple_store()
    assert store.count() == 3


def test_build_index_empty_is_legal() -> None:
    """build_index([], []) produces an empty index, not an error."""
    store = InMemoryVectorStore()
    store.build_index([], [])
    assert store.count() == 0


def test_build_index_replaces_previous_index() -> None:
    """Calling build_index twice replaces, not appends."""
    store = _build_simple_store()
    assert store.count() == 3
    # Rebuild with 1 chunk.
    store.build_index(
        [_make_chunk(chunk_id="solo:0", content="solo")],
        [_make_embedding(chunk_id="solo:0", vector=[1.0, 0.0, 0.0, 0.0])],
    )
    assert store.count() == 1
    assert store.get_chunk("c:0") is None
    assert store.get_chunk("solo:0") is not None


# ---------------------------------------------------------------------------
# build_index — validation errors
# ---------------------------------------------------------------------------


def test_build_index_length_mismatch_raises() -> None:
    """chunks / embeddings length mismatch must raise ValueError."""
    store = InMemoryVectorStore()
    with pytest.raises(ValueError, match="length"):
        store.build_index(
            [_make_chunk(chunk_id="c:0")],
            [],
        )


def test_build_index_chunk_id_mismatch_raises() -> None:
    """chunk.chunk_id != embedding.chunk_id must raise ValueError."""
    store = InMemoryVectorStore()
    with pytest.raises(ValueError, match="chunk_id mismatch"):
        store.build_index(
            [_make_chunk(chunk_id="c:0")],
            [_make_embedding(chunk_id="c:1")],
        )


def test_build_index_duplicate_chunk_id_raises() -> None:
    """Duplicate chunk_id must raise ValueError."""
    store = InMemoryVectorStore()
    with pytest.raises(ValueError, match="duplicate chunk_id"):
        store.build_index(
            [_make_chunk(chunk_id="c:0"), _make_chunk(chunk_id="c:0")],
            [
                _make_embedding(chunk_id="c:0"),
                _make_embedding(chunk_id="c:0"),
            ],
        )


def test_build_index_dim_mismatch_raises() -> None:
    """Embeddings with different dims must raise ValueError."""
    store = InMemoryVectorStore()
    with pytest.raises(ValueError, match="dim mismatch"):
        store.build_index(
            [_make_chunk(chunk_id="c:0"), _make_chunk(chunk_id="c:1")],
            [
                _make_embedding(chunk_id="c:0", dim=4, vector=[1.0, 0.0, 0.0, 0.0]),
                _make_embedding(chunk_id="c:1", dim=3, vector=[1.0, 0.0, 0.0]),
            ],
        )


# ---------------------------------------------------------------------------
# build_index — input immutability
# ---------------------------------------------------------------------------


def test_build_index_does_not_mutate_input_chunks() -> None:
    """Input chunks must be unchanged after build_index."""
    chunks = [_make_chunk(chunk_id="c:0", content="alpha")]
    embeddings = [_make_embedding(chunk_id="c:0")]
    snapshot = copy.deepcopy(chunks)
    store = InMemoryVectorStore()
    store.build_index(chunks, embeddings)
    assert [c.model_dump() for c in chunks] == [c.model_dump() for c in snapshot]


def test_build_index_does_not_mutate_input_embeddings() -> None:
    """Input embeddings must be unchanged after build_index."""
    chunks = [_make_chunk(chunk_id="c:0")]
    embeddings = [_make_embedding(chunk_id="c:0", vector=[1.0, 0.0, 0.0, 0.0])]
    snapshot = copy.deepcopy(embeddings)
    store = InMemoryVectorStore()
    store.build_index(chunks, embeddings)
    assert [e.model_dump() for e in embeddings] == [e.model_dump() for e in snapshot]


# ---------------------------------------------------------------------------
# search — basic behavior
# ---------------------------------------------------------------------------


def test_search_returns_list_of_results() -> None:
    """search returns a list of SemanticRetrievalResult."""
    store = _build_simple_store()
    results = store.search([1.0, 0.0, 0.0, 0.0], top_k=3)
    assert isinstance(results, list)
    for r in results:
        assert isinstance(r, SemanticRetrievalResult)


def test_search_empty_index_returns_empty_list() -> None:
    """search on an empty index returns [], not an error."""
    store = InMemoryVectorStore()
    store.build_index([], [])
    results = store.search([1.0, 0.0, 0.0, 0.0], top_k=5)
    assert results == []


def test_search_top_k_zero_raises() -> None:
    """top_k <= 0 must raise ValueError."""
    store = _build_simple_store()
    with pytest.raises(ValueError, match="top_k"):
        store.search([1.0, 0.0, 0.0, 0.0], top_k=0)


def test_search_top_k_negative_raises() -> None:
    """Negative top_k must raise ValueError."""
    store = _build_simple_store()
    with pytest.raises(ValueError, match="top_k"):
        store.search([1.0, 0.0, 0.0, 0.0], top_k=-1)


def test_search_top_k_greater_than_count_returns_all() -> None:
    """top_k > count returns all indexed chunks."""
    store = _build_simple_store()
    results = store.search([1.0, 0.0, 0.0, 0.0], top_k=100)
    assert len(results) == 3


def test_search_query_dim_mismatch_raises() -> None:
    """Query vector dim != index dim must raise ValueError."""
    store = _build_simple_store()
    with pytest.raises(ValueError, match="dim"):
        store.search([1.0, 0.0, 0.0], top_k=3)  # dim=3, index dim=4


# ---------------------------------------------------------------------------
# search — scoring & ordering
# ---------------------------------------------------------------------------


def test_search_scores_by_dot_product() -> None:
    """retrieval_score equals dot product (L2-normalized → cosine)."""
    store = _build_simple_store()
    # Query exactly matches c:0's vector → score 1.0.
    results = store.search([1.0, 0.0, 0.0, 0.0], top_k=3)
    assert results[0].chunk_id == "c:0"
    assert abs(results[0].retrieval_score - 1.0) < 1e-9


def test_search_scores_non_matching_lower() -> None:
    """Orthogonal vectors produce score 0.0."""
    store = _build_simple_store()
    results = store.search([1.0, 0.0, 0.0, 0.0], top_k=3)
    # c:1 and c:2 are orthogonal to the query → score 0.0.
    assert results[1].retrieval_score == 0.0
    assert results[2].retrieval_score == 0.0


def test_search_clamps_negative_scores_to_zero() -> None:
    """Negative dot products are clamped to 0.0."""
    store = _build_simple_store()
    # Query is opposite of c:0 → dot product -1.0 → clamped to 0.0.
    results = store.search([-1.0, 0.0, 0.0, 0.0], top_k=3)
    for r in results:
        assert r.retrieval_score >= 0.0
    # All scores should be 0.0 (c:0 clamped, c:1/c:2 orthogonal).
    assert all(r.retrieval_score == 0.0 for r in results)


def test_search_orders_by_score_descending() -> None:
    """Results are sorted by retrieval_score descending."""
    store = _build_simple_store()
    # Query has positive components for all three axes.
    results = store.search([0.9, 0.5, 0.1, 0.0], top_k=3)
    scores = [r.retrieval_score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_search_tie_break_by_chunk_id_ascending() -> None:
    """Equal scores are tie-broken by chunk_id ascending."""
    store = _build_simple_store()
    # Query orthogonal to everything → all scores 0.0.
    results = store.search([0.0, 0.0, 0.0, 1.0], top_k=3)
    # All scores are 0.0, so chunk_id order should be ascending.
    chunk_ids = [r.chunk_id for r in results]
    assert chunk_ids == sorted(chunk_ids)
    assert chunk_ids == ["c:0", "c:1", "c:2"]


def test_search_is_deterministic() -> None:
    """Same query produces same results across calls."""
    store = _build_simple_store()
    query = [0.7, 0.3, 0.5, 0.0]
    first = store.search(query, top_k=3)
    second = store.search(query, top_k=3)
    assert [r.model_dump() for r in first] == [r.model_dump() for r in second]


def test_search_respects_top_k_limit() -> None:
    """search returns at most top_k results."""
    store = _build_simple_store()
    results = store.search([1.0, 0.0, 0.0, 0.0], top_k=2)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# get_chunk
# ---------------------------------------------------------------------------


def test_get_chunk_returns_evidence_chunk() -> None:
    """get_chunk returns the indexed EvidenceChunk."""
    store = _build_simple_store()
    chunk = store.get_chunk("c:0")
    assert chunk is not None
    assert isinstance(chunk, EvidenceChunk)
    assert chunk.chunk_id == "c:0"


def test_get_chunk_missing_returns_none() -> None:
    """get_chunk returns None for unknown chunk_id."""
    store = _build_simple_store()
    assert store.get_chunk("nonexistent") is None


def test_get_chunk_returns_deep_copy() -> None:
    """get_chunk returns a deep copy so callers cannot mutate the index."""
    store = _build_simple_store()
    chunk = store.get_chunk("c:0")
    assert chunk is not None
    # Mutate the returned chunk.
    chunk.content = "mutated"
    # The indexed chunk should be unchanged.
    indexed = store.get_chunk("c:0")
    assert indexed is not None
    assert indexed.content == "alpha"


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------


def test_count_returns_zero_for_empty_store() -> None:
    """count() returns 0 for a fresh store."""
    store = InMemoryVectorStore()
    assert store.count() == 0


def test_count_returns_indexed_count() -> None:
    """count() returns the number of indexed chunks."""
    store = _build_simple_store()
    assert store.count() == 3


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


def test_vector_store_service_does_not_import_db() -> None:
    """The vector store must not import any DB session / engine module."""
    source = _read_module_source(vector_store_service)
    imports = _parse_imports(source)
    forbidden = {"sqlalchemy", "database", "SessionLocal", "sessionmaker"}
    assert imports.isdisjoint(forbidden)
    for token in ("get_db", "SessionLocal", "sessionmaker", "create_engine"):
        assert token not in source, (
            f"vector_store_service must not reference DB token '{token}'"
        )


def test_vector_store_service_does_not_import_llm() -> None:
    """The vector store must not import any LLM client module."""
    source = _read_module_source(vector_store_service)
    imports = _parse_imports(source)
    forbidden = {"openai", "anthropic", "llm_service", "llm_client"}
    assert imports.isdisjoint(forbidden)


def test_vector_store_service_does_not_import_external_ml_libs() -> None:
    """The in-memory store must not depend on real ML libraries.

    Only AST-level imports are checked — the module docstring legitimately
    mentions these libraries to document that they are NOT used.
    """
    source = _read_module_source(vector_store_service)
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


def test_vector_store_service_does_not_import_decision_modules() -> None:
    """The vector store must not import ranking / simulation / prediction."""
    source = _read_module_source(vector_store_service)
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


def test_vector_store_service_only_imports_allowed_modules() -> None:
    """The vector store imports only stdlib + app.schemas."""
    source = _read_module_source(vector_store_service)
    imports = _parse_imports(source)
    allowed = {
        "__future__",
        "copy",
        "app",
    }
    extras = imports - allowed
    assert not extras, f"vector_store_service imports unexpected modules: {extras}"


# ---------------------------------------------------------------------------
# Safety — no ranking call, no dangerous fields, no write-back
# ---------------------------------------------------------------------------


def test_search_does_not_call_ranking_engine(monkeypatch) -> None:
    """search must not invoke ranking_engine.rank_prospects."""
    from app.services import ranking_engine

    def _fail(*args, **kwargs):
        raise AssertionError(
            "search must not call ranking_engine.rank_prospects"
        )

    monkeypatch.setattr(ranking_engine, "rank_prospects", _fail)
    store = _build_simple_store()
    store.search([1.0, 0.0, 0.0, 0.0], top_k=3)


def test_build_index_does_not_call_ranking_engine(monkeypatch) -> None:
    """build_index must not invoke ranking_engine.rank_prospects."""
    from app.services import ranking_engine

    def _fail(*args, **kwargs):
        raise AssertionError(
            "build_index must not call ranking_engine.rank_prospects"
        )

    monkeypatch.setattr(ranking_engine, "rank_prospects", _fail)
    store = InMemoryVectorStore()
    store.build_index(
        [_make_chunk(chunk_id="c:0")],
        [_make_embedding(chunk_id="c:0")],
    )


def test_result_does_not_contain_dangerous_fields() -> None:
    """SemanticRetrievalResult must not declare decision-influencing fields."""
    field_names = set(SemanticRetrievalResult.model_fields.keys())
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
    assert dangerous.isdisjoint(field_names)


def test_search_output_does_not_expose_dangerous_fields() -> None:
    """The serialized search output must not contain any dangerous field."""
    store = _build_simple_store()
    results = store.search([1.0, 0.0, 0.0, 0.0], top_k=3)
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
    for r in results:
        payload = r.model_dump()
        for field in dangerous:
            assert field not in payload, (
                f"search output must not expose dangerous field '{field}'"
            )


def test_search_does_not_write_back_retrieval_score_to_chunk() -> None:
    """search must not write retrieval_score back to the indexed EvidenceChunk."""
    store = _build_simple_store()
    # Snapshot the indexed chunk's retrieval_score before search.
    chunk_before = store.get_chunk("c:0")
    assert chunk_before is not None
    score_before = chunk_before.retrieval_score
    # Run a search.
    store.search([1.0, 0.0, 0.0, 0.0], top_k=3)
    # The indexed chunk's retrieval_score should be unchanged.
    chunk_after = store.get_chunk("c:0")
    assert chunk_after is not None
    assert chunk_after.retrieval_score == score_before


# ---------------------------------------------------------------------------
# Full chain: chunk_text -> embed_chunks -> build_index -> search -> get_chunk
# ---------------------------------------------------------------------------


def test_full_chain_chunk_text_to_get_chunk() -> None:
    """The full RAG-v2 chain works end-to-end with fake embeddings."""
    # 1. Chunk a long text.
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

    # 2. Embed the chunks.
    embeddings = embed_chunks(chunks)
    assert len(embeddings) == len(chunks)

    # 3. Build the index.
    store = InMemoryVectorStore()
    store.build_index(chunks, embeddings)
    assert store.count() == len(chunks)

    # 4. Search with a query embedding (embed a query string via a chunk).
    query_chunk = _make_chunk(content="perimeter defender")
    from app.services.embedding_service import embed_chunk
    query_embedding = embed_chunk(query_chunk)
    results = store.search(query_embedding.vector, top_k=3)
    assert len(results) > 0
    assert all(isinstance(r, SemanticRetrievalResult) for r in results)
    assert all(r.retrieval_score >= 0.0 for r in results)

    # 5. get_chunk returns the original chunk for the top result.
    top = results[0]
    retrieved = store.get_chunk(top.chunk_id)
    assert retrieved is not None
    assert retrieved.chunk_id == top.chunk_id
    assert retrieved.evidence_only is True


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
    results = store.search(embeddings[0].vector, top_k=1)
    assert len(results) == 1
    assert results[0].evidence_only is True
    chunk = store.get_chunk(results[0].chunk_id)
    assert chunk is not None
    assert chunk.evidence_only is True


def test_full_chain_retrieval_score_in_result_not_chunk() -> None:
    """retrieval_score lives in SemanticRetrievalResult, not EvidenceChunk."""
    chunks = chunk_text(
        "Test content for score isolation.",
        source_type="manual_note",
        source_id="1",
    )
    embeddings = embed_chunks(chunks)
    store = InMemoryVectorStore()
    store.build_index(chunks, embeddings)
    results = store.search(embeddings[0].vector, top_k=1)
    assert len(results) == 1
    # The result has a retrieval_score.
    assert hasattr(results[0], "retrieval_score")
    # The retrieved chunk's retrieval_score is still None (not written back).
    chunk = store.get_chunk(results[0].chunk_id)
    assert chunk is not None
    assert chunk.retrieval_score is None
