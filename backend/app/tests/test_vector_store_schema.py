"""RAG-v2-M2-D1: Tests for the :class:`SemanticRetrievalResult` schema.

Covers schema construction, safety locks (``evidence_only`` Literal,
``extra="forbid"``), ``retrieval_score >= 0`` constraint, ``chunk_id``
required, and rejection of dangerous fields (including ``embedding`` /
``vector``).  Mirrors the test style of
:mod:`app.tests.test_embedding_vector_schema`.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from app.schemas.vector_store import SemanticRetrievalResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_result(**overrides) -> SemanticRetrievalResult:
    """Factory for a valid :class:`SemanticRetrievalResult`."""
    defaults = {
        "chunk_id": "manual_note:1:0",
        "retrieval_score": 0.87,
    }
    defaults.update(overrides)
    return SemanticRetrievalResult(**defaults)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_result_can_be_created() -> None:
    """SemanticRetrievalResult accepts a valid payload."""
    result = _make_result()
    assert result.chunk_id == "manual_note:1:0"
    assert result.retrieval_score == 0.87


def test_result_evidence_only_defaults_to_true() -> None:
    """``evidence_only`` defaults to ``True`` when not provided."""
    result = _make_result()
    assert result.evidence_only is True


def test_result_evidence_only_true_explicit() -> None:
    """``evidence_only=True`` is accepted explicitly."""
    result = _make_result(evidence_only=True)
    assert result.evidence_only is True


def test_result_rejects_evidence_only_false() -> None:
    """``evidence_only=False`` must be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        _make_result(evidence_only=False)  # type: ignore[arg-type]
    assert "evidence_only" in str(exc_info.value)


# ---------------------------------------------------------------------------
# extra="forbid"
# ---------------------------------------------------------------------------


def test_result_extra_forbid_rejects_unknown_field() -> None:
    """Unknown fields must be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        _make_result(surprise_field="boom")
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
    "embedding",
    "vector",
}


@pytest.mark.parametrize("field_name", sorted(DANGEROUS_FIELDS))
def test_result_rejects_dangerous_field(field_name: str) -> None:
    """Every dangerous field must be rejected by ``extra="forbid"``."""
    with pytest.raises(ValidationError) as exc_info:
        _make_result(**{field_name: "forbidden"})
    assert field_name in str(exc_info.value)


def test_result_model_fields_do_not_include_dangerous_fields() -> None:
    """The schema must not declare any dangerous field."""
    field_names = set(SemanticRetrievalResult.model_fields.keys())
    assert DANGEROUS_FIELDS.isdisjoint(field_names)


# ---------------------------------------------------------------------------
# retrieval_score constraint
# ---------------------------------------------------------------------------


def test_result_retrieval_score_must_be_non_negative() -> None:
    """``retrieval_score < 0`` must be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        _make_result(retrieval_score=-0.01)
    assert "retrieval_score" in str(exc_info.value)


def test_result_retrieval_score_zero_is_allowed() -> None:
    """``retrieval_score == 0`` is allowed (clamped negative similarity)."""
    result = _make_result(retrieval_score=0.0)
    assert result.retrieval_score == 0.0


def test_result_retrieval_score_one_is_allowed() -> None:
    """``retrieval_score == 1.0`` is allowed (perfect match)."""
    result = _make_result(retrieval_score=1.0)
    assert result.retrieval_score == 1.0


# ---------------------------------------------------------------------------
# chunk_id required
# ---------------------------------------------------------------------------


def test_result_chunk_id_required() -> None:
    """``chunk_id`` is required — results must trace back to a chunk."""
    with pytest.raises(ValidationError):
        SemanticRetrievalResult(retrieval_score=0.5)


# ---------------------------------------------------------------------------
# Immutability / mutation safety
# ---------------------------------------------------------------------------


def test_result_deepcopy_roundtrip() -> None:
    """A deep-copied result retains all fields and safety locks."""
    result = _make_result()
    copied = copy.deepcopy(result)
    assert copied.chunk_id == result.chunk_id
    assert copied.retrieval_score == result.retrieval_score
    assert copied.evidence_only is True
