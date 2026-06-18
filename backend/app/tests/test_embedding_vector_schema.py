"""RAG-v2-M2-C1: Tests for the :class:`EmbeddingVector` schema.

Covers schema construction, safety locks (``evidence_only`` Literal,
``extra="forbid"``), dimension constraints, and rejection of dangerous
fields.  Mirrors the test style of
:mod:`app.tests.test_evidence_chunk_schema`.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from app.schemas.embedding import EmbeddingVector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_vector(**overrides) -> EmbeddingVector:
    """Factory for a valid :class:`EmbeddingVector` with overridable fields."""
    defaults = {
        "chunk_id": "manual_note:1:0",
        "vector": [0.1, 0.2, 0.3, 0.4],
        "model_name": "fake-deterministic-v1",
        "dim": 4,
    }
    defaults.update(overrides)
    return EmbeddingVector(**defaults)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_embedding_vector_can_be_created() -> None:
    """EmbeddingVector accepts a valid payload and returns the fields."""
    vector = _make_vector()
    assert vector.chunk_id == "manual_note:1:0"
    assert vector.vector == [0.1, 0.2, 0.3, 0.4]
    assert vector.model_name == "fake-deterministic-v1"
    assert vector.dim == 4


def test_embedding_vector_evidence_only_defaults_to_true() -> None:
    """``evidence_only`` defaults to ``True`` when not provided."""
    vector = _make_vector()
    assert vector.evidence_only is True


def test_embedding_vector_evidence_only_true_explicit() -> None:
    """``evidence_only=True`` is accepted explicitly."""
    vector = _make_vector(evidence_only=True)
    assert vector.evidence_only is True


def test_embedding_vector_rejects_evidence_only_false() -> None:
    """``evidence_only=False`` must be rejected — embeddings are evidence-only."""
    with pytest.raises(ValidationError) as exc_info:
        _make_vector(evidence_only=False)  # type: ignore[arg-type]
    assert "evidence_only" in str(exc_info.value)


# ---------------------------------------------------------------------------
# extra="forbid"
# ---------------------------------------------------------------------------


def test_embedding_vector_extra_forbid_rejects_unknown_field() -> None:
    """Unknown fields must be rejected — no sneaky metadata can slip in."""
    with pytest.raises(ValidationError) as exc_info:
        _make_vector(surprise_field="boom")
    assert "surprise_field" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Dangerous fields
# ---------------------------------------------------------------------------


DANGEROUS_FIELDS = {
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


@pytest.mark.parametrize("field_name", sorted(DANGEROUS_FIELDS))
def test_embedding_vector_rejects_dangerous_field(field_name: str) -> None:
    """Every dangerous field must be rejected by ``extra="forbid"``."""
    with pytest.raises(ValidationError) as exc_info:
        _make_vector(**{field_name: "forbidden"})
    assert field_name in str(exc_info.value)


def test_embedding_vector_model_fields_do_not_include_dangerous_fields() -> None:
    """The schema must not declare any dangerous field."""
    field_names = set(EmbeddingVector.model_fields.keys())
    assert DANGEROUS_FIELDS.isdisjoint(field_names)


# ---------------------------------------------------------------------------
# dim constraint
# ---------------------------------------------------------------------------


def test_embedding_vector_dim_must_be_at_least_one() -> None:
    """``dim < 1`` must be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        _make_vector(dim=0, vector=[])
    assert "dim" in str(exc_info.value)


def test_embedding_vector_dim_negative_rejected() -> None:
    """Negative ``dim`` must be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        _make_vector(dim=-1, vector=[0.1])
    assert "dim" in str(exc_info.value)


# ---------------------------------------------------------------------------
# vector length / emptiness
# ---------------------------------------------------------------------------


def test_embedding_vector_vector_must_not_be_empty() -> None:
    """Empty ``vector`` must be rejected even if ``dim == 0`` were allowed."""
    with pytest.raises(ValidationError) as exc_info:
        _make_vector(dim=1, vector=[])
    assert "vector" in str(exc_info.value)


def test_embedding_vector_vector_length_must_equal_dim() -> None:
    """``len(vector)`` must equal ``dim`` — callers cannot lie about size."""
    with pytest.raises(ValidationError) as exc_info:
        _make_vector(dim=4, vector=[0.1, 0.2, 0.3])
    assert "dim" in str(exc_info.value) or "vector" in str(exc_info.value)


def test_embedding_vector_vector_length_greater_than_dim_rejected() -> None:
    """``len(vector) > dim`` must be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        _make_vector(dim=2, vector=[0.1, 0.2, 0.3])
    assert "dim" in str(exc_info.value) or "vector" in str(exc_info.value)


# ---------------------------------------------------------------------------
# chunk_id / model_name basic constraints
# ---------------------------------------------------------------------------


def test_embedding_vector_chunk_id_required() -> None:
    """``chunk_id`` is required — vectors must trace back to a chunk."""
    with pytest.raises(ValidationError):
        EmbeddingVector(
            vector=[0.1, 0.2],
            model_name="fake-deterministic-v1",
            dim=2,
        )


def test_embedding_vector_model_name_required() -> None:
    """``model_name`` is required — vectors must declare their producer."""
    with pytest.raises(ValidationError):
        EmbeddingVector(
            chunk_id="manual_note:1:0",
            vector=[0.1, 0.2],
            dim=2,
        )


# ---------------------------------------------------------------------------
# Immutability / mutation safety
# ---------------------------------------------------------------------------


def test_embedding_vector_is_mutable_but_input_not_aliased() -> None:
    """Constructing from a list does not alias the caller's list."""
    source = [0.1, 0.2, 0.3, 0.4]
    vector = _make_vector(vector=source)
    # Mutating the schema's vector must not affect the caller's list.
    vector.vector[0] = 99.0
    assert source[0] == 0.1


def test_embedding_vector_deepcopy_roundtrip() -> None:
    """A deep-copied vector retains all fields and safety locks."""
    vector = _make_vector()
    copied = copy.deepcopy(vector)
    assert copied.chunk_id == vector.chunk_id
    assert copied.vector == vector.vector
    assert copied.model_name == vector.model_name
    assert copied.dim == vector.dim
    assert copied.evidence_only is True
