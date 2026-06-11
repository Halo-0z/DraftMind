from __future__ import annotations

from datetime import datetime, timedelta
import logging
import re
from typing import Iterable, Protocol
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import NewsArticle, Prospect, Team


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source definitions — focused on TRADES, DRAFT, OFFSEASON moves
# ---------------------------------------------------------------------------
SOURCES: list[dict[str, str]] = [
    {
        "name": "ESPN NBA News",
        "language": "en",
        "kind": "espn_json",
        "feed": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news?limit=30",
    },
    {
        "name": "ESPN CBB Draft",
        "language": "en",
        "kind": "espn_json",
        "feed": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/news?limit=20",
    },
    {
        "name": "NBA Trade Tracker",
        "language": "en",
        "kind": "nba_trade_tracker",
        "feed": "https://www.nba.com/news/2025-26-nba-trade-tracker",
    },
    {
        "name": "Sportando NBA",
        "language": "en",
        "kind": "sportando",
        "feed": "https://sportando.basketball/en/category/usa/nba/",
    },
    {
        "name": "Hupu Voice",
        "language": "zh",
        "kind": "hupu_voice",
        "feed": "https://voice.hupu.com/nba",
    },
]


# ---------------------------------------------------------------------------
# Keywords & patterns
# ---------------------------------------------------------------------------
# Topics that indicate trade/draft/offseason relevance (used for boosting)
TRADE_TOPIC_KEYWORDS = [
    "trade", "traded", "deal", "acquire", "acquired", "send", "swap",
    "sign", "signed", "free agent", "waive", "waived", "buyout",
    "draft", "drafted", "pick", "prospect", "combine", "workout",
    "offseason", "free agency", "extension", "contract", "option",
    "rumor", "report", "source", "interested", "discussing",
    "injury", "injured", "out for season", "surgery",
    "nba trade deadline", "nba draft",
]

# Patterns that strongly indicate a GAME article (not trade/draft)
GAME_EXCLUDE_PATTERNS = [
    r"\[赛事\]", r"^Game \d+", r"watch party", r"how to watch",
    r"broadcast", r"tv channel", r"live stream",
    r"pregame", r"postgame", r"halftime", r"box score",
]


# ---------------------------------------------------------------------------
# Hint tokens for entity extraction
# ---------------------------------------------------------------------------
PROSPECT_HINT_TOKENS = [
    "Dybantsa", "Peterson", "Boozer", "Wilson", "Flemings",
    "Ament", "Peat", "Quaintance", "Harwell", "Acuff",
    "Cenac", "Khamenia", "Johnson", "Moreno", "Bundalo",
    "Thomas", "Gueye", "Mullins", "Wembanyama", "Doncic",
    "James", "Curry", "Durant", "Tatum", "Edwards", "Antetokounmpo",
    "Davis", "Harden", "Morant", "Kuminga", "Towns", "Brunson",
    "Garland", "Zubac", "Porzingis", "Ball", "McCain",
    "Middleton", "Russell", "Branham", "Bagley", "Hardy",
    "Exum", "Kennard", "Dieng", "Gordon", "Krejci",
    "Huerter", "Saric", "Ivey", "Dosunmu", "Paul",
    "Alvarado", "Hunter", "Tillman", "Boucher", "Jackson",
]

TEAM_HINT_TOKENS = [
    "WAS", "UTA", "MEM", "CHI", "LAC", "BKN", "SAC", "ATL",
    "DAL", "MIL", "GSW", "OKC", "MIA", "CHA", "TOR", "SAS",
    "HOU", "DET", "POR", "NYK", "LAL", "DEN", "BOS", "MIN",
    "CLE", "PHI", "PHX", "ORL", "IND", "NOP",
]

TEAM_CN_HINTS: dict[str, str] = {
    "湖人": "LAL", "勇士": "GSW", "火箭": "HOU", "凯尔特人": "BOS",
    "快船": "LAC", "热火": "MIA", "掘金": "DEN", "雄鹿": "MIL",
    "公牛": "CHI", "篮网": "BKN", "尼克斯": "NYK", "猛龙": "TOR",
    "马刺": "SAS", "太阳": "PHX", "独行侠": "DAL", "小牛": "DAL",
    "76人": "PHI", "森林狼": "MIN", "国王": "SAC", "鹈鹕": "NOP",
    "魔术": "ORL", "雷霆": "OKC", "爵士": "UTA", "灰熊": "MEM",
    "奇才": "WAS", "老鹰": "ATL", "黄蜂": "CHA", "步行者": "IND",
    "活塞": "DET", "开拓者": "POR", "骑士": "CLE",
}


