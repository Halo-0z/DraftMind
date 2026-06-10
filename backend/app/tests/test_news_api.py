import pytest
from fastapi.testclient import TestClient

from app.models import NewsArticle


def test_news_list_returns_empty_when_no_articles(client: TestClient) -> None:
    response = client.get("/api/news")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["articles"] == []


def test_news_refresh_is_idempotent(client: TestClient, db_session, monkeypatch) -> None:
    captured: dict[str, int] = {"calls": 0}

    def _fake_fetch(db, *, limit=None, refresh=False):  # noqa: ANN001
        captured["calls"] += 1
        article = NewsArticle(
            source="Hupu NBA",
            title="2026 选秀联合试训前瞻",
            summary="Dybantsa 继续领跑。",
            url=f"https://example.com/news/{captured['calls']}",
            author=None,
            language="zh",
            published_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            fetched_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            body_excerpt="Dybantsa 继续领跑 2026 模拟选秀榜。",
            prospect_names="Dybantsa",
            team_abbrs="WAS",
        )
        db.add(article)
        db.commit()
        return [article]

    monkeypatch.setattr(
        "app.routers.news.fetch_recent_articles",
        _fake_fetch,
    )

    response = client.post("/api/news/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert captured["calls"] == 1

    follow_up = client.get("/api/news?prospect=Aj%20Dybantsa")
    assert follow_up.status_code == 200
    assert follow_up.json()["total"] >= 1
