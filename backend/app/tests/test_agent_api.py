from fastapi.testclient import TestClient


def test_agent_ask_returns_mock_explanation(client: TestClient) -> None:
    response = client.post(
        "/api/agent/ask",
        json={
            "year": 2026,
            "team": "SAS",
            "pick": 8,
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
    response = client.post(
        "/api/agent/ask",
        json={
            "year": 2026,
            "team": "SAS",
            "pick": 8,
            "question": "为什么不选 Braylon Mullins？",
        },
    )

    assert response.status_code == 200
    answer = response.json()["explanation"]["follow_up_answer"]
    assert "Braylon Mullins" in answer
    assert "Mikel Brown Jr." in answer