HUPU_DRAFT_CONTEXT_KEYWORDS = [
    "选秀", "新秀", "签位", "号签", "试训", "行情", "乐透",
    "mock", "draft", "prospect", "pick", "workout", "combine",
]

HUPU_TOPIC_KEYWORDS = [
    "交易", "签约", "裁员", "买断", "自由球员", "选秀", "新秀",
    "合同", "续约", "报价", "有意", "询价", "追求", "离开", "加盟",
    "签位", "号签", "试训", "行情",
]

HUPU_NOISE_KEYWORDS = [
    "今日曼巴篮球数据方向", "怎么找篮球组队", "历史前十球员排名",
    "今日五佳球", "比赛集锦", "赛后采访", "伤病报告",
]

DRAFTMIND_NEWS_CONTEXT_KEYWORDS = [
    "draft", "mock draft", "prospect", "rookie", "lottery", "combine",
    "pre-draft", "predraft", "workout", "draft board", "draft stock",
    "measurement", "measurements", "pro day",
    "选秀", "新秀", "签位", "号签", "乐透", "试训", "行情", "联合试训", "体测",
]

DRAFTMIND_NEWS_NOISE_KEYWORDS = [
    "nba finals", "finals game", "game 4", "playoffs", "comeback", "collapse",
    "box score", "recap", "postgame", "highlights", "schedule",
    "how to watch", "fantasy", "dfs", "betting", "odds",
    "power ranking", "championship odds", "nba title", "long-awaited title",
    "title race", "championship",
    "历史排名", "历史前十", "组队", "篮球数据方向", "今日五佳球",
    "比赛集锦", "赛后采访", "普通伤病报告", "伤病报告",
]


class _Fetcher(Protocol):
    def __call__(self, source: dict[str, str], session: requests.Session) -> list[dict]: ...


# ---------------------------------------------------------------------------
# ESPN News JSON API — returns articles with real published timestamps
# ---------------------------------------------------------------------------
def _fetch_espn_json(source: dict[str, str], session: requests.Session) -> list[dict]:
    """ESPN's public site API returns a clean JSON envelope with `articles[]`.

    Articles are tagged with their real `published` timestamp from ESPN.
    We boost trade/draft-relevant articles and deprioritize pure game recaps.
    """
    settings = get_settings()
    resp = session.get(source["feed"], timeout=settings.news_fetch_timeout)
    resp.raise_for_status()
    payload = resp.json()
    out: list[dict] = []
    for art in payload.get("articles", []):
        headline = (art.get("headline") or art.get("title") or "").strip()
        description = (art.get("description") or "").strip()
        published = art.get("published") or art.get("lastModified") or ""
        url = ""
        links = art.get("links", {})
        if isinstance(links, dict):
            web = links.get("web") or links.get("mobile")
            if isinstance(web, dict):
                url = web.get("href") or web.get("self", {}).get("href", "")
        if not url and isinstance(art.get("link"), str):
            url = art["link"]
        if not headline or not url:
            continue
        # Check if article has trade/draft/offseason topic categories
        combined = f"{headline} {description}".lower()
        is_trade_relevant = any(kw in combined for kw in TRADE_TOPIC_KEYWORDS)
        has_trade_topic = False
        for cat in art.get("categories", []):
            cat_desc = (cat.get("description") or "").lower()
            if any(kw in cat_desc for kw in ["trade", "draft", "free agent", "offseason", "injury"]):
                has_trade_topic = True
                break
        # Skip pure game recaps (no trade/draft relevance at all)
        if _is_game_article(combined) and not is_trade_relevant and not has_trade_topic:
            continue
        # Map team categories into our team_abbrs.
        teams = []
        for cat in art.get("categories", []):
            if cat.get("type") == "team":
                abbr = _espn_team_id_to_abbr(cat.get("teamId"))
                if abbr and abbr not in teams:
                    teams.append(abbr)
        # Add a relevance tag so search_articles can boost it
        relevance_tag = ""
        if has_trade_topic or is_trade_relevant:
            relevance_tag = "[交易/选秀] "
        out.append({
            "title": f"{relevance_tag}{headline}",
            "summary": description[:500],
            "url": url,
            "published_at": _parse_iso(published) or datetime.utcnow(),
            "author": art.get("byline") or None,
            "team_abbrs": ",".join(teams),
        })
    return out


