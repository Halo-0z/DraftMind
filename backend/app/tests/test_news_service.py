from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.models import NewsArticle, Prospect, ScoutingReport
from app.services.news_service import (
    PROSPECT_HINT_TOKENS,
    _fetch_hupu_voice,
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


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def __init__(self, html: str) -> None:
        self.html = html

    def get(self, *_args, **_kwargs) -> _FakeResponse:
        return _FakeResponse(self.html)


def test_fetch_hupu_voice_filters_ordinary_bbs_posts() -> None:
    source = {
        "name": "Hupu Voice",
        "language": "zh",
        "kind": "hupu_voice",
        "feed": "https://voice.hupu.com/nba",
    }
    html = """
    <html><body>
      <a href="https://bbs.hupu.com/639782144.html">6-7，今日曼巴篮球数据方向</a>
      <a href="https://bbs.hupu.com/639776297.html">你是怎么找篮球组队的？</a>
      <a href="https://bbs.hupu.com/639843329.html">NBA历史前十球员排名</a>
      <a href="https://voice.hupu.com/nba/1">今日五佳球：比赛集锦</a>
      <a href="https://voice.hupu.com/nba/2">赛后采访：球员谈球队表现</a>
      <a href="https://voice.hupu.com/nba/3">伤病报告：球队更新轮换</a>
      <a href="https://bbs.hupu.com/639800000.html">[流言板] 湖人有意得到老将控卫</a>
    </body></html>
    """

    out = _fetch_hupu_voice(source, _FakeSession(html))

    assert out == []


def test_fetch_hupu_voice_keeps_draft_context_articles() -> None:
    source = {
        "name": "Hupu Voice",
        "language": "zh",
        "kind": "hupu_voice",
        "feed": "https://voice.hupu.com/nba",
    }
    html = """
    <html><body>
      <a href="/nba/639900001.html">[流言板] 湖人试训新秀 Cooper Flagg</a>
      <a href="https://voice.hupu.com/nba/639900002.html">[流言板] 黄蜂有意在14号签选择 Chris Cenac Jr.</a>
      <a href="https://bbs.hupu.com/639900003.html">[流言板] 爵士考虑向上交易换取5号签</a>
      <a title="[流言板] Dybantsa 选秀行情上涨" href="https://voice.hupu.com/nba/639900004.html"></a>
    </body></html>
    """

    out = _fetch_hupu_voice(source, _FakeSession(html))
    titles = [item["title"] for item in out]
    urls = {item["url"] for item in out}

    assert len(out) == 4
    assert any("湖人试训新秀 Cooper Flagg" in title for title in titles)
    assert any("黄蜂有意在14号签选择 Chris Cenac Jr." in title for title in titles)
    assert any("爵士考虑向上交易换取5号签" in title for title in titles)
    assert any("Dybantsa 选秀行情上涨" in title for title in titles)
    assert "https://voice.hupu.com/nba/639900001.html" in urls
    assert "https://bbs.hupu.com/639900003.html" in urls


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


def test_search_articles_draftmind_only_filters_public_news_noise(db_session: Session) -> None:
    rejected_titles = [
        "NBA Finals Game 4: Anatomy of Knicks comeback",
        "Knicks on brink of title after historic comeback vs Spurs",
        "Knicks make history with 29-point comeback vs Spurs",
        "2026 NBA playoffs: Schedule, scores, news and highlights",
        "NBA championship and Finals MVP odds",
        "Fantasy basketball: rookies to target this season",
        "6-7，今日曼巴篮球数据方向",
        "你是怎么找篮球组队的？",
        "原创 | NBA历史前十球员排名",
        "今日五佳球：比赛集锦",
        "赛后采访：球员谈球队表现",
    ]
    kept_titles = [
        "2026 NBA mock draft: top prospects",
        "Lakers hosted Cooper Flagg for pre-draft workout",
        "Hornets linked to Chris Cenac Jr. at No. 14",
        "Dybantsa draft stock rising after combine measurements",
        "湖人试训新秀 Cooper Flagg",
        "黄蜂有意在14号签选择 Chris Cenac Jr.",
        "Dybantsa 选秀行情上涨",
    ]
    for idx, title in enumerate(rejected_titles + kept_titles):
        upsert_article(
            db_session,
            _build_article(
                url=f"https://example.com/display-filter/{idx}",
                title=title,
                language="zh" if any("\u4e00" <= char <= "\u9fff" for char in title) else "en",
                days_ago=0,
            ),
        )
    db_session.commit()

    results = search_articles(db_session, limit=50, draftmind_only=True)
    titles = {article.title for article in results}

    assert titles.isdisjoint(rejected_titles)
    assert set(kept_titles).issubset(titles)


def test_search_articles_default_keeps_raw_cache_scope(db_session: Session) -> None:
    title = "NBA Finals Game 4: Anatomy of Knicks comeback"
    upsert_article(
        db_session,
        _build_article(
            url="https://example.com/raw-cache/finals",
            title=title,
            language="en",
            days_ago=0,
        ),
    )
    db_session.commit()

    results = search_articles(db_session, limit=5)

    assert [article.title for article in results] == [title]


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
