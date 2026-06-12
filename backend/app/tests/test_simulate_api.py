from fastapi.testclient import TestClient

from app.models.draft import DraftOrder
from app.models.prospect import Prospect
from app.models.report import ScoutingReport
from app.models.team import TeamNeed


def test_simulate_draft_returns_unique_players(client: TestClient, db_session) -> None:
    # conftest already seeds pick_no 2,5,10,20 for year 2026.
    # Add pick_no 1 (the only one missing from the first few).
    db_session.add(DraftOrder(year=2026, pick_no=1, team_id=1))
    db_session.add(
        TeamNeed(
            team_id=2,
            year=2026,
            need_pg=4,
            need_sg=9,
            need_sf=4,
            need_pf=2,
            need_c=1,
            need_shooting=8,
            need_defense=4,
            need_creation=6,
        )
    )
    third = Prospect(
        year=2026,
        name="Third Prospect",
        position="SF",
        age=19.0,
        height="6-7",
        weight=205,
        school_or_league="Mock",
        ppg=15.0,
        rpg=5.0,
        apg=3.0,
        fg_pct=45.0,
        three_pct=35.0,
        ft_pct=78.0,
        stocks=1.4,
        archetype="Connector wing",
        upside_score=74,
        risk_score=22,
    )
    db_session.add(third)
    db_session.flush()
    db_session.add(
        ScoutingReport(
            prospect_id=third.id,
            source="Test",
            report_text="Test report",
        )
    )
    db_session.commit()

    response = client.post(
        "/api/simulate",
        json={"year": 2026, "rounds": 1, "limit": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_picks"] == 2
    names = [pick["selected_player"]["prospect"]["name"] for pick in body["picks"]]
    assert len(names) == len(set(names))
    assert body["picks"][0]["pick"] == 1
    assert body["picks"][1]["pick"] == 2
    # pick_no=2 comes from conftest (SAS, notes=None)
    assert body["picks"][1]["draft_order_note"] is None
    assert body["picks"][0]["candidate_board"]
    assert body["picks"][0]["trade_evaluation"]["action"]
    assert body["picks"][0]["decision_log"]
    selected = body["picks"][0]["selected_player"]
    assert selected["prospect"]["name"]
    assert selected["scores"]["final_score"] is not None
    assert selected["reasons"]
    assert selected["risks"]
    assert "scouting_fit_score" in selected
    assert "scouting_tiebreaker_applied" in selected
    assert selected["scouting_tiebreaker_applied"] is False
