"""End-to-end contract tests for ManualNote -> Evidence API pipeline.

These tests exercise the full HTTP path ``POST /api/evidence/pick`` with
``manual_notes`` in the request payload and assert that:

1. Matched manual notes flow through the mapper into ``retrieved_evidence``
   and ``citations``.
2. Selection / scoring / ranking fields are untouched.
3. Irrelevant manual notes are filtered out.
4. Omitting ``manual_notes`` preserves the legacy contract.
5. No dangerous override / reranking fields leak into the response.

No production code is modified by this milestone.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.evidence import ManualNote
from app.schemas.prospect import ProspectRead
from app.schemas.recommendation import RankedProspectRead, ScoreBreakdown
from app.schemas.simulation import SimulateResponse, SimulatedPickRead, TradeEvaluation
from app.schemas.team import TeamRead


client = TestClient(app)


DANGEROUS_FIELDS = {
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
}


def _prospect(prospect_id: int, name: str) -> ProspectRead:
    return ProspectRead(
        id=prospect_id,
        year=2026,
        name=name,
        position="G",
        age=19.0,
        height="6-6",
        weight=200,
        school_or_league="Test",
        ppg=12.0,
        rpg=4.0,
        apg=3.0,
        fg_pct=45.0,
        three_pct=35.0,
        ft_pct=75.0,
        stocks=1.2,
        archetype="connector",
        upside_score=80.0,
        risk_score=20.0,
    )


def _ranked(
    prospect_id: int,
    name: str,
    final_score: float,
    *,
    prediction_sort_score: float | None = None,
) -> RankedProspectRead:
    return RankedProspectRead(
        prospect=_prospect(prospect_id, name),
        scores=ScoreBreakdown(
            talent_score=80.0,
            fit_score=70.0,
            pick_value_score=75.0,
            risk_penalty=5.0,
            final_score=final_score,
        ),
        reasons=["Final score led the available board."],
        risks=["Shot profile needs monitoring."],
        projection_expected_pick=5,
        projection_draft_range_min=4,
        projection_draft_range_max=8,
        projection_confidence=0.8,
        projection_source="manual_projection",
        market_expected_pick=5,
        draftmind_selected_pick=5,
        market_pick_delta=0,
        market_alignment_label="一致",
        market_alignment_notes=["市场预计约第 5 顺位。"],
        prediction_sort_score=prediction_sort_score,
    )


def _pick(selected: RankedProspectRead) -> SimulatedPickRead:
    board = [
        selected,
        _ranked(2, "Next Player", 78.0),
        _ranked(3, "Third Player", 75.0),
    ]
    return SimulatedPickRead(
        pick=5,
        team=TeamRead(
            id=1,
            name="LA Clippers",
            abbr="LAC",
            nba_team_id=1610612746,
            city="Los Angeles",
            conference="West",
            division="Pacific",
        ),
        selected_player=selected,
        alternatives=board[1:3],
        candidate_board=board,
        trade_evaluation=TradeEvaluation(
            action="stay",
            probability=0.1,
            rationale="Trade evaluation disabled in test.",
        ),
        decision_log=["Selected by structured simulation."],
    )


def _simulation(pick: SimulatedPickRead) -> SimulateResponse:
    return SimulateResponse(
        year=2026,
        rounds=1,
        total_picks=1,
        source="test",
        picks=[pick],
        market_top30_missing_warnings=[],
    )


def _payload(
    pick: SimulatedPickRead,
    *,
    manual_notes: list[ManualNote] | None = None,
) -> dict:
    simulation = _simulation(pick)
    payload = {
        "simulation": simulation.model_dump(),
        "pick": pick.model_dump(),
    }
    if manual_notes is not None:
        payload["manual_notes"] = [note.model_dump() for note in manual_notes]
    return payload


def _matched_prospect_note() -> ManualNote:
    return ManualNote(
        note_id=42,
        year=2026,
        entity_type="prospect",
        entity_id=1,
        prospect_id=1,
        title="Manual scouting note",
        body="Keaton showed strong defensive range in a private workout.",
        summary="Strong defensive range.",
        confidence=0.82,
        relevance_reason="Explains why this selected player has defensive upside.",
    )


def _unrelated_prospect_note() -> ManualNote:
    return ManualNote(
        note_id=99,
        year=2026,
        entity_type="prospect",
        entity_id=999,
        prospect_id=999,
        title="Wrong player note",
        body="This note should not appear.",
    )


def test_api_manual_note_end_to_end_success() -> None:
    """Matched manual note flows through mapper into evidence package."""
    selected = _ranked(1, "Keaton Sample", 88.0, prediction_sort_score=88.5)
    pick = _pick(selected)
    note = _matched_prospect_note()

    response = client.post("/api/evidence/pick", json=_payload(pick, manual_notes=[note]))

    assert response.status_code == 200
    body = response.json()

    # Selection / scoring / ranking fields are untouched.
    assert body["selected_player_id"] == 1
    assert body["selected_player_name"] == "Keaton Sample"
    assert body["ranking_evidence"]["final_score"] == 88.0
    assert body["ranking_evidence"]["prediction_sort_score"] == 88.5
    assert body["decision_locked"] is True
    assert body["llm_can_modify_decision"] is False

    # Matched manual note appears in retrieved_evidence.
    assert len(body["retrieved_evidence"]) == 1
    retrieved = body["retrieved_evidence"][0]
    assert retrieved["source_type"] == "manual_note"
    assert retrieved["source_id"] == "42"
    assert retrieved["entity_type"] == "prospect"
    assert retrieved["entity_id"] == 1
    assert retrieved["excerpt"] == "Strong defensive range."
    assert retrieved["evidence_only"] is True

    # Matched manual note appears in citations.
    manual_citations = [
        c for c in body["citations"]
        if c.get("evidence_source_type") == "manual_note"
    ]
    assert len(manual_citations) == 1
    assert manual_citations[0]["source_id"] == "42"
    assert manual_citations[0]["title"] == "Manual scouting note"
    assert manual_citations[0]["evidence_only"] is True


def test_api_unrelated_manual_note_is_filtered_out() -> None:
    """Irrelevant manual notes must not appear in the response."""
    selected = _ranked(1, "Keaton Sample", 88.0, prediction_sort_score=88.5)
    pick = _pick(selected)
    notes = [_matched_prospect_note(), _unrelated_prospect_note()]

    response = client.post("/api/evidence/pick", json=_payload(pick, manual_notes=notes))

    assert response.status_code == 200
    body = response.json()

    # Only the matched note survives.
    assert len(body["retrieved_evidence"]) == 1
    assert body["retrieved_evidence"][0]["source_id"] == "42"

    manual_citations = [
        c for c in body["citations"]
        if c.get("evidence_source_type") == "manual_note"
    ]
    assert len(manual_citations) == 1
    assert manual_citations[0]["source_id"] == "42"

    # The unrelated note must not leak anywhere in the response.
    serialized = json.dumps(body, ensure_ascii=False)
    assert "Wrong player note" not in serialized
    assert "This note should not appear." not in serialized
    assert '"99"' not in serialized


def test_api_without_manual_notes_preserves_legacy_contract() -> None:
    """Omitting manual_notes keeps retrieved_evidence empty and decision stable."""
    selected = _ranked(1, "Keaton Sample", 88.0, prediction_sort_score=88.5)
    pick = _pick(selected)

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()

    assert body["retrieved_evidence"] == []
    assert body["selected_player_id"] == 1
    assert body["selected_player_name"] == "Keaton Sample"
    assert body["ranking_evidence"]["final_score"] == 88.0
    assert body["ranking_evidence"]["prediction_sort_score"] == 88.5
    assert body["decision_locked"] is True
    assert body["llm_can_modify_decision"] is False

    manual_citations = [
        c for c in body["citations"]
        if c.get("evidence_source_type") == "manual_note"
    ]
    assert manual_citations == []


def test_api_manual_note_response_has_no_dangerous_fields() -> None:
    """No override / reranking / replacement fields may appear in the response."""
    selected = _ranked(1, "Keaton Sample", 88.0, prediction_sort_score=88.5)
    pick = _pick(selected)
    note = _matched_prospect_note()

    response = client.post("/api/evidence/pick", json=_payload(pick, manual_notes=[note]))

    assert response.status_code == 200
    body = response.json()

    serialized = json.dumps(body, ensure_ascii=False)
    for field in DANGEROUS_FIELDS:
        assert f'"{field}"' not in serialized, (
            f"dangerous field '{field}' must not appear in response"
        )


def test_api_manual_note_does_not_leak_into_other_evidence_blocks() -> None:
    """Manual notes must only land in retrieved_evidence / citations."""
    selected = _ranked(1, "Keaton Sample", 88.0, prediction_sort_score=88.5)
    pick = _pick(selected)
    note = _matched_prospect_note()

    response = client.post("/api/evidence/pick", json=_payload(pick, manual_notes=[note]))

    assert response.status_code == 200
    body = response.json()

    serialized = json.dumps(body, ensure_ascii=False)

    # Manual note identifiers must not appear inside other evidence blocks.
    ranking_block = json.dumps(body["ranking_evidence"], ensure_ascii=False)
    market_block = json.dumps(body["market_evidence"], ensure_ascii=False)
    risk_block = json.dumps(body["risk_evidence"], ensure_ascii=False)
    conflict_block = json.dumps(body["conflict_evidence"], ensure_ascii=False)

    for block_name, block_text in [
        ("ranking_evidence", ranking_block),
        ("market_evidence", market_block),
        ("risk_evidence", risk_block),
        ("conflict_evidence", conflict_block),
    ]:
        assert "Manual scouting note" not in block_text, (
            f"manual note must not leak into {block_name}"
        )
        assert "Strong defensive range." not in block_text, (
            f"manual note excerpt must not leak into {block_name}"
        )
        assert "manual_note" not in block_text, (
            f"manual_note source type must not leak into {block_name}"
        )

    # Sanity: the manual note does appear in retrieved_evidence / citations.
    assert "Manual scouting note" in serialized
    assert "manual_note" in serialized
