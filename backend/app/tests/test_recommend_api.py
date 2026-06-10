from fastapi.testclient import TestClient


def test_recommend_pick_by_team_abbr(client: TestClient) -> None:
    response = client.post(
        "/api/recommend",
        json={
            "year": 2026,
            "team": "SAS",
            "pick": 8,
            "mode": "gm_decision",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["team"]["abbr"] == "SAS"
    assert body["recommended_player"]["scores"]["final_score"] > 0
    assert len(body["alternatives"]) == 1
    assert body["recommended_player"]["reasons"]


def test_recommend_requires_team(client: TestClient) -> None:
    response = client.post("/api/recommend", json={"year": 2026, "pick": 8})

    assert response.status_code == 422
