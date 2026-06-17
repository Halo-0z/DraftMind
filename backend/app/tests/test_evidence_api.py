from fastapi.testclient import TestClient

from app.main import app
from app.schemas.evidence import ManualNote
from app.schemas.prospect import ProspectRead
from app.schemas.recommendation import RankedProspectRead, ScoreBreakdown
from app.schemas.simulation import SimulateResponse, SimulatedPickRead, TradeEvaluation
from app.schemas.team import TeamRead


client = TestClient(app)


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
    market_expected_pick: int | None = 5,
    market_pick_delta: int | None = 0,
    market_alignment_label: str | None = "一致",
    market_alignment_notes: list[str] | None = None,
    diagnostics_warnings: list[str] | None = None,
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
        projection_expected_pick=market_expected_pick,
        projection_draft_range_min=4 if market_expected_pick else None,
        projection_draft_range_max=8 if market_expected_pick else None,
        projection_confidence=0.8 if market_expected_pick else None,
        projection_source="manual_projection" if market_expected_pick else None,
        market_expected_pick=market_expected_pick,
        draftmind_selected_pick=5,
        market_pick_delta=market_pick_delta,
        market_alignment_label=market_alignment_label,
        market_alignment_notes=(
            market_alignment_notes
            if market_alignment_notes is not None
            else ["市场预计约第 5 顺位。"]
        ),
        diagnostics_warnings=diagnostics_warnings,
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


def _payload(pick: SimulatedPickRead, *, manual_notes: list[ManualNote] | None = None) -> dict:
    simulation = SimulateResponse(
        year=2026,
        rounds=1,
        total_picks=1,
        source="test",
        picks=[pick],
        market_top30_missing_warnings=[],
    )
    payload = {
        "simulation": simulation.model_dump(),
        "pick": pick.model_dump(),
    }
    if manual_notes is not None:
        payload["manual_notes"] = [note.model_dump() for note in manual_notes]
    return payload


def _note(**overrides) -> ManualNote:
    defaults = {
        "year": 2026,
        "entity_type": "prospect",
        "entity_id": 1,
        "prospect_id": 1,
        "title": "Workout observation",
        "body": "The player showed advanced passing feel in transition.",
        "summary": "Passing feel note.",
        "confidence": 0.8,
    }
    defaults.update(overrides)
    return ManualNote(**defaults)


def test_pick_evidence_api_returns_package_for_simulated_pick() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    assert body["decision_locked"] is True
    assert body["llm_can_modify_decision"] is False
    assert body["selected_player_name"] == "Keaton Sample"
    assert body["ranking_evidence"]["final_score"] == 82.0


def test_pick_evidence_api_surfaces_market_missing_and_diagnostics() -> None:
    pick = _pick(
        _ranked(
            1,
            "No Market Player",
            82.0,
            market_expected_pick=None,
            market_pick_delta=None,
            market_alignment_label="无市场参考",
            market_alignment_notes=["暂无市场顺位参考。"],
            diagnostics_warnings=[
                "Low-confidence imported stats used in ranking context."
            ],
        )
    )

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    assert body["market_evidence"]["has_market_reference"] is False
    assert body["evidence_sufficiency"]["level"] == "limited"
    assert body["risk_evidence"]["diagnostics_warnings"] == [
        "Low-confidence imported stats used in ranking context."
    ]
    conflict_types = {item["type"] for item in body["conflict_evidence"]}
    assert "missing_market_reference" in conflict_types
    assert "diagnostics_warning" in conflict_types


def test_pick_evidence_api_does_not_return_recommendation_fields() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    forbidden_fields = {
        "recommended_player",
        "replacement_player",
        "new_selected_player",
        "rerank_score",
    }
    assert forbidden_fields.isdisjoint(response.json())


