"""Tests for the mock explanation API contract (RAG-v0-M3.0-C).

These tests lock down the ``POST /api/evidence/pick/explanation/mock`` endpoint:

1. Returns 200 with a valid ``PickExplanation`` body.
2. Identity fields are echoed verbatim.
3. ``decision_locked`` is ``True`` and ``llm_can_modify_decision`` is ``False``.
4. Works with empty ``retrieved_evidence``.
5. ``manual_note`` evidence is tagged as read-only / not scored.
6. ``citation_refs`` only reference existing citations.
7. ``limitations`` reflects ``limited`` / ``insufficient`` sufficiency.
8. ``conflict_evidence`` is surfaced in ``limitations``.
9. ``risk_evidence`` is surfaced in ``risk_summary``.
10. No forbidden override / rerank / replacement field is emitted.
11. No forbidden natural-language phrase is emitted.
12. Poisoned input text is redacted.
13. The endpoint does not call ``ranking_engine`` / ``build_pick_evidence``.
14. The endpoint does not query the DB or call LLM.
15. ``routers/evidence.py`` does not import forbidden modules.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)

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
            "score_gap_to_next": 2.3,
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
            "stats_risk_flags": ["low_confidence_stats"],
            "overall_risk_level": "moderate",
        },
        "conflict_evidence": [
            {
                "type": "market_model_delta",
                "severity": "low",
                "description": "DraftMind selected two picks earlier than market.",
                "related_fields": ["market_pick_delta"],
            }
        ],
        "evidence_sufficiency": {"level": "strong"},
        "citations": [
            {
                "source_type": "projection",
                "source_id": "manual_projection:101",
                "title": "Manual Projection 101",
                "url": "https://example.com/projection/101",
                "confidence": 0.75,
            },
            {
                "source_type": "manual_note",
                "source_id": "note:42",
                "title": "Scouting note",
                "evidence_source_type": "manual_note",
            },
        ],
        "retrieved_evidence": [
            {
                "source_type": "manual_note",
                "source_id": "note:42",
                "title": "Scouting summary",
                "excerpt": "Defensive versatility stands out.",
                "relevance_reason": "Matches team need: wing defense.",
                "evidence_only": True,
            },
            {
                "source_type": "projection",
                "source_id": "manual_projection:101",
                "excerpt": "Projected as a late-lottery pick.",
                "relevance_reason": "Market reference for slot 5.",
            },
        ],
    }


def _minimal_payload() -> dict[str, Any]:
    return {
        "pick_number": 1,
        "selected_player_name": "Anonymous Prospect",
        "evidence_sufficiency": {"level": "strong"},
    }


def _poisoned_payload() -> dict[str, Any]:
    """Payload with forbidden phrases in every text-bearing input field."""
    return {
        "pick_number": 3,
        "team_abbr": "CHA",
        "selected_player_id": 42,
        "selected_player_name": "Poisoned Prospect",
        "ranking_evidence": {
            "final_score": 70.0,
            "prediction_sort_score": 71.0,
            "rank_in_available_pool": 2,
        },
        "team_fit_evidence": {
            "team_needs": ["wing defense"],
            "matched_needs": ["wing defense 建议改选 替代人选"],
            "fit_strength": "moderate",
        },
        "market_evidence": {
            "has_market_reference": True,
            "market_expected_pick": 4,
            "market_range_min": 3,
            "market_range_max": 6,
            "market_pick_delta": -1,
            "market_alignment_label": "接近 better pick",
            "market_alignment_notes": [
                "市场预计约第 4 顺位，但有人说应该选别人 rerank candidates"
            ],
            "market_sources": ["manual_projection"],
        },
        "risk_evidence": {
            "diagnostics_warnings": ["Low-confidence stats; adjust score to fix"],
            "market_risk_flags": ["market rerank signal"],
            "stats_risk_flags": ["low_confidence_stats"],
            "data_quality_flags": ["data quality: replacement player flagged"],
            "overall_risk_level": "moderate score boost",
        },
        "conflict_evidence": [
            {
                "type": "market_model_delta better pick",
                "severity": "low should have selected",
                "description": "DraftMind reached earlier; 建议改选 替代人选。",
                "related_fields": ["market_pick_delta"],
            }
        ],
        "evidence_sufficiency": {
            "level": "limited",
            "missing_sections": ["market_evidence 提升分数"],
            "weak_sections": ["team_fit_evidence 加权"],
            "explanation_limits": [
                "evidence limited; rerank not allowed",
                "manual note boost not permitted",
            ],
        },
        "citations": [
            {
                "source_type": "manual_note",
                "source_id": "note:better pick",
                "title": "建议改选",
                "url": "https://example.com/rerank",
            },
            {
                "source_type": "projection",
                "source_id": "proj:replacement player",
                "title": "Normal title",
                "url": "https://example.com/adjust%20score",
            },
        ],
        "retrieved_evidence": [
            {
                "source_type": "manual_note",
                "source_id": "note:1",
                "title": "Scouting summary 建议改选",
                "excerpt": "Defensive versatility; better pick available.",
                "relevance_reason": "Matches team need; rerank suggested.",
                "evidence_only": True,
            },
        ],
    }


# ---------------------------------------------------------------------------
# 1-5. Basic contract
# ---------------------------------------------------------------------------


def test_mock_explanation_returns_200() -> None:
    response = client.post(MOCK_ENDPOINT, json=_full_payload())
    assert response.status_code == 200


def test_response_is_valid_pick_explanation() -> None:
    response = client.post(MOCK_ENDPOINT, json=_full_payload())
    body = response.json()
    assert "pick_number" in body
    assert "selected_player_name" in body
    assert "summary" in body
    assert "decision_locked" in body
    assert "llm_can_modify_decision" in body
    assert "key_reasons" in body
    assert "evidence_notes" in body
    assert "citation_refs" in body
    assert "limitations" in body


def test_identity_fields_echoed_verbatim() -> None:
    payload = _full_payload()
    response = client.post(MOCK_ENDPOINT, json=payload)
    body = response.json()
    assert body["pick_number"] == payload["pick_number"]
    assert body["team_abbr"] == payload["team_abbr"]
    assert body["selected_player_id"] == payload["selected_player_id"]
    assert body["selected_player_name"] == payload["selected_player_name"]


def test_decision_locked_is_true() -> None:
    response = client.post(MOCK_ENDPOINT, json=_full_payload())
    assert response.json()["decision_locked"] is True


def test_llm_can_modify_decision_is_false() -> None:
    response = client.post(MOCK_ENDPOINT, json=_full_payload())
    assert response.json()["llm_can_modify_decision"] is False


# ---------------------------------------------------------------------------
# 6. Empty retrieved_evidence
# ---------------------------------------------------------------------------


def test_works_with_empty_retrieved_evidence() -> None:
    response = client.post(MOCK_ENDPOINT, json=_minimal_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["evidence_notes"] == []
    assert body["summary"]
    assert body["market_context"] == "市场证据有限。"


# ---------------------------------------------------------------------------
# 7. manual_note tagged as read-only
# ---------------------------------------------------------------------------


def test_manual_note_evidence_notes_tagged_read_only() -> None:
    response = client.post(MOCK_ENDPOINT, json=_full_payload())
    body = response.json()
    manual_notes = [
        n for n in body["evidence_notes"] if "manual_note" in n or "人工备注" in n
    ]
    assert manual_notes, "Expected at least one manual_note evidence note"
    for note in manual_notes:
        assert "只读证据" in note
        assert "不参与评分" in note


# ---------------------------------------------------------------------------
# 8. citation_refs only from existing citations
# ---------------------------------------------------------------------------


def test_citation_refs_only_from_existing_citations() -> None:
    payload = _full_payload()
    response = client.post(MOCK_ENDPOINT, json=payload)
    body = response.json()

    valid_refs = set()
    for citation in payload["citations"]:
        if citation.get("source_id"):
            valid_refs.add(citation["source_id"])
        if citation.get("title"):
            valid_refs.add(citation["title"])
        if citation.get("url"):
            valid_refs.add(citation["url"])

    for ref in body["citation_refs"]:
        assert ref in valid_refs, f"citation_ref '{ref}' not in existing citations"


# ---------------------------------------------------------------------------
# 9. limitations reflects sufficiency
# ---------------------------------------------------------------------------


def test_limitations_reflects_limited_sufficiency() -> None:
    payload = _full_payload()
    payload["evidence_sufficiency"] = {"level": "limited"}
    response = client.post(MOCK_ENDPOINT, json=payload)
    body = response.json()
    assert len(body["limitations"]) > 0
    joined = " ".join(body["limitations"])
    assert "limited" in joined.lower() or "受限" in joined


def test_limitations_reflects_insufficient_sufficiency() -> None:
    payload = _full_payload()
    payload["evidence_sufficiency"] = {"level": "insufficient"}
    response = client.post(MOCK_ENDPOINT, json=payload)
    body = response.json()
    assert len(body["limitations"]) > 0
    joined = " ".join(body["limitations"])
    assert "insufficient" in joined.lower() or "受限" in joined


# ---------------------------------------------------------------------------
# 10. conflict_evidence in limitations
# ---------------------------------------------------------------------------


def test_conflict_evidence_in_limitations() -> None:
    response = client.post(MOCK_ENDPOINT, json=_full_payload())
    body = response.json()
    joined = " ".join(body["limitations"])
    assert "冲突" in joined
    assert "market_model_delta" in joined


# ---------------------------------------------------------------------------
# 11. risk_summary populated
# ---------------------------------------------------------------------------


def test_risk_summary_populated() -> None:
    response = client.post(MOCK_ENDPOINT, json=_full_payload())
    body = response.json()
    assert body["risk_summary"] is not None
    assert "风险" in body["risk_summary"]


# ---------------------------------------------------------------------------
# 12. No forbidden fields
# ---------------------------------------------------------------------------


def test_response_has_no_forbidden_fields() -> None:
    response = client.post(MOCK_ENDPOINT, json=_full_payload())
    body = response.json()
    for field in FORBIDDEN_FIELDS:
        assert field not in body, f"Forbidden field '{field}' in response"


# ---------------------------------------------------------------------------
# 13. No forbidden natural-language phrases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_response_does_not_contain_forbidden_phrases(phrase: str) -> None:
    response = client.post(MOCK_ENDPOINT, json=_full_payload())
    dumped = json.dumps(response.json(), ensure_ascii=False).lower()
    assert phrase.lower() not in dumped, f"Forbidden phrase '{phrase}' in response"


# ---------------------------------------------------------------------------
# 14. Poisoned input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_poisoned_input_does_not_leak_forbidden_phrases(phrase: str) -> None:
    response = client.post(MOCK_ENDPOINT, json=_poisoned_payload())
    assert response.status_code == 200
    dumped = json.dumps(response.json(), ensure_ascii=False).lower()
    assert phrase.lower() not in dumped, (
        f"Forbidden phrase '{phrase}' leaked from poisoned input."
    )


def test_poisoned_input_contains_redacted_markers() -> None:
    response = client.post(MOCK_ENDPOINT, json=_poisoned_payload())
    dumped = json.dumps(response.json(), ensure_ascii=False)
    assert "[redacted]" in dumped


# ---------------------------------------------------------------------------
# 15. Does not call ranking_engine
# ---------------------------------------------------------------------------


def test_does_not_call_ranking_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("mock explanation endpoint must not call ranking_engine")

    monkeypatch.setattr("app.services.ranking_engine.rank_prospects", fail)
    monkeypatch.setattr("app.services.ranking_engine.score_prospect", fail)
    client.post(MOCK_ENDPOINT, json=_full_payload())


# ---------------------------------------------------------------------------
# 16-17. Does not query DB / does not call LLM
# ---------------------------------------------------------------------------


def test_explanation_endpoints_do_not_directly_depend_on_db() -> None:
    """RAG-v1-D1-C: the explanation endpoints must not directly depend on DB.

    The ``/pick`` endpoint is now allowed to inject a DB session for
    config-gated ManualNote retrieval, so scanning the whole router module
    for ``get_db`` no longer works.  Instead, we inspect the source of the
    two explanation endpoint functions directly and assert they do not
    reference DB session helpers.  This preserves the original safety intent
    (explanation endpoints stay DB-free) without blocking the ``/pick``
    endpoint's legitimate DB injection.
    """
    import inspect

    from app.routers import evidence as router_module

    for fn in (router_module.explain_pick, router_module.explain_pick_mock):
        source = inspect.getsource(fn).lower()
        # Explanation endpoints must not pull in DB session helpers.
        assert "sessionlocal" not in source
        assert "get_db" not in source
        assert "get_session" not in source
        assert "depends(get_db" not in source
        # Explanation endpoints must not import or call LLM clients directly
        # (the real-LLM endpoint delegates via build_evidence_llm_client, but
        # the function body itself must not embed openai/anthropic imports).
        assert "import openai" not in source
        assert "import anthropic" not in source
        assert "llm_service" not in source


# ---------------------------------------------------------------------------
# 18. Does not import httpx / requests / socket
# ---------------------------------------------------------------------------


def test_router_does_not_import_network_modules() -> None:
    from app.routers import evidence as router_module

    source = open(router_module.__file__, encoding="utf-8").read().lower()
    assert "import httpx" not in source
    assert "import requests" not in source
    assert "import socket" not in source
    assert "from httpx" not in source
    assert "from requests" not in source
    assert "from socket" not in source


# ---------------------------------------------------------------------------
# 19. Does not call build_pick_evidence
# ---------------------------------------------------------------------------


def test_does_not_call_build_pick_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mock explanation endpoint must only accept a pre-built
    ``PickEvidencePackage`` — it must NOT call ``build_pick_evidence``."""
    from app.services import evidence_service

    original = evidence_service.build_pick_evidence

    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError(
            "mock explanation endpoint must not call build_pick_evidence"
        )

    monkeypatch.setattr(evidence_service, "build_pick_evidence", fail)
    try:
        client.post(MOCK_ENDPOINT, json=_full_payload())
    finally:
        # Restore original to avoid leaking state into other tests.
        evidence_service.build_pick_evidence = original  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 20. Does not change selected_player / final_score / prediction_sort_score