# ---------------------------------------------------------------------------
# NBA.com Trade Tracker — extract real dates from HTML
# ---------------------------------------------------------------------------
# Month name → number for parsing "Feb. 5" style dates
_MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def _parse_nba_date(text: str, season_year: int = 2026) -> datetime | None:
    """Parse date strings like 'Feb. 5', 'February 6, 2026', 'Updated on February 6, 2026'.

    season_year is the second year of the NBA season (e.g. 2026 for 2025-26).
    NBA season runs Oct-Jun, so months Oct-Dec belong to the first year (2025),
    and Jan-Jun belong to the second year (2026).
    """
    # Try "Month Day, Year" (explicit year)
    m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})", text, re.IGNORECASE)
    if m:
        month = _MONTH_MAP.get(m.group(1).lower())
        if month:
            return datetime(int(m.group(3)), month, int(m.group(2)))
    # Try "Mon. Day" (e.g. "Feb. 5") — infer year from season
    m = re.search(r"\(?(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+(\d{1,2})\)?", text, re.IGNORECASE)
    if m:
        month = _MONTH_MAP.get(m.group(1).lower())
        if month:
            # Oct-Dec → first year of season; Jan-Sep → second year
            year = season_year - 1 if month >= 10 else season_year
            return datetime(year, month, int(m.group(2)))
    return None


