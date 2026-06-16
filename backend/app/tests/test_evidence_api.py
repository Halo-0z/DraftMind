from fastapi.testclient import TestClient

from app.main import app
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


def _payload(pick: SimulatedPickRead) -> dict:
    simulation = SimulateResponse(
        year=2026,
        rounds=1,
        total_picks=1,
        source="test",
        picks=[pick],
        market_top30_missing_warnings=[],
    )
    return {
        "simulation": simulation.model_dump(),
        "pick": pick.model_dump(),
    }


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
