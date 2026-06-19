"""Tests for the LLM explanation payload whitelist (RAG-v1-D3-B).

These tests lock down the ``_build_llm_explanation_payload`` helper and the
``_call_llm`` integration so that:

1. The LLM user message is a whitelist payload, NOT ``evidence.model_dump()``.
2. The payload includes ``retrieved_evidence`` (manual_note lives here).
3. The payload includes ``manual_note`` entries.
4. The payload includes ``citations``.
5. The payload does NOT include ``candidate_board`` / ``alternatives`` /
   ``simulation`` / ``replacement_player`` / ``score_adjustment`` /
   ``selection_override``.
6. Long excerpts are truncated to ``LLM_EXCERPT_MAX_CHARS``.
7. The original ``PickEvidencePackage`` is not mutated.
8. Dangerous LLM output still falls back to mock.
9. Invalid JSON still falls back to mock.
10. Provider error / timeout still falls back to mock.

The new payload whitelist is defense in depth: even if the schema later grows
dangerous fields, the whitelist will not accidentally include them.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from app.schemas.evidence import (
    ConflictEvidence,
    EvidenceCitation,
    EvidenceSufficiency,
    MarketEvidence,
    PickEvidencePackage,
    PickExplanation,
    RankingEvidence,
    RetrievedEvidence,
    RiskEvidence,
    TeamFitEvidence,
)
from app.services.evidence_explanation_service import build_mock_pick_explanation
from app.services.evidence_llm_explanation_service import (
    LLM_EXCERPT_MAX_CHARS,
    _build_llm_explanation_payload,
    _truncate_excerpt,
    build_llm_pick_explanation,
)


# ---------------------------------------------------------------------------
# Fake LLM client
# ---------------------------------------------------------------------------


class FakeLLMClient:
    """Minimal fake LLM client that records calls for inspection."""

    def __init__(self, response: str | Exception):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _full_evidence() -> PickEvidencePackage:
    return PickEvidencePackage(
        pick_number=5,
        team_abbr="LAC",
        selected_player_id=101,
        selected_player_name="Keaton Sample",
        ranking_evidence=RankingEvidence(
            final_score=82.4,
            prediction_sort_score=84.1,
            rank_in_available_pool=1,
        ),
        team_fit_evidence=TeamFitEvidence(
            team_needs=["wing defense"],
            matched_needs=["wing defense"],
            fit_strength="moderate",
        ),
        market_evidence=MarketEvidence(
            has_market_reference=True,
            market_expected_pick=7,
            market_range_min=5,
            market_range_max=10,
            market_pick_delta=-2,
            market_alignment_label="接近",
            market_alignment_notes=["市场预计约第 7 顺位。"],
            market_sources=["manual_projection"],
        ),
        risk_evidence=RiskEvidence(
            diagnostics_warnings=["Low-confidence imported stats."],
            overall_risk_level="moderate",
        ),
        conflict_evidence=[
            ConflictEvidence(
                type="market_model_delta",
                severity="low",
                description="DraftMind selected two picks earlier than market.",
            )
        ],
        evidence_sufficiency=EvidenceSufficiency(level="strong"),
        citations=[
            EvidenceCitation(
                source_type="projection",
                source_id="manual_projection:101",
                title="Manual Projection 101",
                url="https://example.com/projection/101",
            ),
            EvidenceCitation(
                source_type="manual_note",
                source_id="note:42",
                title="Scouting note",
                evidence_source_type="manual_note",
                excerpt="Defensive versatility stands out.",
            ),
        ],
        retrieved_evidence=[
            RetrievedEvidence(
                source_type="manual_note",
                source_id="note:42",
                title="Scouting summary",
                excerpt="Defensive versatility stands out.",
                relevance_reason="Matches team need.",
                evidence_only=True,
            ),
            RetrievedEvidence(
                source_type="projection",
                source_id="manual_projection:101",
                excerpt="Projected as a late-lottery pick.",
                relevance_reason="Market reference for slot 5.",
            ),
        ],
    )


def _valid_llm_json(evidence: PickEvidencePackage | None = None) -> str:
    if evidence is None:
        evidence = _full_evidence()
    return build_mock_pick_explanation(evidence).model_dump_json()


# ---------------------------------------------------------------------------
# 1-3. Payload includes retrieved_evidence / manual_note / citations
# ---------------------------------------------------------------------------


def test_payload_includes_retrieved_evidence() -> None:
    evidence = _full_evidence()
    payload = _build_llm_explanation_payload(evidence)
    assert "retrieved_evidence" in payload
    assert isinstance(payload["retrieved_evidence"], list)
    assert len(payload["retrieved_evidence"]) == len(evidence.retrieved_evidence)


def test_payload_includes_manual_note() -> None:
    evidence = _full_evidence()
    payload = _build_llm_explanation_payload(evidence)
    manual_notes = [
        r for r in payload["retrieved_evidence"] if r["source_type"] == "manual_note"
    ]
    assert manual_notes, "Payload must include manual_note retrieved_evidence"
    for note in manual_notes:
        assert note["evidence_only"] is True


def test_payload_includes_manual_note_in_citations() -> None:
    evidence = _full_evidence()
    payload = _build_llm_explanation_payload(evidence)
    manual_citations = [
        c for c in payload["citations"] if c.get("evidence_source_type") == "manual_note"
    ]
    assert manual_citations, "Payload must include manual_note citations"


def test_payload_includes_citations() -> None:
    evidence = _full_evidence()
    payload = _build_llm_explanation_payload(evidence)
    assert "citations" in payload
    assert isinstance(payload["citations"], list)
    assert len(payload["citations"]) == len(evidence.citations)


def test_llm_user_message_contains_retrieved_evidence() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(_valid_llm_json(evidence))
    build_llm_pick_explanation(evidence, llm_client=client)
    user_msg = client.calls[0]["messages"][-1]["content"]
    parsed = json.loads(user_msg)
    assert "retrieved_evidence" in parsed
    assert any(r["source_type"] == "manual_note" for r in parsed["retrieved_evidence"])


def test_llm_user_message_contains_citations() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(_valid_llm_json(evidence))
    build_llm_pick_explanation(evidence, llm_client=client)
    user_msg = client.calls[0]["messages"][-1]["content"]
    parsed = json.loads(user_msg)
    assert "citations" in parsed
    assert len(parsed["citations"]) == len(evidence.citations)


# ---------------------------------------------------------------------------
# 4-9. Payload excludes dangerous fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "candidate_board",
        "alternatives",
        "simulation",
        "replacement_player",
        "score_adjustment",
        "selection_override",
        "recommended_player",
        "new_selected_player",
        "rerank_score",
        "new_score",
        "ranking_weight",
        "final_score_delta",
        "prediction_sort_delta",
        "should_have_selected",
        "better_pick",
    ],
)
def test_payload_does_not_contain_dangerous_field(field: str) -> None:
    evidence = _full_evidence()
    payload = _build_llm_explanation_payload(evidence)
    assert field not in payload, f"Payload must not contain '{field}'"


def test_payload_does_not_contain_nested_citation_in_retrieved_evidence() -> None:
    """The nested ``citation`` object inside RetrievedEvidence is redundant
    with the top-level ``citations`` list and must be excluded."""
    evidence = _full_evidence()
    payload = _build_llm_explanation_payload(evidence)
    for item in payload["retrieved_evidence"]:
        assert "citation" not in item


def test_payload_does_not_contain_internal_metadata_in_retrieved_evidence() -> None:
    """Internal metadata fields must not leak into the LLM payload."""
    evidence = _full_evidence()
    payload = _build_llm_explanation_payload(evidence)
    for item in payload["retrieved_evidence"]:
        assert "entity_id" not in item
        assert "retrieval_score" not in item
        assert "freshness_days" not in item
        assert "conflict_note" not in item


def test_payload_does_not_contain_internal_metadata_in_citations() -> None:
    """Internal metadata fields must not leak into the LLM payload."""
    evidence = _full_evidence()
    payload = _build_llm_explanation_payload(evidence)
    for citation in payload["citations"]:
        assert "publisher" not in citation
        assert "retrieved_at" not in citation
        assert "freshness_days" not in citation
        assert "entity_id" not in citation


def test_llm_user_message_does_not_contain_dangerous_fields() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(_valid_llm_json(evidence))
    build_llm_pick_explanation(evidence, llm_client=client)
    user_msg = client.calls[0]["messages"][-1]["content"]
    parsed = json.loads(user_msg)
    for field in (
        "candidate_board",
        "alternatives",
        "simulation",
        "replacement_player",
        "score_adjustment",
        "selection_override",
    ):
        assert field not in parsed, f"LLM user message must not contain '{field}'"


# ---------------------------------------------------------------------------
# 10. Long excerpt is truncated
# ---------------------------------------------------------------------------


def test_truncate_excerpt_short_unchanged() -> None:
    assert _truncate_excerpt("short text") == "short text"


def test_truncate_excerpt_none_unchanged() -> None:
    assert _truncate_excerpt(None) is None


def test_truncate_excerpt_exact_limit_unchanged() -> None:
    text = "x" * LLM_EXCERPT_MAX_CHARS
    assert _truncate_excerpt(text) == text


def test_truncate_excerpt_long_is_truncated() -> None:
    text = "x" * (LLM_EXCERPT_MAX_CHARS + 100)
    result = _truncate_excerpt(text)
    assert result is not None
    assert len(result) == LLM_EXCERPT_MAX_CHARS
    assert result.endswith("...")


def test_payload_truncates_long_retrieved_evidence_excerpt() -> None:
    long_excerpt = "A" * (LLM_EXCERPT_MAX_CHARS + 200)
    evidence = _full_evidence()
    evidence.retrieved_evidence[0].excerpt = long_excerpt
    payload = _build_llm_explanation_payload(evidence)
    truncated = payload["retrieved_evidence"][0]["excerpt"]
    assert len(truncated) == LLM_EXCERPT_MAX_CHARS
    assert truncated.endswith("...")


def test_payload_truncates_long_citation_excerpt() -> None:
    long_excerpt = "B" * (LLM_EXCERPT_MAX_CHARS + 200)
    evidence = _full_evidence()
    evidence.citations[1].excerpt = long_excerpt
    payload = _build_llm_explanation_payload(evidence)
    truncated = payload["citations"][1]["excerpt"]
    assert len(truncated) == LLM_EXCERPT_MAX_CHARS
    assert truncated.endswith("...")


def test_llm_user_message_truncates_long_excerpt() -> None:
    long_excerpt = "C" * (LLM_EXCERPT_MAX_CHARS + 500)
    evidence = _full_evidence()
    evidence.retrieved_evidence[0].excerpt = long_excerpt
    client = FakeLLMClient(_valid_llm_json(evidence))
    build_llm_pick_explanation(evidence, llm_client=client)
    user_msg = client.calls[0]["messages"][-1]["content"]
    parsed = json.loads(user_msg)
    excerpt = parsed["retrieved_evidence"][0]["excerpt"]
    assert len(excerpt) == LLM_EXCERPT_MAX_CHARS
    assert excerpt.endswith("...")


# ---------------------------------------------------------------------------
# 11. Original PickEvidencePackage is not mutated
# ---------------------------------------------------------------------------


def test_build_payload_does_not_mutate_input() -> None:
    evidence = _full_evidence()
    snapshot = copy.deepcopy(evidence.model_dump())
    _build_llm_explanation_payload(evidence)
    assert evidence.model_dump() == snapshot


def test_build_llm_pick_explanation_does_not_mutate_input() -> None:
    evidence = _full_evidence()
    snapshot = copy.deepcopy(evidence.model_dump())
    client = FakeLLMClient(_valid_llm_json(evidence))
    build_llm_pick_explanation(evidence, llm_client=client)
    assert evidence.model_dump() == snapshot


def test_truncation_does_not_mutate_input_excerpt() -> None:
    long_excerpt = "D" * (LLM_EXCERPT_MAX_CHARS + 100)
    evidence = _full_evidence()
    evidence.retrieved_evidence[0].excerpt = long_excerpt
    original_excerpt = evidence.retrieved_evidence[0].excerpt
    _build_llm_explanation_payload(evidence)
    assert evidence.retrieved_evidence[0].excerpt == original_excerpt


# ---------------------------------------------------------------------------
# 12. Dangerous LLM output still falls back
# ---------------------------------------------------------------------------


def test_dangerous_llm_output_falls_back_to_mock() -> None:
    evidence = _full_evidence()
    data = json.loads(_valid_llm_json(evidence))
    data["replacement_player"] = "Someone Else"
    client = FakeLLMClient(json.dumps(data, ensure_ascii=False))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


def test_dangerous_phrase_falls_back_to_mock() -> None:
    evidence = _full_evidence()
    data = json.loads(_valid_llm_json(evidence))
    data["summary"] = "建议改选 替代人选 better pick"
    client = FakeLLMClient(json.dumps(data, ensure_ascii=False))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


# ---------------------------------------------------------------------------
# 13. Invalid JSON still falls back
# ---------------------------------------------------------------------------


def test_invalid_json_falls_back_to_mock() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient("this is not json {{{")
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


# ---------------------------------------------------------------------------
# 14. Provider error / timeout still falls back
# ---------------------------------------------------------------------------


def test_provider_error_falls_back_to_mock() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(RuntimeError("provider error"))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


def test_provider_timeout_falls_back_to_mock() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(TimeoutError("timed out"))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


# ---------------------------------------------------------------------------
# 15. Payload includes identity + decision lock fields
# ---------------------------------------------------------------------------


def test_payload_includes_identity_fields() -> None:
    evidence = _full_evidence()
    payload = _build_llm_explanation_payload(evidence)
    assert payload["pick_number"] == evidence.pick_number
    assert payload["team_abbr"] == evidence.team_abbr
    assert payload["selected_player_id"] == evidence.selected_player_id
    assert payload["selected_player_name"] == evidence.selected_player_name


def test_payload_includes_decision_locks() -> None:
    evidence = _full_evidence()
    payload = _build_llm_explanation_payload(evidence)
    assert payload["decision_locked"] is True
    assert payload["llm_can_modify_decision"] is False
    assert payload["decision_source"] == "structured_simulation"


def test_payload_includes_evidence_sub_blocks() -> None:
    evidence = _full_evidence()
    payload = _build_llm_explanation_payload(evidence)
    assert "ranking_evidence" in payload
    assert "team_fit_evidence" in payload
    assert "market_evidence" in payload
    assert "risk_evidence" in payload
    assert "conflict_evidence" in payload
    assert "evidence_sufficiency" in payload


# ---------------------------------------------------------------------------
# 16. Prompt contract includes manual_note safety rules
# ---------------------------------------------------------------------------


def test_prompt_contract_includes_manual_note_safety_rules() -> None:
    from app.services.evidence_prompt_contract import (
        build_pick_explanation_prompt_contract,
    )

    contract = build_pick_explanation_prompt_contract()
    developer = contract["developer"]
    # The strengthened contract must mention manual_note safety explicitly.
    assert "ManualNote safety rules" in developer
    assert "manual_note" in developer
    assert "read-only" in developer.lower() or "read only" in developer.lower()
    assert "MUST NOT" in developer


def test_llm_developer_message_contains_manual_note_safety_rules() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(_valid_llm_json(evidence))
    build_llm_pick_explanation(evidence, llm_client=client)
    developer_msg = client.calls[0]["messages"][1]["content"]
    assert "ManualNote safety rules" in developer_msg
    assert "manual_note" in developer_msg


# ---------------------------------------------------------------------------
# RAG-v2-M2-E: Semantic retrieval retrieval_score isolation
# ---------------------------------------------------------------------------


def test_semantic_retrieval_score_excluded_from_llm_payload() -> None:
    """RetrievedEvidence produced by semantic retrieval carries
    ``retrieval_score`` (for sorting).  This test verifies the LLM payload
    whitelist still excludes it end-to-end.

    RAG-v2-M2-E: the semantic retrieval wiring appends RetrievedEvidence
    with ``retrieval_score`` set to ``PickEvidencePackage.retrieved_evidence``.
    The ``_build_llm_explanation_payload`` whitelist must strip it so the
    LLM never sees a numeric score that could be misinterpreted as a
    ranking / scoring signal.
    """
    evidence = _full_evidence()
    # Append a semantic-retrieval-style RetrievedEvidence with retrieval_score.
    evidence.retrieved_evidence.append(
        RetrievedEvidence(
            source_type="manual_note",
            source_id="semantic:0",
            title="Semantic retrieval result",
            excerpt="Chunk matched by semantic search.",
            relevance_reason="Semantic match for query context.",
            retrieval_score=0.92,
            evidence_only=True,
        )
    )
    # Verify the input actually has retrieval_score set.
    assert any(
        r.retrieval_score is not None for r in evidence.retrieved_evidence
    )

    payload = _build_llm_explanation_payload(evidence)
    for item in payload["retrieved_evidence"]:
        assert "retrieval_score" not in item, (
            "retrieval_score from semantic retrieval must not enter LLM payload"
        )


def test_semantic_retrieval_score_excluded_from_llm_user_message() -> None:
    """The LLM user message (JSON) must also exclude retrieval_score from
    semantic retrieval results."""
    evidence = _full_evidence()
    evidence.retrieved_evidence.append(
        RetrievedEvidence(
            source_type="manual_note",
            source_id="semantic:1",
            title="Semantic retrieval result",
            excerpt="Chunk matched by semantic search.",
            relevance_reason="Semantic match for query context.",
            retrieval_score=0.88,
            evidence_only=True,
        )
    )

    client = FakeLLMClient(_valid_llm_json(evidence))
    build_llm_pick_explanation(evidence, llm_client=client)
    user_msg = client.calls[0]["messages"][-1]["content"]
    parsed = json.loads(user_msg)
    for item in parsed["retrieved_evidence"]:
        assert "retrieval_score" not in item
