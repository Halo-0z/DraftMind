"""Tests for the EvidenceChunk schema (RAG-v2-M1-B).

Covers:
- Minimal required fields can create a chunk
- content cannot be empty
- chunk_index / chunk_count basic constraints
- chunk_index < chunk_count validator
- confidence range [0, 1]
- retrieval_score range [0, 1]
- evidence_only=False is rejected (Literal[True] lock)
- dangerous fields do not exist / extra forbidden
- tags default does not share mutable list
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.evidence import EvidenceChunk


def _make_chunk(**overrides) -> EvidenceChunk:
    defaults = {
        "chunk_id": "manual_note:42:0",
        "source_type": "manual_note",
        "source_id": "42",
        "chunk_index": 0,
        "chunk_count": 1,
        "content": "Defensive versatility stands out in transition.",
    }
    defaults.update(overrides)
    return EvidenceChunk(**defaults)


# ---------------------------------------------------------------------------
# Minimal creation
# ---------------------------------------------------------------------------


def test_minimal_required_fields_create_chunk() -> None:
    chunk = _make_chunk()
    assert chunk.chunk_id == "manual_note:42:0"
    assert chunk.source_type == "manual_note"
    assert chunk.source_id == "42"
    assert chunk.chunk_index == 0
    assert chunk.chunk_count == 1
    assert chunk.content == "Defensive versatility stands out in transition."
    assert chunk.evidence_only is True


def test_full_fields_create_chunk() -> None:
    chunk = EvidenceChunk(
        chunk_id="news:7:2",
        source_type="news",
        source_id="7",
        chunk_index=2,
        chunk_count=5,
        title="Trade rumor update",
        content="Team is exploring moving up in the draft.",
        excerpt="Trade rumor update",
        entity_type="team",
        entity_id=10,
        prospect_id=101,
        prospect_name="Keaton Sample",
        team_id=10,
        team_abbr="SAS",
        pick_no=5,
        year=2026,
        url="https://example.test/news/7",
        source_name="DraftMind News",
        publisher="DraftMind",
        author="Reporter",
        published_at=datetime(2026, 6, 15, 12, 0, 0),
        confidence=0.85,
        retrieval_score=0.72,
        relevance_reason="Explains team's draft positioning.",
        conflict_note=None,
        tags=["trade", "draft"],
    )
    assert chunk.title == "Trade rumor update"
    assert chunk.tags == ["trade", "draft"]
    assert chunk.confidence == 0.85
    assert chunk.retrieval_score == 0.72


# ---------------------------------------------------------------------------
# content constraints
# ---------------------------------------------------------------------------


def test_content_cannot_be_empty() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(content="")


def test_content_cannot_be_whitespace_only() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(content="   ")


# ---------------------------------------------------------------------------
# chunk_index / chunk_count constraints
# ---------------------------------------------------------------------------


def test_chunk_index_must_be_non_negative() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(chunk_index=-1)


def test_chunk_count_must_be_at_least_one() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(chunk_count=0)


def test_chunk_index_must_be_less_than_chunk_count() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(chunk_index=2, chunk_count=2)


def test_chunk_index_equal_to_count_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(chunk_index=1, chunk_count=1)


def test_chunk_index_less_than_count_accepted() -> None:
    chunk = _make_chunk(chunk_index=0, chunk_count=3)
    assert chunk.chunk_index == 0
    assert chunk.chunk_count == 3


# ---------------------------------------------------------------------------
# confidence range
# ---------------------------------------------------------------------------


def test_confidence_below_zero_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(confidence=-0.01)


def test_confidence_above_one_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(confidence=1.01)


def test_confidence_zero_accepted() -> None:
    chunk = _make_chunk(confidence=0.0)
    assert chunk.confidence == 0.0


def test_confidence_one_accepted() -> None:
    chunk = _make_chunk(confidence=1.0)
    assert chunk.confidence == 1.0


# ---------------------------------------------------------------------------
# retrieval_score range
# ---------------------------------------------------------------------------


def test_retrieval_score_below_zero_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(retrieval_score=-0.01)


def test_retrieval_score_above_one_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(retrieval_score=1.01)


def test_retrieval_score_zero_accepted() -> None:
    chunk = _make_chunk(retrieval_score=0.0)
    assert chunk.retrieval_score == 0.0


def test_retrieval_score_one_accepted() -> None:
    chunk = _make_chunk(retrieval_score=1.0)
    assert chunk.retrieval_score == 1.0


# ---------------------------------------------------------------------------
# evidence_only Literal lock
# ---------------------------------------------------------------------------


def test_evidence_only_false_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(evidence_only=False)


def test_evidence_only_none_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(evidence_only=None)


def test_evidence_only_defaults_to_true() -> None:
    chunk = _make_chunk()
    assert chunk.evidence_only is True


# ---------------------------------------------------------------------------
# dangerous fields / extra forbidden
# ---------------------------------------------------------------------------


DANGEROUS_FIELDS = [
    "replacement_player",
    "recommended_player",
    "new_selected_player",
    "score_adjustment",
    "selection_override",
    "rerank_score",
    "new_score",
    "ranking_weight",
    "final_score_delta",
    "prediction_sort_delta",
    "should_have_selected",
    "better_pick",
]


@pytest.mark.parametrize("field", DANGEROUS_FIELDS)
def test_dangerous_field_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        _make_chunk(**{field: "evil"})


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(unknown_field="oops")


# ---------------------------------------------------------------------------
# tags default does not share mutable list
# ---------------------------------------------------------------------------


def test_tags_default_not_shared() -> None:
    chunk1 = _make_chunk()
    chunk2 = _make_chunk()
    chunk1.tags.append("shared?")
    assert "shared?" not in chunk2.tags
    assert chunk2.tags == []


def test_tags_provided_not_mutated_by_default() -> None:
    original_tags = ["a", "b"]
    chunk = _make_chunk(tags=original_tags)
    chunk.tags.append("c")
    assert original_tags == ["a", "b"]


# ---------------------------------------------------------------------------
# pick_no / year constraints
# ---------------------------------------------------------------------------


def test_pick_no_below_one_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(pick_no=0)


def test_pick_no_above_60_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(pick_no=61)


def test_year_below_1900_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(year=1899)


def test_year_above_2100_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_chunk(year=2101)
