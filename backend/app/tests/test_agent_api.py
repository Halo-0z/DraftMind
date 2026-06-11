from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.llm_service import LLMService


@pytest.fixture(autouse=True)
def _force_mock_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force agent_api tests to use the deterministic mock explanation.

    The agent endpoint normally calls the configured LLM provider
    (e.g. hunyuan) when `LLM_API_KEY` is set.  For test stability we
    always short-circuit `LLMService.explain_recommendation` to its
    in-process mock implementation, regardless of any developer
    `.env` or environment variable settings.

    We also wrap the LLMService instance with a subclass that reports
    `is_mock = True` and `provider = "mock"` so the response's
    `is_mock` flag is correct.
    """
    real = LLMService()

    def always_mock(recommendation, question, rag_context=""):
        return real._mock_explanation(
            recommendation=recommendation,
            question=question,
            rag_context=rag_context,
        )

    class _MockLLMService(LLMService):
        @property
        def provider(self) -> str:
            return "mock"

        @property
        def is_mock(self) -> bool:
            return True

        def explain_recommendation(self, recommendation, question, rag_context=""):
            return always_mock(
                recommendation=recommendation,
                question=question,
                rag_context=rag_context,
            )

    monkeypatch.setattr(
        "app.services.agent_service.LLMService", _MockLLMService
    )


def test_agent_ask_returns_mock_explanation(client: TestClient) -> None:
    # Phase 6B-M1: pick=2 is SAS's first pick in the conftest seed
    # (draft_order starts at pick_no=2).  At this pick, no prior
    # board has consumed any prospect, so the available list still
    # contains both seeded prospects (Mikel, Braylon).  The
    # recommendation succeeds and AgentService can call the LLM
    # mock to produce an explanation.
    response = client.post(
        "/api/agent/ask",
        json={
            "year": 2026,
            "team": "SAS",
            "pick": 2,
            "question": "请解释这次推荐。",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_mock"] is True
    assert body["recommendation"]["team"]["abbr"] == "SAS"
    assert body["explanation"]["recommendation_reasons"]
    assert body["explanation"]["risks"]
    assert body["explanation"]["alternatives"]
    assert body["explanation"]["gm_summary"]


def test_agent_answers_why_not_alternative(client: TestClient) -> None:
    # Same pick=2 invariant as above: both Mikel and Braylon are
    # still on the board so the follow-up question can name both.
    response = client.post(
        "/api/agent/ask",
        json={
            "year": 2026,
            "team": "SAS",
            "pick": 2,
            "question": "为什么不选 Braylon Mullins？",
        },
    )

    assert response.status_code == 200
    answer = response.json()["explanation"]["follow_up_answer"]
    assert "Braylon Mullins" in answer
    assert "Mikel Brown Jr." in answer
