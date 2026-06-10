from fastapi.testclient import TestClient


def test_list_prospects_by_year(client: TestClient) -> None:
    response = client.get("/api/prospects?year=2026")

    assert response.status_code == 200
    prospects = response.json()
    assert len(prospects) == 2
    assert prospects[0]["name"] == "Mikel Brown Jr."
    assert prospects[0]["upside_score"] == 86