def _fetch_nba_trade_tracker(source: dict[str, str], session: requests.Session) -> list[dict]:
    """Scrape NBA.com's trade tracker page for completed trade details.

    Extracts real publication dates from the HTML so that old trades
    (e.g. from Feb 2026 deadline) are not mislabeled as "today".
    """
    settings = get_settings()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = session.get(source["feed"], headers=headers, timeout=settings.news_fetch_timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")
    out: list[dict] = []
    seen_urls: set[str] = set()

    # Try to find the page-level "Updated on" date as a fallback
    page_date: datetime | None = None
    page_text = soup.get_text(" ", strip=True)
    page_date_match = re.search(r"Updated on\s+(.+?\d{4})", page_text)
    if page_date_match:
        page_date = _parse_nba_date(page_date_match.group(1))

    # NBA.com trade tracker uses <a> links to individual trade articles
    # Each trade section often has a date like "(Feb. 5)" before the link
    for a in soup.select("a[href*='/news/']"):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href or not title or len(title) < 8 or len(title) > 300:
            continue
        # Only keep links that look like trade articles
        combined = title.lower()
        if not any(kw in combined for kw in ["trade", "traded", "deal", "acquire", "sign", "waive", "buyout", "land", "add", "deal"]):
            continue
        if href.startswith("/"):
            href = f"https://www.nba.com{href}"
        elif not href.startswith("http"):
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        # Try to find a date near this link — look at preceding siblings/parent text
        published_at = _extract_nearby_date(a) or page_date or datetime.utcnow()
        out.append({
            "title": f"[交易] {title}",
            "summary": "",
            "url": href,
            "published_at": published_at,
            "author": None,
            "team_abbrs": "",
        })

    # Also try Article structured content
    for article in soup.select("article, [class*='Article']"):
        a = article.select_one("a[href]")
        if not a:
            continue
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href or not title or len(title) < 8 or len(title) > 300:
            continue
        combined = title.lower()
        if not any(kw in combined for kw in ["trade", "traded", "deal", "acquire", "sign", "waive"]):
            continue
        if href.startswith("/"):
            href = f"https://www.nba.com{href}"
        elif not href.startswith("http"):
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        # Try to find a date in the article
        published_at = datetime.utcnow()
        time_el = article.select_one("time")
        if time_el and time_el.get("datetime"):
            parsed = _parse_iso(time_el["datetime"])
            if parsed:
                published_at = parsed
        else:
            article_text = article.get_text(" ", strip=True)
            nearby = _parse_nba_date(article_text)
            if nearby:
                published_at = nearby
            elif page_date:
                published_at = page_date
        out.append({
            "title": f"[交易] {title}",
            "summary": "",
            "url": href,
            "published_at": published_at,
            "author": None,
            "team_abbrs": "",
        })

    return out[:30]


def _extract_nearby_date(element) -> datetime | None:
    """Walk up and sideways from an element to find a date string like '(Feb. 5)'."""
    # Check previous siblings
    for sib in element.previous_siblings:
        if isinstance(sib, str):
            d = _parse_nba_date(sib)
            if d:
                return d
        elif hasattr(sib, "get_text"):
            d = _parse_nba_date(sib.get_text())
            if d:
                return d
    # Check parent's text for a nearby date
    parent = element.parent
    if parent:
        parent_text = parent.get_text(" ", strip=True)
        # Look for "(Month Day)" pattern near the link text
        m = re.search(r"\((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}\)", parent_text, re.IGNORECASE)
        if m:
            d = _parse_nba_date(m.group(0))
            if d:
                return d
    return None


# ---------------------------------------------------------------------------
# Sportando — Professional NBA trade/draft rumor aggregator
# ---------------------------------------------------------------------------
def _fetch_sportando(source: dict[str, str], session: requests.Session) -> list[dict]:
    """Scrape Sportando basketball news for NBA trade/draft rumors.

    Sportando is a professional basketball news aggregator with real-time
    NBA trade rumors sourced from Shams, Fischer, Stein, etc.
    """
    settings = get_settings()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = session.get(source["feed"], headers=headers, timeout=settings.news_fetch_timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")
    out: list[dict] = []
    seen_urls: set[str] = set()

    # Sportando uses <article> or <h2><a> patterns for news items
    for a in soup.select("article a[href], h2 a[href], .post-title a[href]"):
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not href or not title or len(title) < 10 or len(title) > 300:
            continue
        combined = title.lower()
        # Only keep NBA-related articles (trade/draft/offseason)
        if not any(kw in combined for kw in ["trade", "deal", "sign", "draft", "pick", "free agent",
                                              "waive", "buyout", "contract", "extension", "rumor",
                                              "acquire", "offseason", "nbas", "nba"]):
            continue
        if _is_game_article(combined):
            continue
        if href.startswith("/"):
            href = f"https://sportando.basketball{href}"
        elif not href.startswith("http"):
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        # Try to extract date from nearby <time> or date text
        published_at = datetime.utcnow()
        parent = a.find_parent("article") or a.find_parent()
        if parent:
            time_el = parent.select_one("time")
            if time_el and time_el.get("datetime"):
                parsed = _parse_iso(time_el["datetime"])
                if parsed:
                    published_at = parsed
            else:
                # Try "DD/MM/YYYY HH:MM" format used by Sportando
                date_match = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})", parent.get_text(" ", strip=True))
                if date_match:
                    try:
                        published_at = datetime.strptime(f"{date_match.group(1)} {date_match.group(2)}", "%d/%m/%Y %H:%M")
                    except ValueError:
                        pass
        # Tag trade/draft articles
        is_trade = any(kw in combined for kw in ["trade", "deal", "sign", "acquire", "waive", "buyout"])
        is_draft = any(kw in combined for kw in ["draft", "pick", "prospect"])
        prefix = "[交易] " if is_trade else ("[选秀] " if is_draft else "")
        out.append({
            "title": f"{prefix}{title}",
            "summary": "",
            "url": href,
            "published_at": published_at,
            "author": None,
            "team_abbrs": "",
        })

    return out[:30]


