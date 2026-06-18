"""Tests for the guarded real explanation API (RAG-v0-M3.1-E).

These tests lock down ``POST /api/evidence/pick/explanation``:

1. Returns 200 with a valid ``PickExplanation`` body.
2. Identity fields are echoed verbatim.
3. ``decision_locked=True`` and ``llm_can_modify_decision=False``.
4. Default disabled → mock-equivalent output.
5. No API key → mock-equivalent output.
6. Fake client with valid JSON → LLM explanation.
7. Fake client timeout/error → fallback mock.
8. Fake client invalid JSON → fallback mock.
9. Fake client dangerous extra field → fallback mock.
10. Fake client dangerous phrase → fallback mock.
11. Endpoint does not call ``build_pick_evidence``.
12. Endpoint does not call ranking/prediction/simulation.
13. Endpoint does not query DB.
14. Response has no forbidden fields.
15. Router does not import OpenAI/requests/httpx/socket.
16. Mock endpoint still works.
17. Does not change selected_player/final_score/prediction_sort_score.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.evidence_explanation_service import build_mock_pick_explanation
from app.services.evidence_llm_provider import EvidenceLLMProviderError


client = TestClient(app)

REAL_ENDPOINT = "/api/evidence/pick/explanation"
MOCK_ENDPOINT = "/api/evidence/pick/explanation/mock"

FORBIDDEN_FIELDS = {
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


# ---------------------------------------------------------------------------
# Fake LLM client (satisfies LLMClient protocol)
# ---------------------------------------------------------------------------


class FakeLLMClient:
    def __init__(self, response: str | Exception):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def _full_payload() -> dict[str, Any]:
    return {
        "pick_number": 5,
        "team_abbr": "LAC",
        "selected_player_id": 101,
        "selected_player_name": "Keaton Sample",
        "ranking_evidence": {
            "final_score": 82.4,
            "prediction_sort_score": 84.1,
            "rank_in_available_pool": 1,
        },
        "team_fit_evidence": {
            "team_needs": ["wing defense"],
            "matched_needs": ["wing defense"],
            "fit_strength": "moderate",
        },
        "market_evidence": {
            "has_market_reference": True,
            "market_expected_pick": 7,
            "market_range_min": 5,
            "market_range_max": 10,
            "market_pick_delta": -2,
            "market_alignment_label": "接近",
            "market_alignment_notes": ["市场预计约第 7 顺位。"],
            "market_sources": ["manual_projection"],
        },
        "risk_evidence": {
            "diagnostics_warnings": ["Low-confidence imported stats."],
            "overall_risk_level": "moderate",
        },
        "conflict_evidence": [
            {
                "type": "market_model_delta",
                "severity": "low",
                "description": "DraftMind selected two picks earlier than market.",
            }
        ],
        "evidence_sufficiency": {"level": "strong"},
        "citations": [
            {
                "source_type": "projection",
                "source_id": "manual_projection:101",
                "title": "Manual Projection 101",
                "url": "https://example.com/projection/101",
            },
        ],
        "retrieved_evidence": [
            {
                "source_type": "manual_note",
                "source_id": "note:42",
                "title": "Scouting summary",
                "excerpt": "Defensive versatility stands out.",
                "relevance_reason": "Matches team need.",
                "evidence_only": True,
            },
        ],
    }


def _mock_json_for_payload(payload: dict[str, Any]) -> str:
    """Return the JSON that build_mock_pick_explanation would produce."""
    from app.schemas.evidence import PickEvidencePackage

    evidence = PickEvidencePackage.model_validate(payload)
    return build_mock_pick_explanation(evidence).model_dump_json()


# ---------------------------------------------------------------------------
# 1-5. Basic contract (default disabled → mock)
# ---------------------------------------------------------------------------


def test_returns_200() -> None:
    response = client.post(REAL_ENDPOINT, json=_full_payload())
    assert response.status_code == 200


def test_response_is_valid_pick_explanation() -> None:
    response = client.post(REAL_ENDPOINT, json=_full_payload())
    body = response.json()
    for field in (
        "pick_number",
        "selected_player_name",
        "summary",
        "decision_locked",
        "llm_can_modify_decision",
        "key_reasons",
        "evidence_notes",
        "citation_refs",
        "limitations",
    ):
        assert field in body


def test_identity_fields_echoed_verbatim() -> None:
    payload = _full_payload()
    response = client.post(REAL_ENDPOINT, json=payload)
    body = response.json()
    assert body["pick_number"] == payload["pick_number"]
    assert body["team_abbr"] == payload["team_abbr"]
    assert body["selected_player_id"] == payload["selected_player_id"]
    assert body["selected_player_name"] == payload["selected_player_name"]


def test_decision_locked_true() -> None:
    response = client.post(REAL_ENDPOINT, json=_full_payload())
    assert response.json()["decision_locked"] is True


def test_llm_can_modify_decision_false() -> None:
    response = client.post(REAL_ENDPOINT, json=_full_payload())
    assert response.json()["llm_can_modify_decision"] is False


# ---------------------------------------------------------------------------
# 6-7. Default disabled / no key → mock-equivalent
# ---------------------------------------------------------------------------


def test_default_disabled_returns_mock_equivalent() -> None:
    payload = _full_payload()
    response = client.post(REAL_ENDPOINT, json=payload)
    body = response.json()
    mock_json = json.loads(_mock_json_for_payload(payload))
    assert body == mock_json


def test_no_api_key_returns_mock_equivalent(monkeypatch: pytest.MonkeyPatch) -> None:
    # Even if the flag is on, no key → None client → mock fallback.
    from app.config import Settings, get_settings

    settings = Settings(enable_real_llm_explanation=True, llm_api_key="")
    monkeypatch.setattr("app.routers.evidence.get_settings", lambda: settings)
    get_settings.cache_clear()
    try:
        payload = _full_payload()
        response = client.post(REAL_ENDPOINT, json=payload)
        body = response.json()
        mock_json = json.loads(_mock_json_for_payload(payload))
        assert body == mock_json
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 8. Fake client with valid JSON → LLM explanation
# ---------------------------------------------------------------------------


def test_fake_client_valid_json_returns_llm_explanation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _full_payload()
    valid_llm_json = _mock_json_for_payload(payload)
    fake_client = FakeLLMClient(valid_llm_json)
    monkeypatch.setattr(
        "app.routers.evidence.build_evidence_llm_client", lambda settings: fake_client
    )
    response = client.post(REAL_ENDPOINT, json=payload)
    assert response.status_code == 200
    assert len(fake_client.calls) == 1
    body = response.json()
    assert body["pick_number"] == payload["pick_number"]


# ---------------------------------------------------------------------------
# 9. Fake client timeout/error → fallback mock
# ---------------------------------------------------------------------------


def test_fake_client_timeout_falls_back_to_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeLLMClient(TimeoutError("timed out"))
    monkeypatch.setattr(
        "app.routers.evidence.build_evidence_llm_client", lambda settings: fake_client
    )
    payload = _full_payload()
    response = client.post(REAL_ENDPOINT, json=payload)
    body = response.json()
    mock_json = json.loads(_mock_json_for_payload(payload))
    assert body == mock_json


def test_fake_client_error_falls_back_to_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeLLMClient(EvidenceLLMProviderError("provider error"))
    monkeypatch.setattr(
        "app.routers.evidence.build_evidence_llm_client", lambda settings: fake_client
    )
    payload = _full_payload()
    response = client.post(REAL_ENDPOINT, json=payload)
    body = response.json()
    mock_json = json.loads(_mock_json_for_payload(payload))
    assert body == mock_json


# ---------------------------------------------------------------------------
# 10. Fake client invalid JSON → fallback mock
# ---------------------------------------------------------------------------


def test_fake_client_invalid_json_falls_back_to_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeLLMClient("this is not json {{{")
    monkeypatch.setattr(
        "app.routers.evidence.build_evidence_llm_client", lambda settings: fake_client
    )
    payload = _full_payload()
    response = client.post(REAL_ENDPOINT, json=payload)
    body = response.json()
    mock_json = json.loads(_mock_json_for_payload(payload))
    assert body == mock_json


# ---------------------------------------------------------------------------
# 11. Fake client dangerous extra field → fallback mock
# ---------------------------------------------------------------------------


def test_fake_client_dangerous_extra_field_falls_back_to_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _full_payload()
    valid_json = _mock_json_for_payload(payload)
    # Inject a forbidden field.
    data = json.loads(valid_json)
    data["replacement_player"] = "Someone Else"
    fake_client = FakeLLMClient(json.dumps(data, ensure_ascii=False))
    monkeypatch.setattr(
        "app.routers.evidence.build_evidence_llm_client", lambda settings: fake_client
    )
    response = client.post(REAL_ENDPOINT, json=payload)
    body = response.json()
    mock_json = json.loads(_mock_json_for_payload(payload))
    assert body == mock_json
    assert "replacement_player" not in body


# ---------------------------------------------------------------------------
# 12. Fake client dangerous phrase → fallback mock
# ---------------------------------------------------------------------------


def test_fake_client_dangerous_phrase_falls_back_to_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _full_payload()
    data = json.loads(_mock_json_for_payload(payload))
    data["summary"] = "建议改选 替代人选 better pick"
    fake_client = FakeLLMClient(json.dumps(data, ensure_ascii=False))
    monkeypatch.setattr(
        "app.routers.evidence.build_evidence_llm_client", lambda settings: fake_client
    )
    response = client.post(REAL_ENDPOINT, json=payload)
    body = response.json()
    mock_json = json.loads(_mock_json_for_payload(payload))
    assert body == mock_json


# ---------------------------------------------------------------------------
# 13. Endpoint does not call build_pick_evidence
# ---------------------------------------------------------------------------


def test_does_not_call_build_pick_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import evidence_service

    original = evidence_service.build_pick_evidence

    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("endpoint must not call build_pick_evidence")

    monkeypatch.setattr(evidence_service, "build_pick_evidence", fail)
    try:
        client.post(REAL_ENDPOINT, json=_full_payload())
    finally:
        evidence_service.build_pick_evidence = original  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 14. Endpoint does not call ranking/prediction/simulation
# ---------------------------------------------------------------------------


def test_does_not_call_ranking_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*a: object, **k: object) -> object:
        raise AssertionError("must not call ranking_engine")

    monkeypatch.setattr("app.services.ranking_engine.rank_prospects", fail)
    monkeypatch.setattr("app.services.ranking_engine.score_prospect", fail)
    client.post(REAL_ENDPOINT, json=_full_payload())


def test_does_not_call_prediction_calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.prediction_calibration as pc

    original = pc.calculate_prediction_calibration
    monkeypatch.setattr(
        pc,
        "calculate_prediction_calibration",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("must not call prediction_calibration")
        ),
    )
    try:
        client.post(REAL_ENDPOINT, json=_full_payload())
    finally:
        pc.calculate_prediction_calibration = original  # type: ignore[assignment]


def test_does_not_call_simulation_service(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.simulation_service as ss

    original = ss.simulate_draft
    monkeypatch.setattr(
        ss,
        "simulate_draft",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("must not call simulation_service")
        ),
    )
    try:
        client.post(REAL_ENDPOINT, json=_full_payload())
    finally:
        ss.simulate_draft = original  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 15. Endpoint does not query DB
# ---------------------------------------------------------------------------


def test_explanation_endpoint_does_not_directly_depend_on_db() -> None:
    """RAG-v1-D1-C: the real explanation endpoint must not directly depend on DB.

    The ``/pick`` endpoint is now allowed to inject a DB session for
    config-gated ManualNote retrieval, so scanning the whole router module
    for ``get_db`` no longer works.  Instead, we inspect the source of the
    ``explain_pick`` function directly and assert it does not reference DB
    session helpers.  This preserves the original safety intent (the real
    explanation endpoint stays DB-free) without blocking the ``/pick``
    endpoint's legitimate DB injection.
    """
    import inspect

    from app.routers import evidence as router_module

    source = inspect.getsource(router_module.explain_pick).lower()
    assert "sessionlocal" not in source
    assert "get_db" not in source
    assert "get_session" not in source
    assert "depends(get_db" not in source


# ---------------------------------------------------------------------------
# 16. Response has no forbidden fields
# ---------------------------------------------------------------------------


def test_response_has_no_forbidden_fields() -> None:
    response = client.post(REAL_ENDPOINT, json=_full_payload())
    body = response.json()
    for field in FORBIDDEN_FIELDS:
        assert field not in body, f"Forbidden field '{field}' in response"


# ---------------------------------------------------------------------------
# 17. Router does not import OpenAI/requests/httpx/socket
# ---------------------------------------------------------------------------


def test_router_does_not_import_forbidden_modules() -> None:
    from app.routers import evidence as router_module

    source = open(router_module.__file__, encoding="utf-8").read().lower()
    assert "import openai" not in source
    assert "import httpx" not in source
    assert "import requests" not in source
    assert "import socket" not in source
    assert "from openai" not in source
    assert "from httpx" not in source
    assert "from requests" not in source
    assert "from socket" not in source


# ---------------------------------------------------------------------------
# 18. No real network requests (covered by using FakeLLMClient / default None)
# ---------------------------------------------------------------------------


def test_no_real_network_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    # When the provider is disabled (default), no client is created and no
    # network call is made.  This test verifies the default path.
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        response = client.post(REAL_ENDPOINT, json=_full_payload())
        assert response.status_code == 200
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 19. Mock endpoint still works
# ---------------------------------------------------------------------------


def test_mock_endpoint_still_works() -> None:
    response = client.post(MOCK_ENDPOINT, json=_full_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["pick_number"] == 5
    assert body["decision_locked"] is True


def test_both_endpoints_produce_same_output_when_disabled() -> None:
    payload = _full_payload()
    real_response = client.post(REAL_ENDPOINT, json=payload)
    mock_response = client.post(MOCK_ENDPOINT, json=payload)
    assert real_response.json() == mock_response.json()


# ---------------------------------------------------------------------------
# 20. Does not change selected_player / final_score / prediction_sort_score
# ---------------------------------------------------------------------------


def test_does_not_change_decision_fields() -> None:
    payload = _full_payload()
    response = client.post(REAL_ENDPOINT, json=payload)
    body = response.json()
    for field in FORBIDDEN_FIELDS:
        assert field not in body
    assert "final_score" not in body
    assert "prediction_sort_score" not in body
    assert body["selected_player_id"] == payload["selected_player_id"]
    assert body["selected_player_name"] == payload["selected_player_name"]
