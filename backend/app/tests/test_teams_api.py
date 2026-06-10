from fastapi.testclient import TestClient


def test_list_teams(client: TestClient) -> None:
    response = client.get("/api/teams")

    assert response.status_code == 200
    teams = response.json()
    assert len(teams) == 2
    assert teams[0]["abbr"] == "HOU"


def test_get_team_includes_needs(client: TestClient) -> None:
    response = client.get("/api/teams/1")

    assert response.status_code == 200
    body = response.json()
    assert body["abbr"] == "SAS"
    assert body["nba_team_id"] == 1610612759
    assert body["needs"][0]["need_pg"] == 9


def test_get_team_roster(client: TestClient) -> None:
    response = client.get("/api/teams/1/roster?season=2025-26")

    assert response.status_code == 200
    roster = response.json()
    assert len(roster) == 1
    assert roster[0]["player_name"] == "Victor Wembanyama"


def test_get_team_picks_orders_by_pick_no_and_exposes_origin(
    client: TestClient, db_with_team_picks
) -> None:
    # SAS owns #61 (own) and #70 (from ATL).  Endpoint should return
    # them earliest-first and include the original_team field so the
    # UI can show "来自 ATL".
    response = client.get("/api/teams/1/picks?year=2026")

    assert response.status_code == 200
    picks = response.json()
    assert [p["pick_no"] for p in picks] == [61, 70]
    assert picks[0]["original_team"] is None
    assert picks[1]["original_team"] == "ATL"
    assert picks[1]["notes"] == "from Atlanta"


def test_get_team_picks_404_for_unknown_team(client: TestClient) -> None:
    response = client.get("/api/teams/999999/picks?year=2026")
    assert response.status_code == 404


def test_get_team_picks_filters_by_year(
    client: TestClient, db_with_team_picks
) -> None:
    # No rows are seeded for 2025, so the response must be empty
    # (not error out, not leak 2026 data).
    response = client.get("/api/teams/1/picks?year=2025")
    assert response.status_code == 200
    assert response.json() == []
