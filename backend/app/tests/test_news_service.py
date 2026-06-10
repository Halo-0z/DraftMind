from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.models import NewsArticle, Prospect, ScoutingReport
from app.services.news_service import (
    PROSPECT_HINT_TOKENS,
    fetch_recent_articles,
    search_articles,
    upsert_article,
)
from app.services.rag_service import build_prospect_context_block


def _build_article(
    *,
    url: str,
    title: str,
    summary: str = "",
    body: str = "",
    source: str = "Hupu NBA",
    language: str = "zh",
    days_ago: int = 1,
    prospects: str = "",
    teams: str = "",
) -> NewsArticle:
    now = datetime.now(timezone.utc)
    return NewsArticle(
        source=source,
        title=title,
        summary=summary,
        url=url,
        author=None,
        language=language,
        published_at=now - timedelta(days=days_ago),
        fetched_at=now,
        body_excerpt=body or summary,
        prospect_names=prospects,
        team_abbrs=teams,
    )


def test_upsert_article_is_idempotent(db_session: Session) -> None:
    article = _build_article(
        url="https://example.com/a1",
        title="迪班察试训表现出色",
        summary="杨百翰前锋试训全中。",
        prospects="Dybantsa",
    )
    first = upsert_article(db_session, article)
    db_session.commit()
    second = upsert_article(
        db_session,
        _build_article(
            url="https://example.com/a1",
            title="迪班察试训表现出色 (更新)",
            summary="更新摘要。",
            prospects="Dybantsa",
        ),
    )
    db_session.commit()

    assert first.id == second.id
    assert second.title.endswith("(更新)")
    assert db_session.query(NewsArticle).count() == 1


def test_search_article_scores_match_by_name_and_team(db_session: Session) -> None:
    upsert_article(
        db_session,
        _build_article(
            url="https://example.com/sas-news",
            title="马刺球探考察 BYU 新秀",
            summary="圣安东尼奥本周考察 Dybantsa。",
            prospects="Dybantsa",
            teams="SAS",
        ),
    )
    upsert_article(
        db_session,
        _build_article(
            url="https://example.com/unrelated",
            title="火箭 2026 计划",
            summary="Houston 计划灵活。",
            teams="HOU",
        ),
    )
    db_session.commit()

    results = search_articles(
        db_session,
        prospect_name="AJ Dybantsa",
        team_abbr="SAS",
        language="zh",
        limit=5,
    )
    assert results
    assert results[0].url.endswith("sas-news")


def test_search_articles_ignores_empty_query(db_session: Session) -> None:
    assert search_articles(db_session, limit=5) == []


def test_fetch_recent_articles_handles_unreachable_sources(
    db_session: Session, monkeypatch
) -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated network failure")

    # Force every registered fetcher to fail and confirm the dispatcher
    # swallows the error and returns an empty list.
    import app.services.news_service as svc

    monkeypatch.setattr(
        svc,
        "FETCHERS",
        {kind: _boom for kind in ("espn_json", "hupu_html", "sina_html", "sohu_html")},
    )
    articles = fetch_recent_articles(db=db_session, refresh=True)
    assert articles == []


def test_rag_block_uses_scouting_report_and_news(db_session: Session) -> None:
    prospect = Prospect(
        year=2026,
        name="AJ Dybantsa",
        position="SF",
        age=19.0,
        height="6-9",
        weight=210,
        school_or_league="BYU",
        ppg=21.0,
        rpg=7.5,
        apg=3.4,
        fg_pct=49.0,
        three_pct=35.0,
        ft_pct=78.0,
        stocks=2.0,
        archetype="Two-way wing creator",
        upside_score=95,
        risk_score=28,
    )
    db_session.add(prospect)
    db_session.flush()
    db_session.add(
        ScoutingReport(
            prospect_id=prospect.id,
            source="DraftMind Mock",
            report_text="迪班察是本届最高天赋翼侧。",
        )
    )
    upsert_article(
        db_session,
        _build_article(
            url="https://example.com/dybantsa-news",
            title="迪班察领跑 2026 模拟选秀",
            summary="奇才状元签潜在目标。",
            prospects="Dybantsa",
            teams="WAS",
        ),
    )
    db_session.commit()

    block = build_prospect_context_block(
        db_session,
        prospect=prospect,
        team_abbr="SAS",
    )
    assert "球探报告" in block
    assert "迪班察领跑" in block
    assert "未提供" not in block  # we never claim missing stats


def test_prospect_hint_tokens_cover_known_prospects() -> None:
    # Sanity check so the heuristic matcher keeps up with the seed list.
    expected = {"Dybantsa", "Peterson", "Boozer", "Wilson"}
    assert expected.issubset(set(PROSPECT_HINT_TOKENS))
