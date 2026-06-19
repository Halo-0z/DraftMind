"""RAG-v2-M2-C1: Tests for the fake deterministic embedding service.

Covers:

- :func:`embed_chunk` / :func:`embed_chunks` return values
- Determinism (same content -> same vector)
- Different content -> different vectors
- L2 normalization (norm ~= 1.0)
- Fixed dimension (384) and model name (``fake-deterministic-v1``)
- Input immutability
- Module purity (no DB / LLM / ranking / external ML library imports)
- Safety (no ``retrieval_score``, no dangerous fields, no ranking call)

Mirrors the test style of :mod:`app.tests.test_evidence_chunker`.
"""

from __future__ import annotations

import ast
import copy
import math
import sys

import pytest

from app.schemas.embedding import EmbeddingVector
from app.schemas.evidence import EvidenceChunk
from app.services import embedding_service
from app.services.embedding_service import (
    FAKE_EMBEDDING_DIM,
    FAKE_MODEL_NAME,
    embed_chunk,
    embed_chunks,
    embed_query,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chunk(**overrides) -> EvidenceChunk:
    """Factory for a valid :class:`EvidenceChunk` with overridable fields."""
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


# ---------------------------------------------------------------------------
# embed_chunk — basic behavior
# ---------------------------------------------------------------------------


def test_embed_chunk_returns_embedding_vector() -> None:
    """``embed_chunk`` returns an :class:`EmbeddingVector` instance."""
    chunk = _make_chunk()
    result = embed_chunk(chunk)
    assert isinstance(result, EmbeddingVector)


def test_embed_chunk_chunk_id_back_references_input() -> None:
    """The returned vector's ``chunk_id`` matches the input chunk's."""
    chunk = _make_chunk(chunk_id="manual_note:42:3")
    result = embed_chunk(chunk)
    assert result.chunk_id == "manual_note:42:3"


def test_embed_chunk_model_name_is_fake_deterministic_v1() -> None:
    """The fake model name is recorded in the output."""
    chunk = _make_chunk()
    result = embed_chunk(chunk)
    assert result.model_name == FAKE_MODEL_NAME
    assert result.model_name == "fake-deterministic-v1"


def test_embed_chunk_dim_is_384() -> None:
    """The vector dimension matches the contract (384)."""
    chunk = _make_chunk()
    result = embed_chunk(chunk)
    assert result.dim == FAKE_EMBEDDING_DIM
    assert result.dim == 384


def test_embed_chunk_vector_length_equals_dim() -> None:
    """``len(vector) == dim`` — the schema enforces this; verify the service."""
    chunk = _make_chunk()
    result = embed_chunk(chunk)
    assert len(result.vector) == result.dim == 384


def test_embed_chunk_vector_l2_norm_approximately_one() -> None:
    """The fake embedding is L2-normalized so cosine similarity is dot product."""
    chunk = _make_chunk()
    result = embed_chunk(chunk)
    norm = math.sqrt(sum(v * v for v in result.vector))
    assert abs(norm - 1.0) < 1e-9


def test_embed_chunk_evidence_only_is_true() -> None:
    """Every embedding carries the ``evidence_only=True`` safety lock."""
    chunk = _make_chunk()
    result = embed_chunk(chunk)
    assert result.evidence_only is True


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_same_chunk_produces_same_vector() -> None:
    """Embedding the same chunk twice must yield identical vectors."""
    chunk = _make_chunk()
    first = embed_chunk(chunk)
    second = embed_chunk(chunk)
    assert first.vector == second.vector
    assert first.chunk_id == second.chunk_id


def test_same_content_different_chunk_id_produces_same_vector() -> None:
    """The vector depends only on ``content``; ``chunk_id`` is metadata."""
    chunk_a = _make_chunk(chunk_id="manual_note:1:0", content="Same content here.")
    chunk_b = _make_chunk(chunk_id="manual_note:2:0", content="Same content here.")
    result_a = embed_chunk(chunk_a)
    result_b = embed_chunk(chunk_b)
    assert result_a.vector == result_b.vector
    # But the chunk_id back-references differ correctly.
    assert result_a.chunk_id == "manual_note:1:0"
    assert result_b.chunk_id == "manual_note:2:0"


def test_different_content_produces_different_vectors() -> None:
    """Different content must produce different vectors (best effort)."""
    chunk_a = _make_chunk(content="Player A is a strong defender.")
    chunk_b = _make_chunk(content="Player B is a fast breakaway scorer.")
    result_a = embed_chunk(chunk_a)
    result_b = embed_chunk(chunk_b)
    assert result_a.vector != result_b.vector


def test_deterministic_across_calls_and_instances() -> None:
    """Determinism holds across many calls (no hidden state)."""
    chunk = _make_chunk(content="Stability check content.")
    vectors = [embed_chunk(chunk).vector for _ in range(10)]
    for v in vectors[1:]:
        assert v == vectors[0]


# ---------------------------------------------------------------------------
# embed_chunks — batch behavior
# ---------------------------------------------------------------------------


def test_embed_chunks_preserves_input_order() -> None:
    """Batch embedding preserves the input order in the output list."""
    chunks = [
        _make_chunk(chunk_id=f"manual_note:{i}:0", content=f"Content number {i}.")
        for i in range(5)
    ]
    results = embed_chunks(chunks)
    assert [r.chunk_id for r in results] == [c.chunk_id for c in chunks]


def test_embed_chunks_output_count_equals_input_count() -> None:
    """Batch embedding returns exactly one vector per input chunk."""
    chunks = [
        _make_chunk(chunk_id=f"manual_note:{i}:0", content=f"Content {i}.")
        for i in range(7)
    ]
    results = embed_chunks(chunks)
    assert len(results) == len(chunks) == 7


def test_embed_chunks_empty_list_returns_empty_list() -> None:
    """An empty input yields an empty output (no errors, no phantom vectors)."""
    results = embed_chunks([])
    assert results == []


def test_embed_chunks_each_result_is_embedding_vector() -> None:
    """Every batch output element is an :class:`EmbeddingVector`."""
    chunks = [_make_chunk(content="Chunk A."), _make_chunk(content="Chunk B.")]
    results = embed_chunks(chunks)
    for r in results:
        assert isinstance(r, EmbeddingVector)


def test_embed_chunks_matches_individual_calls() -> None:
    """Batch embedding equals per-chunk embedding (no batching divergence)."""
    chunks = [
        _make_chunk(chunk_id=f"manual_note:{i}:0", content=f"Content {i}.")
        for i in range(3)
    ]
    batch_results = embed_chunks(chunks)
    individual_results = [embed_chunk(c) for c in chunks]
    for br, ir in zip(batch_results, individual_results):
        assert br.vector == ir.vector
        assert br.chunk_id == ir.chunk_id


# ---------------------------------------------------------------------------
# Input immutability
# ---------------------------------------------------------------------------


def test_embed_chunk_does_not_mutate_input_chunk() -> None:
    """The input :class:`EvidenceChunk` must be unchanged after embedding."""
    chunk = _make_chunk()
    snapshot = copy.deepcopy(chunk)
    embed_chunk(chunk)
    assert chunk.model_dump() == snapshot.model_dump()


def test_embed_chunk_does_not_mutate_input_tags() -> None:
    """Input ``tags`` list must not be mutated."""
    tags = ["defense", "athletic"]
    chunk = _make_chunk(tags=tags)
    embed_chunk(chunk)
    assert tags == ["defense", "athletic"]


def test_embed_chunks_does_not_mutate_input_list() -> None:
    """The input list of chunks must not be mutated by batch embedding."""
    chunks = [_make_chunk(content="A."), _make_chunk(content="B.")]
    snapshot = [copy.deepcopy(c) for c in chunks]
    embed_chunks(chunks)
    for original, snap in zip(chunks, snapshot):
        assert original.model_dump() == snap.model_dump()


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


def test_embedding_service_module_does_not_import_db() -> None:
    """The embedding service must not import any DB session / engine module."""
    source = _read_module_source(embedding_service)
    imports = _parse_imports(source)
    forbidden = {"sqlalchemy", "database", "SessionLocal", "sessionmaker"}
    assert imports.isdisjoint(forbidden)
    # Also check the source text for common DB patterns.
    for token in ("get_db", "SessionLocal", "sessionmaker", "create_engine"):
        assert token not in source, (
            f"embedding_service must not reference DB token '{token}'"
        )


def test_embedding_service_module_does_not_import_llm() -> None:
    """The embedding service must not import any LLM client module."""
    source = _read_module_source(embedding_service)
    imports = _parse_imports(source)
    forbidden = {"openai", "anthropic", "llm_service", "llm_client"}
    assert imports.isdisjoint(forbidden)


def test_embedding_service_module_does_not_import_external_ml_libs() -> None:
    """The fake embedding must not depend on real ML libraries.

    Only AST-level imports are checked — the module docstring legitimately
    mentions these libraries to document that they are NOT used, so text
    matching would produce false positives.
    """
    source = _read_module_source(embedding_service)
    imports = _parse_imports(source)
    forbidden = {
        "sentence_transformers",
        "torch",
        "faiss",
        "chromadb",
        "numpy",
        "sklearn",
        "transformers",
    }
    assert imports.isdisjoint(forbidden)


def test_embedding_service_module_does_not_import_decision_modules() -> None:
    """The embedding service must not import ranking / simulation / prediction."""
    source = _read_module_source(embedding_service)
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


def test_embedding_service_module_only_imports_allowed_modules() -> None:
    """The embedding service imports only stdlib + app.schemas."""
    source = _read_module_source(embedding_service)
    imports = _parse_imports(source)
    # Allowed: stdlib (hashlib, math, struct, __future__) + app.schemas.*
    allowed = {
        "__future__",
        "hashlib",
        "math",
        "struct",
        "app",
    }
    # Every imported top-level name must be in ``allowed`` or start with
    # ``app.`` (already covered by ``app``).
    extras = imports - allowed
    assert not extras, f"embedding_service imports unexpected modules: {extras}"


# ---------------------------------------------------------------------------
# Safety — no ranking call, no dangerous fields
# ---------------------------------------------------------------------------


def test_embed_chunk_does_not_call_ranking_engine(monkeypatch) -> None:
    """``embed_chunk`` must not invoke ``ranking_engine.rank_prospects``."""
    # Import the real ranking_engine to monkeypatch its public function.
    from app.services import ranking_engine

    def _fail(*args, **kwargs):
        raise AssertionError(
            "embed_chunk must not call ranking_engine.rank_prospects"
        )

    monkeypatch.setattr(ranking_engine, "rank_prospects", _fail)
    chunk = _make_chunk()
    # If embed_chunk secretly calls rank_prospects, the test fails.
    embed_chunk(chunk)


def test_embed_chunks_does_not_call_ranking_engine(monkeypatch) -> None:
    """``embed_chunks`` must not invoke ``ranking_engine.rank_prospects``."""
    from app.services import ranking_engine

    def _fail(*args, **kwargs):
        raise AssertionError(
            "embed_chunks must not call ranking_engine.rank_prospects"
        )

    monkeypatch.setattr(ranking_engine, "rank_prospects", _fail)
    chunks = [_make_chunk(content="A."), _make_chunk(content="B.")]
    embed_chunks(chunks)


def test_embedding_vector_does_not_contain_retrieval_score() -> None:
    """``EmbeddingVector`` must not declare a ``retrieval_score`` field."""
    field_names = set(EmbeddingVector.model_fields.keys())
    assert "retrieval_score" not in field_names


def test_embedding_vector_does_not_contain_dangerous_fields() -> None:
    """``EmbeddingVector`` must not declare any decision-influencing field."""
    field_names = set(EmbeddingVector.model_fields.keys())
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
    }
    assert dangerous.isdisjoint(field_names)


