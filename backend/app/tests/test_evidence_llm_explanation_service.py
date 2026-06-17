"""Tests for the real LLM explanation service shell (RAG-v0-M3.1-B).

These tests lock down the guarded shell around the LLM client:

1. ``llm_client is None`` → fallback to mock.
2. Fake LLM returns valid JSON → returns ``PickExplanation``.
3. Success path: identity fields verbatim.
4. Success path: ``decision_locked=True``.
5. Success path: ``llm_can_modify_decision=False``.
6. Prompt contract is used.
7. LLM input only contains ``PickEvidencePackage`` (no alternatives/board).
8. Invalid JSON → fallback mock.
9. LLM exception → fallback mock.
10. LLM timeout-style exception → fallback mock.
11. Schema extra dangerous field → fallback mock.
12. Dangerous natural language → fallback mock.
13. Identity mismatch → fallback mock.
14. ``decision_locked=False`` → fallback mock.
15. ``llm_can_modify_decision=True`` → fallback mock.
16. Fabricated citation_refs → fallback mock.
17. limited/insufficient but empty limitations → fallback mock.
18. conflict_evidence present but not described → fallback mock.
19. risk_evidence present but empty risk_summary → fallback mock.
20. Does not call ranking_engine.
21. Does not call prediction_calibration.
22. Does not call simulation_service.
23. Does not query DB.
24. Does not import openai/httpx/requests/socket.
25. Does not mutate input.
26. Does not change selected_player/final_score/prediction_sort_score.
27. Fallback calls ``build_mock_pick_explanation``.
28. Output has no forbidden fields.
29. Output has no forbidden phrases.
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
    FORBIDDEN_FIELDS,
    build_llm_pick_explanation,
)


FORBIDDEN_PHRASES = (
    "应该选别人",
    "更好的选择",
    "建议改选",
    "重新排序",
    "提升分数",
    "replacement player",
    "better pick",
    "rerank",
    "adjust score",
)


# ---------------------------------------------------------------------------
# Fake LLM client
# ---------------------------------------------------------------------------


class FakeLLMClient:
    """Minimal fake LLM client for testing."""

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
        ],
    )


def _valid_llm_json(evidence: PickEvidencePackage | None = None) -> str:
    """Return a JSON string that passes all safety checks."""
    if evidence is None:
        evidence = _full_evidence()
    mock = build_mock_pick_explanation(evidence)
    return mock.model_dump_json()


def _limited_evidence() -> PickEvidencePackage:
    evidence = _full_evidence()
    evidence.evidence_sufficiency = EvidenceSufficiency(level="limited")
    return evidence


def _no_conflict_evidence() -> PickEvidencePackage:
    evidence = _full_evidence()
    evidence.conflict_evidence = []
    return evidence


def _no_risk_evidence() -> PickEvidencePackage:
    evidence = _full_evidence()
    evidence.risk_evidence = None
    return evidence


# ---------------------------------------------------------------------------
# 1. llm_client is None → fallback mock
# ---------------------------------------------------------------------------


def test_none_client_falls_back_to_mock() -> None:
    evidence = _full_evidence()
    result = build_llm_pick_explanation(evidence, llm_client=None)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


# ---------------------------------------------------------------------------
# 2. Fake LLM returns valid JSON → returns PickExplanation
# ---------------------------------------------------------------------------


def test_valid_llm_response_returns_pick_explanation() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(_valid_llm_json(evidence))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    assert isinstance(result, PickExplanation)
    assert client.calls, "LLM client should have been called"


# ---------------------------------------------------------------------------
# 3-5. Success path checks
# ---------------------------------------------------------------------------


def test_success_identity_fields_verbatim() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(_valid_llm_json(evidence))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    assert result.pick_number == evidence.pick_number
    assert result.team_abbr == evidence.team_abbr
    assert result.selected_player_id == evidence.selected_player_id
    assert result.selected_player_name == evidence.selected_player_name


def test_success_decision_locked_true() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(_valid_llm_json(evidence))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    assert result.decision_locked is True


def test_success_llm_can_modify_decision_false() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(_valid_llm_json(evidence))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    assert result.llm_can_modify_decision is False


# ---------------------------------------------------------------------------
# 6. Prompt contract used
# ---------------------------------------------------------------------------


def test_prompt_contract_is_used() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(_valid_llm_json(evidence))
    build_llm_pick_explanation(evidence, llm_client=client)
    assert len(client.calls) == 1
    messages = client.calls[0]["messages"]
    # Should have system, developer, and user messages.
    roles = [m["role"] for m in messages]
    assert "system" in roles
    assert "developer" in roles
    # The developer prompt should contain contract guardrails.
    developer_msg = next(m["content"] for m in messages if m["role"] == "developer")
    assert "PickExplanation" in developer_msg
    assert "forbid" in developer_msg.lower() or "forbidden" in developer_msg.lower()


# ---------------------------------------------------------------------------
# 7. LLM input only contains PickEvidencePackage
# ---------------------------------------------------------------------------


def test_llm_input_only_contains_evidence_package() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(_valid_llm_json(evidence))
    build_llm_pick_explanation(evidence, llm_client=client)
    user_msg = client.calls[0]["messages"][-1]["content"]
    parsed = json.loads(user_msg)
    # Must contain evidence fields.
    assert parsed["pick_number"] == evidence.pick_number
    assert parsed["selected_player_name"] == evidence.selected_player_name
    # Must NOT contain forbidden extras.
    assert "candidate_board" not in parsed
    assert "alternatives" not in parsed
    assert "simulation" not in parsed
    assert "ranking_result" not in parsed
    assert "db_result" not in parsed


# ---------------------------------------------------------------------------
# 8. Invalid JSON → fallback mock
# ---------------------------------------------------------------------------


def test_invalid_json_falls_back_to_mock() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient("this is not json {{{")
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


# ---------------------------------------------------------------------------
# 9. LLM exception → fallback mock
# ---------------------------------------------------------------------------


def test_llm_exception_falls_back_to_mock() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(RuntimeError("LLM provider error"))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


# ---------------------------------------------------------------------------
# 10. LLM timeout → fallback mock
# ---------------------------------------------------------------------------


def test_llm_timeout_falls_back_to_mock() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(TimeoutError("LLM timed out"))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


# ---------------------------------------------------------------------------
# 11. Schema extra dangerous field → fallback mock
# ---------------------------------------------------------------------------


def test_dangerous_extra_field_falls_back_to_mock() -> None:
    evidence = _full_evidence()
    bad_json = _valid_llm_json(evidence).rstrip("}")
    bad_json = bad_json[:-1]  # remove trailing comma if any
    bad_json += ', "replacement_player": "Someone Else"}}'
    client = FakeLLMClient(bad_json)
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


# ---------------------------------------------------------------------------
# 12. Dangerous natural language → fallback mock
# ---------------------------------------------------------------------------


def test_dangerous_phrase_falls_back_to_mock() -> None:
    evidence = _full_evidence()
    data = json.loads(_valid_llm_json(evidence))
    data["summary"] = "建议改选 替代人选 better pick"
    client = FakeLLMClient(json.dumps(data, ensure_ascii=False))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


# ---------------------------------------------------------------------------
# 13. Identity mismatch → fallback mock
# ---------------------------------------------------------------------------


def test_identity_mismatch_falls_back_to_mock() -> None:
    evidence = _full_evidence()
    data = json.loads(_valid_llm_json(evidence))
    data["pick_number"] = 99
    client = FakeLLMClient(json.dumps(data, ensure_ascii=False))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


# ---------------------------------------------------------------------------
# 14. decision_locked=False → fallback mock
# ---------------------------------------------------------------------------


def test_decision_locked_false_falls_back_to_mock() -> None:
    evidence = _full_evidence()
    data = json.loads(_valid_llm_json(evidence))
    data["decision_locked"] = False
    client = FakeLLMClient(json.dumps(data, ensure_ascii=False))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


# ---------------------------------------------------------------------------
# 15. llm_can_modify_decision=True → fallback mock
# ---------------------------------------------------------------------------


def test_llm_can_modify_true_falls_back_to_mock() -> None:
    evidence = _full_evidence()
    data = json.loads(_valid_llm_json(evidence))
    data["llm_can_modify_decision"] = True
    client = FakeLLMClient(json.dumps(data, ensure_ascii=False))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


# ---------------------------------------------------------------------------
# 16. Fabricated citation_refs → fallback mock
# ---------------------------------------------------------------------------


def test_fabricated_citation_refs_falls_back_to_mock() -> None:
    evidence = _full_evidence()
    data = json.loads(_valid_llm_json(evidence))
    data["citation_refs"] = ["fabricated:ref:not:in:citations"]
    client = FakeLLMClient(json.dumps(data, ensure_ascii=False))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


# ---------------------------------------------------------------------------
# 17. limited/insufficient but empty limitations → fallback mock
# ---------------------------------------------------------------------------


def test_limited_empty_limitations_falls_back_to_mock() -> None:
    evidence = _limited_evidence()
    data = json.loads(_valid_llm_json(evidence))
    data["limitations"] = []
    client = FakeLLMClient(json.dumps(data, ensure_ascii=False))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


# ---------------------------------------------------------------------------
# 18. conflict_evidence present but not described → fallback mock
# ---------------------------------------------------------------------------


def test_conflict_not_described_falls_back_to_mock() -> None:
    evidence = _full_evidence()  # has conflict_evidence
    data = json.loads(_valid_llm_json(evidence))
    # Remove all conflict mentions from text fields.
    data["limitations"] = [l for l in data["limitations"] if "冲突" not in l and "conflict" not in l.lower()]
    data["evidence_notes"] = [n for n in data["evidence_notes"] if "冲突" not in n and "conflict" not in n.lower()]
    # Summary must not contain the word "conflict" (English) or "冲突" (Chinese).
    data["summary"] = "A safe summary that does not mention the market-model tension."
    client = FakeLLMClient(json.dumps(data, ensure_ascii=False))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


# ---------------------------------------------------------------------------
# 19. risk_evidence present but empty risk_summary → fallback mock
# ---------------------------------------------------------------------------


def test_risk_not_described_falls_back_to_mock() -> None:
    evidence = _full_evidence()  # has risk_evidence with flags
    data = json.loads(_valid_llm_json(evidence))
    data["risk_summary"] = None
    client = FakeLLMClient(json.dumps(data, ensure_ascii=False))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    expected = build_mock_pick_explanation(evidence)
    assert result.model_dump() == expected.model_dump()


# ---------------------------------------------------------------------------
# 20-22. Does not call ranking / prediction / simulation
# ---------------------------------------------------------------------------


def test_does_not_call_ranking_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*a: object, **k: object) -> object:
        raise AssertionError("must not call ranking_engine")

    monkeypatch.setattr("app.services.ranking_engine.rank_prospects", fail)
    monkeypatch.setattr("app.services.ranking_engine.score_prospect", fail)
    evidence = _full_evidence()
    client = FakeLLMClient(_valid_llm_json(evidence))
    build_llm_pick_explanation(evidence, llm_client=client)


def test_does_not_call_prediction_calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.prediction_calibration as pc

    original = pc.calculate_prediction_calibration
    monkeypatch.setattr(pc, "calculate_prediction_calibration", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call prediction_calibration")))
    try:
        evidence = _full_evidence()
        client = FakeLLMClient(_valid_llm_json(evidence))
        build_llm_pick_explanation(evidence, llm_client=client)
    finally:
        pc.calculate_prediction_calibration = original  # type: ignore[assignment]


def test_does_not_call_simulation_service(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.simulation_service as ss

    original = ss.simulate_draft
    monkeypatch.setattr(ss, "simulate_draft", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call simulation_service")))
    try:
        evidence = _full_evidence()
        client = FakeLLMClient(_valid_llm_json(evidence))
        build_llm_pick_explanation(evidence, llm_client=client)
    finally:
        ss.simulate_draft = original  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 23. Does not query DB
# ---------------------------------------------------------------------------


def test_does_not_import_db_modules() -> None:
    from app.services import evidence_llm_explanation_service as module

    forbidden = {"SessionLocal", "get_session", "sessionmaker", "create_engine", "Session", "get_db"}
    attrs = set(vars(module).keys())
    assert not (attrs & forbidden)


# ---------------------------------------------------------------------------
# 24. Does not import openai/httpx/requests/socket
# ---------------------------------------------------------------------------


def test_does_not_import_forbidden_modules() -> None:
    from app.services import evidence_llm_explanation_service as module

    source = open(module.__file__, encoding="utf-8").read().lower()
    assert "import openai" not in source
    assert "import httpx" not in source
    assert "import requests" not in source
    assert "import socket" not in source
    assert "from openai" not in source
    assert "from httpx" not in source
    assert "from requests" not in source
    assert "from socket" not in source
    assert "os.environ" not in source
    assert "getenv" not in source


# ---------------------------------------------------------------------------
# 25. Does not mutate input
# ---------------------------------------------------------------------------


def test_does_not_mutate_input() -> None:
    evidence = _full_evidence()
    snapshot = copy.deepcopy(evidence.model_dump())
    client = FakeLLMClient(_valid_llm_json(evidence))
    build_llm_pick_explanation(evidence, llm_client=client)
    assert evidence.model_dump() == snapshot


# ---------------------------------------------------------------------------
# 26. Does not change selected_player / final_score / prediction_sort_score
# ---------------------------------------------------------------------------


def test_output_has_no_decision_override_fields() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(_valid_llm_json(evidence))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    dumped = result.model_dump()
    for field in FORBIDDEN_FIELDS:
        assert field not in dumped
    assert "final_score" not in dumped
    assert "prediction_sort_score" not in dumped
    assert result.selected_player_id == evidence.selected_player_id
    assert result.selected_player_name == evidence.selected_player_name


# ---------------------------------------------------------------------------
# 27. Fallback calls build_mock_pick_explanation
# ---------------------------------------------------------------------------


def test_fallback_uses_mock_service(monkeypatch: pytest.MonkeyPatch) -> None:
    evidence = _full_evidence()
    mock_result = build_mock_pick_explanation(evidence)
    call_count = 0

    def tracking_mock(ev: PickEvidencePackage) -> PickExplanation:
        nonlocal call_count
        call_count += 1
        return mock_result

    monkeypatch.setattr(
        "app.services.evidence_llm_explanation_service.build_mock_pick_explanation",
        tracking_mock,
    )
    # None client → should call mock.
    build_llm_pick_explanation(evidence, llm_client=None)
    assert call_count == 1

    # Invalid JSON → should call mock.
    call_count = 0
    client = FakeLLMClient("not json")
    build_llm_pick_explanation(evidence, llm_client=client)
    assert call_count == 1


# ---------------------------------------------------------------------------
# 28-29. Output has no forbidden fields / phrases (even on success path)
# ---------------------------------------------------------------------------


def test_success_output_has_no_forbidden_fields() -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(_valid_llm_json(evidence))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    dumped = result.model_dump()
    for field in FORBIDDEN_FIELDS:
        assert field not in dumped


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_success_output_has_no_forbidden_phrases(phrase: str) -> None:
    evidence = _full_evidence()
    client = FakeLLMClient(_valid_llm_json(evidence))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    dumped = json.dumps(result.model_dump(), ensure_ascii=False).lower()
    assert phrase.lower() not in dumped


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_fallback_output_has_no_forbidden_phrases(phrase: str) -> None:
    evidence = _full_evidence()
    client = FakeLLMClient("invalid json")
    result = build_llm_pick_explanation(evidence, llm_client=client)
    dumped = json.dumps(result.model_dump(), ensure_ascii=False).lower()
    assert phrase.lower() not in dumped


# ---------------------------------------------------------------------------
# Additional: fenced JSON handling
# ---------------------------------------------------------------------------


def test_fenced_json_is_parsed() -> None:
    evidence = _full_evidence()
    raw = "```json\n" + _valid_llm_json(evidence) + "\n```"
    client = FakeLLMClient(raw)
    result = build_llm_pick_explanation(evidence, llm_client=client)
    assert isinstance(result, PickExplanation)
    assert result.pick_number == evidence.pick_number


def test_success_with_limited_sufficiency_and_limitations() -> None:
    evidence = _limited_evidence()
    # The mock output already has limitations for limited sufficiency.
    client = FakeLLMClient(_valid_llm_json(evidence))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    assert isinstance(result, PickExplanation)
    assert len(result.limitations) > 0


def test_success_with_no_conflict_passes() -> None:
    evidence = _no_conflict_evidence()
    client = FakeLLMClient(_valid_llm_json(evidence))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    assert isinstance(result, PickExplanation)


def test_success_with_no_risk_passes() -> None:
    evidence = _no_risk_evidence()
    client = FakeLLMClient(_valid_llm_json(evidence))
    result = build_llm_pick_explanation(evidence, llm_client=client)
    assert isinstance(result, PickExplanation)