def _fetch_hupu_voice(source: dict[str, str], session: requests.Session) -> list[dict]:
    """Scrape 虎扑篮球资讯 (voice.hupu.com) for authoritative Chinese NBA news.

    Only keeps articles tagged with [流言板] (rumor mill) which are
    professional translations of reports from Shams, Fischer, Stein, etc.
    """
    settings = get_settings()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    resp = session.get(source["feed"], headers=headers, timeout=settings.news_fetch_timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")
    out: list[dict] = []
    seen_urls: set[str] = set()

    def _append_item(href: str, title: str, parent) -> None:
        normalized_url = _normalize_hupu_url(href)
        if normalized_url is None:
            return
        title = title.strip()
        if (
            not title
            or len(title) < 8
            or len(title) > 200
            or not _should_keep_hupu_link(normalized_url, title)
            or normalized_url in seen_urls
        ):
            return
        seen_urls.add(normalized_url)

        published_at = datetime.utcnow()
        if parent:
            parent_text = parent.get_text(" ", strip=True)
            # Try "MM月DD日 HH:MM" or "YYYY-MM-DD" format
            date_match = re.search(r"(\d{1,2})月(\d{1,2})日\s+(\d{2}:\d{2})", parent_text)
            if date_match:
                try:
                    published_at = datetime(2026, int(date_match.group(1)), int(date_match.group(2)),
                                           int(date_match.group(3).split(":")[0]), int(date_match.group(3).split(":")[1]))
                except ValueError:
                    pass
            else:
                date_match = re.search(r"(\d{4}-\d{2}-\d{2})", parent_text)
                if date_match:
                    try:
                        published_at = datetime.strptime(date_match.group(1), "%Y-%m-%d")
                    except ValueError:
                        pass
        combined = title.lower()
        is_trade = any(
            kw in combined for kw in ["交易", "签约", "裁员", "买断", "有意", "询价", "追求"]
        )
        is_draft = any(
            kw in combined for kw in ["选秀", "新秀", "签位", "号签", "试训", "行情"]
        )
        prefix = "[交易] " if is_trade else ("[选秀] " if is_draft else "[流言] ")
        out.append({
            "title": f"{prefix}{title}",
            "summary": "",
            "url": normalized_url,
            "published_at": published_at,
            "author": None,
            "team_abbrs": "",
        })

    # Prefer authoritative Hupu news links, but keep a strict host/title
    # guard because the page can include community recommendations.
    for a in soup.select("a[href]"):
        _append_item(a.get("href", ""), a.get_text(strip=True), a.find_parent())

    # Also try <a> tags with title attribute (voice.hupu.com uses this pattern)
    for a in soup.select("a[title]"):
        _append_item(a.get("href", ""), a.get("title", ""), a.find_parent())

    return out[:30]


def _normalize_hupu_url(href: str) -> str | None:
    href = (href or "").strip()
    if not href:
        return None
    if href.startswith("/"):
        return f"https://voice.hupu.com{href}"
    if href.startswith("http"):
        return href
    return None


def _is_hupu_rumor_title(title: str) -> bool:
    return "[流言板]" in title or "流言板" in title


def _has_hupu_draft_context(title: str) -> bool:
    lowered = title.lower()
    return any(keyword.lower() in lowered for keyword in HUPU_DRAFT_CONTEXT_KEYWORDS)


def _has_hupu_topic_context(title: str) -> bool:
    lowered = title.lower()
    return any(keyword.lower() in lowered for keyword in HUPU_TOPIC_KEYWORDS)


def _is_hupu_noise_title(title: str) -> bool:
    return any(keyword in title for keyword in HUPU_NOISE_KEYWORDS)


def _should_keep_hupu_link(url: str, title: str) -> bool:
    host = urlparse(url).netloc.lower()
    is_voice = host == "voice.hupu.com"
    is_bbs = host == "bbs.hupu.com"
    is_rumor = _is_hupu_rumor_title(title)
    has_draft_context = _has_hupu_draft_context(title)

    if _is_hupu_noise_title(title):
        return False
    if is_bbs:
        return is_rumor and has_draft_context
    if is_voice:
        if not (is_rumor or has_draft_context):
            return False
        return has_draft_context or _has_hupu_topic_context(title)
    return False


FETCHERS: dict[str, _Fetcher] = {
    "espn_json": _fetch_espn_json,
    "nba_trade_tracker": _fetch_nba_trade_tracker,
    "sportando": _fetch_sportando,
    "hupu_voice": _fetch_hupu_voice,
}


# ---------------------------------------------------------------------------
# Article filtering helpers
# ---------------------------------------------------------------------------
def _is_game_article(text: str) -> bool:
    """Return True if the article is about a specific game/match rather than
    trades, draft, or offseason moves."""
    for pattern in GAME_EXCLUDE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def is_draftmind_relevant_news(article_or_text: NewsArticle | str) -> bool:
    """Return True for articles suitable for the public DraftMind news panel."""
    if isinstance(article_or_text, str):
        text = article_or_text
    else:
        text = " ".join(
            [
                article_or_text.title or "",
                article_or_text.summary or "",
                article_or_text.body_excerpt or "",
            ]
        )
    lowered = text.lower()
    if any(keyword in lowered for keyword in DRAFTMIND_NEWS_NOISE_KEYWORDS):
        return False
    if any(keyword in lowered for keyword in DRAFTMIND_NEWS_CONTEXT_KEYWORDS):
        return True
    if re.search(r"\bno\.\s*\d{1,2}\b", lowered):
        return True
    if re.search(r"#\s*\d{1,2}\b", lowered):
        return True
    if re.search(r"\b\d{1,2}(st|nd|rd|th)\s+pick\b", lowered):
        return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def fetch_recent_articles(
    db: Session,
    *,
    limit: int | None = None,
    refresh: bool = False,
) -> list[NewsArticle]:
    """Fetch and upsert NBA trade/draft news from all configured sources.

    Designed to be safe to call at request time: failures on a single source
    are logged and skipped so the rest of the import still runs.
    """
    settings = get_settings()
    max_articles = limit or settings.news_max_articles
    headers = {"User-Agent": settings.news_user_agent}
    articles: list[NewsArticle] = []

    with requests.Session() as session:
        session.headers.update(headers)

        from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout

        def _run_one(source: dict) -> tuple[str, list[dict] | None, str | None]:
            fetcher = FETCHERS.get(source["kind"])
            if fetcher is None:
                return source["name"], None, f"unknown kind: {source['kind']}"
            try:
                return source["name"], fetcher(source, session), None
            except Exception as exc:  # noqa: BLE001
                return source["name"], None, str(exc)

        # Run all sources in parallel; collect results as they complete.
        per_source_timeout = max(8.0, float(settings.news_fetch_timeout or 6.0) + 2.0)
        completed: list[tuple[dict, list[dict]]] = []
        with ThreadPoolExecutor(max_workers=len(SOURCES) or 1) as pool:
            future_map = {pool.submit(_run_one, src): src for src in SOURCES}
            for fut in as_completed(future_map, timeout=per_source_timeout):
                src = future_map[fut]
                try:
                    name, raw, err = fut.result(timeout=0.1)
                except FuturesTimeout:
                    logger.warning("Source %s: timed out", src["name"])
                    continue
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Source %s: unexpected error: %s", src["name"], exc)
                    continue
                if err is not None:
                    logger.warning("Source %s fetch failed: %s", name, err)
                    continue
                if raw:
                    completed.append((src, raw))

        for source, raw in completed:
            logger.info("Source %s: fetcher returned %d raw items", source["name"], len(raw))
            # Dedupe within source by URL.
            seen_urls: set[str] = set()
            unique_raw: list[dict] = []
            for item in raw:
                url = (item.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                unique_raw.append(item)
            logger.info(
                "Source %s: %d items after dedupe",
                source["name"],
                len(unique_raw),
            )

            per_source = max(1, max_articles // max(1, len(SOURCES)))
            for item in unique_raw[:per_source]:
                try:
                    article = _raw_to_article(item, source)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Source %s: skip malformed item: %s", source["name"], exc)
                    continue
                if article is None:
                    continue
                try:
                    persisted = upsert_article(db, article)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Source %s: upsert failed for %s: %s", source["name"], article.url, exc)
                    continue
                articles.append(persisted)
                if len(articles) >= max_articles:
                    break
            if len(articles) >= max_articles:
                break

    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("news commit failed: %s", exc)
        db.rollback()

    if refresh:
        _purge_stale_and_orphaned(db)
        _trim_old_articles(db, settings.news_max_articles)
        try:
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("news trim commit failed: %s", exc)
            db.rollback()

    return articles


def upsert_article(db: Session, article: NewsArticle) -> NewsArticle:
    existing = db.scalar(select(NewsArticle).where(NewsArticle.url == article.url))
    if existing is None:
        db.add(article)
        db.flush()
        return article
    existing.title = article.title
    existing.summary = article.summary
    existing.body_excerpt = article.body_excerpt
    existing.prospect_names = article.prospect_names
    existing.team_abbrs = article.team_abbrs
    existing.author = article.author
    existing.published_at = article.published_at
    existing.fetched_at = article.fetched_at
    return existing


def _fallback_cached(db: Session, limit: int) -> list[NewsArticle]:
    """Return whatever articles we already have cached."""
    try:
        return list(
            db.scalars(
                select(NewsArticle)
                .order_by(NewsArticle.published_at.desc())
                .limit(limit)
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("fallback cache read failed: %s", exc)
        return []


def search_articles(
    db: Session,
    *,
    prospect_name: str | None = None,
    team_abbr: str | None = None,
    keyword: str | None = None,
    language: str | None = None,
    limit: int = 5,
    draftmind_only: bool = False,
) -> list[NewsArticle]:
    """Lightweight retrieval for the agent RAG pipeline.

    When `language` is specified but yields no results, we automatically
    fall back to all languages so the caller always gets useful data.
    Articles within the last 24h are always preferred.
    """
    stmt = select(NewsArticle).order_by(NewsArticle.published_at.desc())
    if language:
        stmt = stmt.where(NewsArticle.language == language)
    candidates = list(db.scalars(stmt.limit(200)))
    if not candidates and language:
        # Fallback: try without language filter
        stmt = select(NewsArticle).order_by(NewsArticle.published_at.desc())
        candidates = list(db.scalars(stmt.limit(200)))
    if not candidates:
        return []

    # Prefer articles published within the last 24 hours.
    # Note: SQLite stores naive datetimes, so we use naive UTC for comparison.
    cutoff = datetime.utcnow() - timedelta(hours=24)
    recent = [a for a in candidates if a.published_at.replace(tzinfo=None) >= cutoff]
    if recent:
        candidates = recent

    if draftmind_only:
        candidates = [article for article in candidates if is_draftmind_relevant_news(article)]
        if not candidates:
            return []

    needles: list[str] = []
    if prospect_name:
        needles.append(prospect_name)
        needles.extend(part for part in prospect_name.split() if len(part) >= 3)
    if team_abbr:
        needles.append(team_abbr)
    if keyword:
        needles.append(keyword)

    # If no specific search criteria, return most recent articles
    if not needles:
        return candidates[:limit]

    scored: list[tuple[float, NewsArticle]] = []
    for article in candidates:
        score = _article_relevance(article, needles)
        if score > 0:
            scored.append((score, article))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [article for _, article in scored[:limit]]


def _article_relevance(article: NewsArticle, needles: Iterable[str]) -> float:
    needles = [n for n in needles if n]
    if not needles:
        return 0.0
    haystack = " ".join(
        [article.title or "", article.summary or "", article.body_excerpt or ""]
    ).lower()
    haystack_prospects = (article.prospect_names or "").lower()
    haystack_teams = (article.team_abbrs or "").lower()

    score = 0.0
    for needle in needles:
        token = needle.lower()
        if not token:
            continue
        if token in haystack:
            score += 1.0
        if token in haystack_prospects:
            score += 2.0
        if token in haystack_teams:
            score += 0.8
    # Prefer fresh content.
    age_days = max(
        0,
        (datetime.utcnow() - article.published_at.replace(tzinfo=None)).days,
    )
    if article.language == "zh":
        score += 0.3
    # Boost trade/draft tagged articles
    if "[交易" in (article.title or "") or "[选秀" in (article.title or ""):
        score += 1.0
    score += max(0.0, 1.0 - age_days * 0.05)
    return score


def _raw_to_article(item: dict, source: dict[str, str]) -> NewsArticle | None:
    url = (item.get("url") or "").strip()
    title = _clean_text(item.get("title") or "")
    if not url or not title:
        return None
    summary = _clean_text(item.get("summary") or "")
    haystack = f"{title} {summary}"
    # Augment with Chinese team name detection.
    team_abbrs = item.get("team_abbrs") or ""
    for cn_name, abbr in TEAM_CN_HINTS.items():
        if cn_name in haystack and abbr not in team_abbrs:
            team_abbrs = f"{team_abbrs},{abbr}" if team_abbrs else abbr
    return NewsArticle(
        source=source["name"],
        title=title,
        summary=summary[:500],
        url=url,
        author=item.get("author") or None,
        language=source.get("language", "en"),
        published_at=item.get("published_at") or datetime.utcnow(),
        fetched_at=datetime.utcnow(),
        body_excerpt=summary[:1200],
        prospect_names=_extract_names(haystack, PROSPECT_HINT_TOKENS),
        team_abbrs=team_abbrs,
    )


def _clean_text(value: str) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "lxml")
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def _parse_iso(value: str) -> datetime | None:
    """Parse ISO datetime string and return a naive UTC datetime (no tzinfo).

    SQLite DateTime columns don't store timezone info, so we always strip it.
    """
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        # Strip timezone info to get naive UTC datetime for SQLite compatibility
        return dt.replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _extract_names(text: str, tokens: Iterable[str]) -> str:
    lowered = text.lower()
    found: list[str] = []
    for token in tokens:
        if token.lower() in lowered and token not in found:
            found.append(token)
    return ",".join(found)


def _espn_team_id_to_abbr(team_id: int | None) -> str | None:
    if not team_id:
        return None
    mapping = {
        1: "ATL", 2: "BOS", 3: "BKN", 4: "CHA", 5: "CHI", 6: "CLE",
        7: "DAL", 8: "DEN", 9: "DET", 10: "GSW", 11: "HOU", 12: "IND",
        13: "LAC", 14: "LAL", 15: "MEM", 16: "MIA", 17: "MIL", 18: "MIN",
        19: "NOP", 20: "NYK", 21: "OKC", 22: "ORL", 23: "PHI", 24: "PHX",
        25: "POR", 26: "SAC", 27: "SAS", 28: "TOR", 29: "UTA", 30: "WAS",
    }
    return mapping.get(team_id)


def _espn_abbr_normalize(abbr: str) -> str:
    """Normalize ESPN's 2-letter scoreboard abbreviations to our 3-letter standard."""
    mapping = {
        "NY": "NYK", "SA": "SAS", "NO": "NOP", "GS": "GSW",
        "WS": "WAS", "UT": "UTA", "PH": "PHX", "BK": "BKN",
        "LA": "LAL",
    }
    return mapping.get(abbr, abbr)


def _purge_stale_and_orphaned(db: Session) -> None:
    """Remove articles older than 48h and articles from removed sources.

    This ensures stale data (e.g. old Sina/Sohu entries with garbled titles
    and wrong published_at timestamps) does not pollute search results.
    """
    # Active source names — anything else is from a removed source.
    active_sources = {s["name"] for s in SOURCES}

    # Delete articles from removed sources.
    orphaned = list(
        db.scalars(select(NewsArticle).where(NewsArticle.source.notin_(active_sources)))
    )
    if orphaned:
        orphaned_ids = [a.id for a in orphaned]
        logger.info("Purging %d articles from removed sources: %s", len(orphaned_ids), set(a.source for a in orphaned))
        db.execute(delete(NewsArticle).where(NewsArticle.id.in_(orphaned_ids)))

    # Delete articles older than 48 hours (based on fetched_at, which is
    # always the real ingestion time).  This prevents stale cache entries
    # from surfacing when upstream sources are temporarily unavailable.
    # Note: SQLite stores naive datetimes, so we use naive UTC for comparison.
    cutoff = datetime.utcnow() - timedelta(hours=48)
    stale = list(
        db.scalars(select(NewsArticle).where(NewsArticle.fetched_at < cutoff))
    )
    if stale:
        stale_ids = [a.id for a in stale]
        logger.info("Purging %d articles older than 48h", len(stale_ids))
        db.execute(delete(NewsArticle).where(NewsArticle.id.in_(stale_ids)))


def _trim_old_articles(db: Session, keep: int) -> None:
    """Drop the oldest rows when we exceed the cache budget."""
    rows = list(
        db.scalars(
            select(NewsArticle).order_by(NewsArticle.published_at.desc())
        )
    )
    if len(rows) <= keep:
        return
    stale = [article.id for article in rows[keep:]]
    if stale:
        db.execute(delete(NewsArticle).where(NewsArticle.id.in_(stale)))


# --- Convenience helper used by agent / RAG services ---

def build_prospect_context(
    db: Session,
    *,
    prospect_name: str,
    team_abbr: str | None,
    limit: int = 3,
) -> list[NewsArticle]:
    """Build news context for a prospect. Tries zh first, falls back to all."""
    result = search_articles(
        db,
        prospect_name=prospect_name,
        team_abbr=team_abbr,
        language="zh",
        limit=limit,
    )
    if not result:
        result = search_articles(
            db,
            prospect_name=prospect_name,
            team_abbr=team_abbr,
            limit=limit,
        )
    return result


def article_age_label(article: NewsArticle) -> str:
    delta = datetime.utcnow() - article.published_at.replace(tzinfo=None)
    if delta < timedelta(days=1):
        return "今天"
    if delta < timedelta(days=2):
        return "1 天前"
    return f"{delta.days} 天前"