def test_pick_evidence_api_does_not_call_ranking_engine(monkeypatch) -> None:
    def fail_rank_prospects(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("Evidence API must not call ranking_engine")

    monkeypatch.setattr(
        "app.services.ranking_engine.rank_prospects",
        fail_rank_prospects,
    )
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    assert response.json()["selected_player_name"] == "Keaton Sample"


def test_pick_evidence_api_returns_retrieved_evidence_slot() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    assert "retrieved_evidence" in body
    assert body["retrieved_evidence"] == []


def test_pick_evidence_api_retrieved_evidence_default_is_independent_list() -> None:
    pick_a = _pick(_ranked(1, "Player A", 82.0))
    pick_b = _pick(_ranked(4, "Player B", 80.0))

    response_a = client.post("/api/evidence/pick", json=_payload(pick_a))
    response_b = client.post("/api/evidence/pick", json=_payload(pick_b))

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    body_a = response_a.json()
    body_b = response_b.json()
    assert body_a["retrieved_evidence"] == []
    assert body_b["retrieved_evidence"] == []
    assert body_a["retrieved_evidence"] is not body_b["retrieved_evidence"]


def test_pick_evidence_api_retrieved_evidence_does_not_change_selected_player() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    assert body["retrieved_evidence"] == []
    assert body["selected_player_name"] == "Keaton Sample"
    assert body["selected_player_id"] == 1


def test_pick_evidence_api_retrieved_evidence_does_not_change_ranking_scores() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    assert body["retrieved_evidence"] == []
    assert body["ranking_evidence"]["final_score"] == 82.0
    assert body["ranking_evidence"]["prediction_sort_score"] is None


def test_pick_evidence_api_retrieved_evidence_does_not_call_ranking_engine(
    monkeypatch,
) -> None:
    def fail_rank_prospects(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("Evidence API must not call ranking_engine")

    monkeypatch.setattr(
        "app.services.ranking_engine.rank_prospects",
        fail_rank_prospects,
    )
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    assert response.json()["retrieved_evidence"] == []


def test_pick_evidence_api_retrieved_evidence_does_not_expose_override_fields() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    forbidden_fields = {
        "recommended_player",
        "replacement_player",
        "new_selected_player",
        "rerank_score",
        "new_score",
        "selection_override",
    }
    assert forbidden_fields.isdisjoint(body)
    assert body["retrieved_evidence"] == []


def test_api_without_manual_notes_keeps_legacy_behavior() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    assert body["retrieved_evidence"] == []
    manual_citations = [
        c for c in body["citations"]
        if c.get("evidence_source_type") == "manual_note"
    ]
    assert manual_citations == []


def test_api_with_matched_manual_notes_returns_retrieved_evidence() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))
    note = _note(note_id=42, entity_type="prospect", prospect_id=1, entity_id=1)

    response = client.post("/api/evidence/pick", json=_payload(pick, manual_notes=[note]))

    assert response.status_code == 200
    body = response.json()
    assert len(body["retrieved_evidence"]) == 1
    retrieved = body["retrieved_evidence"][0]
    assert retrieved["source_type"] == "manual_note"
    assert retrieved["source_id"] == "42"
    assert retrieved["entity_type"] == "prospect"
    assert retrieved["entity_id"] == 1
    assert retrieved["evidence_only"] is True


def test_api_with_matched_manual_notes_returns_citation() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))
    note = _note(note_id=42, entity_type="prospect", prospect_id=1)

    response = client.post("/api/evidence/pick", json=_payload(pick, manual_notes=[note]))

    assert response.status_code == 200
    body = response.json()
    manual_citations = [
        c for c in body["citations"]
        if c.get("evidence_source_type") == "manual_note"
    ]
    assert len(manual_citations) == 1
    assert manual_citations[0]["source_id"] == "42"
    assert manual_citations[0]["source_type"] == "manual"
    assert manual_citations[0]["evidence_only"] is True


def test_api_ignores_unrelated_manual_notes() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))
    note = _note(entity_type="prospect", prospect_id=999, entity_id=999)

    response = client.post("/api/evidence/pick", json=_payload(pick, manual_notes=[note]))

    assert response.status_code == 200
    body = response.json()
    assert body["retrieved_evidence"] == []
    manual_citations = [
        c for c in body["citations"]
        if c.get("evidence_source_type") == "manual_note"
    ]
    assert manual_citations == []


def test_api_with_manual_notes_does_not_call_ranking_engine(monkeypatch) -> None:
    def fail_rank_prospects(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("Evidence API must not call ranking_engine")

    monkeypatch.setattr(
        "app.services.ranking_engine.rank_prospects",
        fail_rank_prospects,
    )
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))
    note = _note(entity_type="prospect", prospect_id=1)

    response = client.post("/api/evidence/pick", json=_payload(pick, manual_notes=[note]))

    assert response.status_code == 200
    assert len(response.json()["retrieved_evidence"]) == 1


def test_api_with_manual_notes_does_not_change_decision_or_scores() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))
    note = _note(entity_type="prospect", prospect_id=1)

    response = client.post("/api/evidence/pick", json=_payload(pick, manual_notes=[note]))

    assert response.status_code == 200
    body = response.json()
    assert body["selected_player_name"] == "Keaton Sample"
    assert body["selected_player_id"] == 1
    assert body["ranking_evidence"]["final_score"] == 82.0
    assert body["ranking_evidence"]["prediction_sort_score"] is None
    assert body["decision_locked"] is True
    assert body["llm_can_modify_decision"] is False


def test_api_with_manual_notes_does_not_expose_dangerous_fields() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))
    note = _note(entity_type="prospect", prospect_id=1)

    response = client.post("/api/evidence/pick", json=_payload(pick, manual_notes=[note]))

    assert response.status_code == 200
    body = response.json()
    forbidden_fields = {
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
    assert forbidden_fields.isdisjoint(body)
    for retrieved in body["retrieved_evidence"]:
        assert forbidden_fields.isdisjoint(retrieved)
    for citation in body["citations"]:
        assert forbidden_fields.isdisjoint(citation)