def test_embed_chunk_output_does_not_expose_dangerous_fields() -> None:
    """The serialized output must not contain any dangerous field."""
    chunk = _make_chunk()
    result = embed_chunk(chunk)
    payload = result.model_dump()
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
        "retrieval_score",
    }
    for field in dangerous:
        assert field not in payload, (
            f"embed_chunk output must not expose dangerous field '{field}'"
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_embed_chunk_with_unicode_content() -> None:
    """Unicode content (Chinese, emoji) must embed without error."""
    chunk = _make_chunk(content="球员 X 是一名出色的防守者。🏀")
    result = embed_chunk(chunk)
    assert len(result.vector) == 384
    # Still deterministic.
    result2 = embed_chunk(chunk)
    assert result.vector == result2.vector


def test_embed_chunk_with_long_content() -> None:
    """Long content must embed without error and remain deterministic."""
    long_content = "This is a sentence. " * 500
    chunk = _make_chunk(content=long_content)
    result = embed_chunk(chunk)
    assert len(result.vector) == 384
    result2 = embed_chunk(chunk)
    assert result.vector == result2.vector


def test_embed_chunk_with_minimal_content() -> None:
    """A single-character content must embed without error."""
    chunk = _make_chunk(content="A")
    result = embed_chunk(chunk)
    assert len(result.vector) == 384
    # L2 norm still ~1.0.
    norm = math.sqrt(sum(v * v for v in result.vector))
    assert abs(norm - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_fake_embedding_dim_constant_is_384() -> None:
    """The fake embedding dimension is locked to 384 (matches MiniLM)."""
    assert FAKE_EMBEDDING_DIM == 384


def test_fake_model_name_constant_is_fake_deterministic_v1() -> None:
    """The fake model name is locked to ``fake-deterministic-v1``."""
    assert FAKE_MODEL_NAME == "fake-deterministic-v1"


def test_fake_embedding_dim_matches_real_minilm_dim() -> None:
    """The fake dim is chosen so M2-C2 can swap in ``all-MiniLM-L6-v2``."""
    # all-MiniLM-L6-v2 produces 384-dim vectors.
    assert FAKE_EMBEDDING_DIM == 384


# ---------------------------------------------------------------------------
# RAG-v2-M2-D2: embed_query
# ---------------------------------------------------------------------------


def test_embed_query_returns_list_of_floats() -> None:
    """embed_query returns a list[float] (not EmbeddingVector)."""
    vector = embed_query("perimeter defender")
    assert isinstance(vector, list)
    for v in vector:
        assert isinstance(v, float)


def test_embed_query_length_equals_fake_embedding_dim() -> None:
    """The returned vector has length FAKE_EMBEDDING_DIM."""
    vector = embed_query("perimeter defender")
    assert len(vector) == FAKE_EMBEDDING_DIM


def test_embed_query_l2_norm_approximately_one() -> None:
    """The returned vector is L2-normalized (norm ~= 1.0)."""
    vector = embed_query("perimeter defender")
    norm = math.sqrt(sum(v * v for v in vector))
    assert abs(norm - 1.0) < 1e-9


def test_embed_query_is_deterministic() -> None:
    """The same query produces the same vector across calls."""
    first = embed_query("perimeter defender")
    second = embed_query("perimeter defender")
    assert first == second


def test_embed_query_different_queries_produce_different_vectors() -> None:
    """Different queries produce different vectors."""
    first = embed_query("perimeter defender")
    second = embed_query("stretch big three point")
    assert first != second


def test_embed_query_empty_raises_value_error() -> None:
    """Empty query_text raises ValueError."""
    with pytest.raises(ValueError, match="query_text"):
        embed_query("")


def test_embed_query_whitespace_only_raises_value_error() -> None:
    """Whitespace-only query_text raises ValueError."""
    with pytest.raises(ValueError, match="query_text"):
        embed_query("   \t\n  ")


def test_embed_query_matches_embed_chunk_with_same_content() -> None:
    """embed_query(text) == embed_chunk(chunk_with_content=text).vector.

    Verifies that embed_query reuses the same _fake_embed algorithm as
    embed_chunk — they must produce identical vectors for the same text.
    """
    query_text = "perimeter defender"
    query_vector = embed_query(query_text)

    chunk = _make_chunk(content=query_text)
    chunk_vector = embed_chunk(chunk).vector

    assert query_vector == chunk_vector


def test_embed_query_does_not_call_ranking_engine(monkeypatch) -> None:
    """embed_query must not invoke ranking_engine.rank_prospects."""
    from app.services import ranking_engine

    def _fail(*args, **kwargs):
        raise AssertionError(
            "embed_query must not call ranking_engine.rank_prospects"
        )

    monkeypatch.setattr(ranking_engine, "rank_prospects", _fail)
    embed_query("perimeter defender")