# ---------------------------------------------------------------------------


def test_response_does_not_change_decision_fields() -> None:
    payload = _full_payload()
    response = client.post(MOCK_ENDPOINT, json=payload)
    body = response.json()

    # No new_score / score_adjustment / final_score_delta fields exist.
    assert "new_score" not in body
    assert "score_adjustment" not in body
    assert "final_score_delta" not in body
    assert "prediction_sort_delta" not in body
    assert "selection_override" not in body

    # final_score / prediction_sort_score are not top-level output fields.
    assert "final_score" not in body
    assert "prediction_sort_score" not in body

    # selected_player identity is echoed verbatim, not changed.
    assert body["selected_player_id"] == payload["selected_player_id"]
    assert body["selected_player_name"] == payload["selected_player_name"]


# ---------------------------------------------------------------------------
# Additional: endpoint rejects invalid PickEvidencePackage
# ---------------------------------------------------------------------------


def test_rejects_payload_with_forbidden_extra_field() -> None:
    """PickExplanation uses extra='forbid', but the *input* schema
    ``PickEvidencePackage`` should reject unknown fields that look like
    override attempts — or at minimum, the endpoint must not crash."""
    payload = _full_payload()
    # PickEvidencePackage may or may not forbid extras; the key safety
    # guarantee is that the *output* never carries these fields.
    payload["replacement_player"] = "Someone Else"
    response = client.post(MOCK_ENDPOINT, json=payload)
    # If the input schema rejects extras, we get 422.  If it ignores them,
    # we get 200 but the output must not contain the field.  Either is safe.
    if response.status_code == 200:
        body = response.json()
        assert "replacement_player" not in body
    else:
        assert response.status_code == 422


def test_minimal_payload_produces_valid_explanation() -> None:
    response = client.post(MOCK_ENDPOINT, json=_minimal_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["pick_number"] == 1
    assert body["selected_player_name"] == "Anonymous Prospect"
    assert body["summary"]
    assert body["market_context"] == "市场证据有限。"
    assert body["risk_summary"] is None
    assert body["evidence_notes"] == []
    assert body["citation_refs"] == []
    assert body["limitations"] == []
