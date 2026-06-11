from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.models import NewsArticle


def _article(*, title: str, url: str, language: str = "en") -> NewsArticle:
    now = datetime.now(timezone.utc)
    return NewsArticle(
        source="ESPN NBA News" if language == "en" else "Hupu Voice",
        title=title,
        summary="",
        url=url,
        author=None,
        language=language,
        published_at=now,
        fetched_at=now,
        body_excerpt="",
        prospect_names="",
        team_abbrs="",
    )


def test_news_list_returns_empty_when_no_articles(client: TestClient) -> None:
    response = client.get("/api/news")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["articles"] == []


def test_news_list_returns_only_draftmind_relevant_articles(
    client: TestClient,
    db_session,
) -> None:
    rejected_titles = [
        "NBA Finals Game 4: Anatomy of Knicks comeback",
        "Fantasy basketball: rookies to target this season",
        "原创 | NBA历史前十球员排名",
    ]
    kept_titles = [
        "2026 NBA mock draft: top prospects",
        "湖人试训新秀 Cooper Flagg",
    ]
    for idx, title in enumerate(rejected_titles + kept_titles):
        db_session.add(
            _article(
                title=title,
                url=f"https://example.com/api-news/{idx}",
                language="zh" if any("\u4e00" <= char <= "\u9fff" for char in title) else "en",
            )
        )
    db_session.commit()

    response = client.get("/api/news?limit=20")

    assert response.status_code == 200
    titles = {article["title"] for article in response.json()["articles"]}
    assert titles.isdisjoint(rejected_titles)
    assert set(kept_titles).issubset(titles)


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
            published_at=datetime.now(timezone.utc),
            fetched_at=datetime.now(timezone.utc),
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


def test_news_refresh_response_filters_public_news_noise(
    client: TestClient,
    db_session,
    monkeypatch,
) -> None:
    def _fake_fetch(db, *, limit=None, refresh=False):  # noqa: ANN001
        bad = _article(
            title="NBA Finals Game 4: Anatomy of Knicks comeback",
            url="https://example.com/refresh/finals",
        )
        good = _article(
            title="Hornets linked to Chris Cenac Jr. at No. 14",
            url="https://example.com/refresh/draft",
        )
        db.add_all([bad, good])
        db.commit()
        return [bad, good]

    monkeypatch.setattr(
        "app.routers.news.fetch_recent_articles",
        _fake_fetch,
    )

    response = client.post("/api/news/refresh?limit=20")

    assert response.status_code == 200
    titles = {article["title"] for article in response.json()["articles"]}
    assert "NBA Finals Game 4: Anatomy of Knicks comeback" not in titles
    assert "Hornets linked to Chris Cenac Jr. at No. 14" in titles
