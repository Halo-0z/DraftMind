"""Rumor signal extractor — derives structured ``NewsSignal`` view objects
from already-cached ``NewsArticle`` (or any duck-typed object with the
same surface).

Design goals (Phase 5A, internal-only):

* Pure function library. No DB, no LLM, no network. Given a sequence of
  article objects, return a list of signals.
* Whitelist-driven intent classification. If an article does not match
  any of the seven intent buckets, it produces *no* signal (we do not
  even emit ``OTHER`` for it — that gets filtered downstream anyway).
* Source authority tiers and a simple recency decay combine to a
  confidence in ``[0, 1]``. Signals below ``CONFIDENCE_FLOOR`` are
  dropped so the caller never sees noise.
* Pure-data output: ``NewsSignal`` is a frozen dataclass. We do *not*
  persist signals, do *not* expose them via Pydantic, and do *not* call
  the LLM. ``ranking_engine`` and ``simulate_draft`` continue to ignore
  news entirely.

This module is intentionally read-only with respect to the rest of the
codebase — it can be imported and tested without DB fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Confidence floor — signals below this are discarded.
CONFIDENCE_FLOOR: float = 0.30


#: Hard-coded source authority tiers. Lower tier = more weight.
#: Tier 1 = official / semi-official, Tier 3 = community translation.
SOURCE_AUTHORITY: dict[str, float] = {
    "ESPN NBA News": 1.0,
    "ESPN CBB Draft": 1.0,
    "NBA Trade Tracker": 1.0,
    "Sportando NBA": 0.8,
    "Hupu Voice": 0.6,
}
SOURCE_AUTHORITY_DEFAULT: float = 0.4


#: Recency decay — piecewise linear.
#: 0-6h:   * 1.0
#: 6-24h:  * 0.8
#: 24-48h: * 0.6
#: 48h+:   * 0.35   (stale but not zero — a 3-day-old "SAS wants
#:                   pick 2" rumor is still more useful than no signal)
#: 14d+:   * 0.0    (effectively dropped by the confidence floor)
#: unknown: * 0.4
def _recency_factor(age_hours: float | None) -> float:
    if age_hours is None:
        return 0.4
    if age_hours < 0:
        return 1.0
    if age_hours < 6:
        return 1.0
    if age_hours < 24:
        return 0.8
    if age_hours < 48:
        return 0.6
    if age_hours < 14 * 24:
        return 0.35
    return 0.0


#: Whitelist keyword tables. Order within each list is preserved but
#: ordering of buckets is fixed (see ``_classify_intent``).
INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "trade_up": (
        "trade up", "move up", "moving up",
        "acquire pick", "向上交易", "换取签位",
    ),
    "trade_down": (
        "trade down", "move back", "moving back",
        "shop the pick", "open to dealing",
        "向下交易", "出售签位",
    ),
    "workout": (
        "workout", "visit", "met with", "tryout",
        "试训", "面试",
    ),
    "draft_pref": (
        "high on", "linked to", "interested in",
        "targeting", "zeroed in on",
        "有意", "青睐", "看中",
    ),
    "rise": (
        "rising", "stock rising", "climbing",
        "moving up boards", "行情上涨",
    ),
    "fall": (
        "falling", "sliding", "stock falling",
        "dropping", "行情下滑",
    ),
}


#: Patterns that mark a *game* article (not draft/trade rumor). If the
#: title (or summary) hits one of these and no intent keyword matched,
#: we skip the article silently.
GAME_NOISE_PATTERNS: tuple[str, ...] = (
    "box score",
    "how to watch",
    "halftime",
    "injury recap",
    "game preview",
    "final score",
    "player scores",
    "highlights",
    "比赛集锦",
    "赛后采访",
)


#: Standard 30-team abbreviation whitelist for ``_pick_team``.
TEAM_ABBR_TOKENS: frozenset[str] = frozenset({
    "WAS", "UTA", "MEM", "CHI", "LAC", "BKN", "SAC", "ATL",
    "DAL", "MIL", "GSW", "OKC", "MIA", "CHA", "TOR", "SAS",
    "HOU", "DET", "POR", "NYK", "LAL", "DEN", "BOS", "MIN",
    "CLE", "PHI", "PHX", "ORL", "IND", "NOP",
})


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class RumorIntent(str, Enum):
    """Seven-way classification of draft/trade rumors."""

    TRADE_UP = "trade_up"
    TRADE_DOWN = "trade_down"
    WORKOUT = "workout"
    DRAFT_PREFERENCE = "draft_pref"
    RISE = "rise"
    FALL = "fall"
    OTHER = "other"


@dataclass(frozen=True)
class NewsSignal:
    """A structured view of a single draft/trade rumor derived from a
    ``NewsArticle`` (or any duck-typed equivalent)."""

    team_abbr: str | None
    prospect_name: str | None
    pick_no: int | None
    intent: RumorIntent
    confidence: float
    source_count: int
    evidence_urls: list[str] = field(default_factory=list)
    summary: str = ""
    published_at: datetime | None = None
    age_hours: float | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    """Naive UTC now (consistent with SQLite-stored datetimes in the
    existing ``news_service``)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _article_attr(article: Any, name: str, default: Any = "") -> Any:
    """Read an attribute from either a dict or an object, returning
    ``default`` for missing keys / attributes."""
    if isinstance(article, dict):
        return article.get(name, default)
    return getattr(article, name, default)


def _haystack(article: Any) -> str:
    title = str(_article_attr(article, "title", "") or "")
    summary = str(_article_attr(article, "summary", "") or "")
    body = str(_article_attr(article, "body_excerpt", "") or "")
    return f"{title} \n {summary} \n {body}".lower()


#: Intent priority. Higher index = higher priority. The first
#: matching keyword found for the highest-priority intent wins. This
#: order is intentional: a title like "Ace Bailey sliding down draft
#: boards after workout no-shows" must be classified as FALL (the
#: dominant narrative), not WORKOUT (a passing modifier).
INTENT_PRIORITY: tuple[RumorIntent, ...] = (
    RumorIntent.OTHER,            # placeholder for "anything else"
    RumorIntent.DRAFT_PREFERENCE, # baseline — easier to satisfy
    RumorIntent.WORKOUT,          # specific event
    RumorIntent.TRADE_UP,         # action verbs
    RumorIntent.TRADE_DOWN,       # action verbs
    RumorIntent.RISE,             # market signal
    RumorIntent.FALL,             # market signal — highest priority
)


def _classify_intent(haystack_lower: str) -> RumorIntent | None:
    """Return the dominant intent by priority, or ``None`` if no
    whitelist keyword matches anything.

    Priority (low → high): ``DRAFT_PREFERENCE < WORKOUT <
    TRADE_UP < TRADE_DOWN < RISE < FALL``.

    A title like "Ace Bailey sliding down draft boards after workout
    no-shows" matches both ``workout`` and ``sliding``. We must pick
    ``FALL`` because that is the dominant market signal — ``workout``
    is a passing modifier. Hence the priority list above.
    """
    for intent in reversed(INTENT_PRIORITY):
        keywords = INTENT_KEYWORDS.get(intent.value, ())
        for kw in keywords:
            if kw.lower() in haystack_lower:
                return intent
    return None


def _is_game_noise(haystack_lower: str) -> bool:
    return any(pat in haystack_lower for pat in GAME_NOISE_PATTERNS)


def _pick_team(article: Any, haystack_lower: str) -> str | None:
    """Prefer the structured ``team_abbrs`` field; fall back to scanning
    the haystack for known abbr tokens."""
    abbrs_raw = _article_attr(article, "team_abbrs", "") or ""
    for token in (t.strip().upper() for t in str(abbrs_raw).split(",") if t.strip()):
        if token in TEAM_ABBR_TOKENS:
            return token
    # Fall back to scanning for abbr tokens in the haystack.
    for abbr in TEAM_ABBR_TOKENS:
        # Match as a word boundary, e.g. "SAS" not inside "SASScout".
        if f" {abbr} " in f" {haystack_lower.upper()} ":
            return abbr
    return None


def _pick_prospect(article: Any) -> str | None:
    """First non-empty entry in the comma-separated ``prospect_names``
    field, if any."""
    names_raw = _article_attr(article, "prospect_names", "") or ""
    for token in (t.strip() for t in str(names_raw).split(",") if t.strip()):
        return token
    return None


_PICK_NO_PATTERNS: tuple[str, ...] = (
    r"#\s*(\d{1,2})\b",
    r"no\.\s*(\d{1,2})\b",
    r"pick\s*no\.\s*(\d{1,2})\b",
    r"(\d{1,2})(?:st|nd|rd|th)\s+pick\b",
)


def _pick_pick_no(article: Any, haystack_lower: str) -> int | None:
    """Search for a draft-pick number in the haystack. Returns the first
    hit, if any, in the 1-60 range."""
    import re

    candidates: list[int] = []
    for pat in _PICK_NO_PATTERNS:
        for m in re.finditer(pat, haystack_lower):
            try:
                n = int(m.group(1))
            except (ValueError, IndexError):
                continue
            if 1 <= n <= 60:
                candidates.append(n)
    if candidates:
        # Prefer the *first* match (most natural reading order).
        return candidates[0]
    return None


def _age_hours(article: Any, now: datetime | None = None) -> float | None:
    published = _article_attr(article, "published_at", None)
    if published is None:
        return None
    if isinstance(published, str):
        # Best-effort ISO parse; if it fails, treat as unknown.
        try:
            published = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(published, datetime):
        return None
    if published.tzinfo is not None:
        published = published.astimezone(timezone.utc).replace(tzinfo=None)
    ref = now or _now()
    delta = ref - published
    return delta.total_seconds() / 3600.0


def _source_authority(source: str) -> float:
    return SOURCE_AUTHORITY.get(source, SOURCE_AUTHORITY_DEFAULT)


def _confidence_for(
    *,
    source: str,
    age_hours: float | None,
    has_team: bool,
    has_prospect: bool,
    has_pick: bool,
) -> float:
    """Combine source authority, recency, and entity presence into a
    confidence in [0, 1].

    We multiply three sub-scores:
      * source authority in [0.4, 1.0]
      * recency factor in [0.2, 1.0]
      * entity presence bonus: 0.7 if no entities, up to 1.0 if all three
    """
    base = _source_authority(source)
    recency = _recency_factor(age_hours)
    entity_bonus = 0.7
    if has_team:
        entity_bonus += 0.1
    if has_prospect:
        entity_bonus += 0.1
    if has_pick:
        entity_bonus += 0.1
    # Cap to [0, 1].
    entity_bonus = min(entity_bonus, 1.0)
    return max(0.0, min(1.0, base * recency * entity_bonus))


def _make_summary(title: str, intent: RumorIntent) -> str:
    """Trim a one-line human-readable summary from the article title."""
    cleaned = " ".join((title or "").split())
    if len(cleaned) <= 120:
        return cleaned
    return cleaned[:117] + "..."


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_signals(
    articles: Sequence[object],
    *,
    now: datetime | None = None,
) -> list[NewsSignal]:
    """Extract draft / trade rumor signals from a sequence of articles.

    The function is intentionally tolerant: each article may be either a
    SQLAlchemy ``NewsArticle`` instance, a Pydantic ``NewsArticleRead``,
    a ``SimpleNamespace``, or a plain ``dict``. The only attributes
    consulted are ``source``, ``title``, ``summary``, ``url``,
    ``published_at``, ``prospect_names``, ``team_abbrs``, and
    ``body_excerpt`` (the last is optional but helps).

    Behavior:

    * Empty input → empty output.
    * Article does not match any intent whitelist keyword → no signal.
    * Article matches a *game* noise pattern and no intent keyword →
      no signal.
    * Article matches an intent keyword but confidence falls below
      :data:`CONFIDENCE_FLOOR` → signal is dropped.
    * Output is sorted by ``-confidence, published_at desc, intent``.
    """
    if not articles:
        return []

    raw: list[NewsSignal] = []
    for article in articles:
        signal = _signal_from_article(article, now=now)
        if signal is not None:
            raw.append(signal)

    raw.sort(
        key=lambda s: (
            -s.confidence,
            s.published_at or datetime.min,
            s.intent.value,
        )
    )
    return raw


def _signal_from_article(
    article: Any,
    *,
    now: datetime | None,
) -> NewsSignal | None:
    source = str(_article_attr(article, "source", "") or "")
    title = str(_article_attr(article, "title", "") or "")
    if not title:
        return None

    haystack = _haystack(article)
    haystack_lower = haystack.lower()

    intent = _classify_intent(haystack_lower)
    if intent is None:
        return None
    if _is_game_noise(haystack_lower):
        return None

    team = _pick_team(article, haystack_lower)
    prospect = _pick_prospect(article)
    pick_no = _pick_pick_no(article, haystack_lower)
    age = _age_hours(article, now=now)

    confidence = _confidence_for(
        source=source,
        age_hours=age,
        has_team=team is not None,
        has_prospect=prospect is not None,
        has_pick=pick_no is not None,
    )
    if confidence < CONFIDENCE_FLOOR:
        return None

    published = _article_attr(article, "published_at", None)
    if isinstance(published, str):
        try:
            published = datetime.fromisoformat(published.replace("Z", "+00:00"))
            if published.tzinfo is not None:
                published = published.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            published = None
    if not isinstance(published, datetime):
        published = None

    url = str(_article_attr(article, "url", "") or "")
    return NewsSignal(
        team_abbr=team,
        prospect_name=prospect,
        pick_no=pick_no,
        intent=intent,
        confidence=round(confidence, 4),
        source_count=1,
        evidence_urls=[url] if url else [],
        summary=_make_summary(title, intent),
        published_at=published,
        age_hours=round(age, 2) if age is not None else None,
    )


def merge_duplicate_signals(
    signals: Iterable[NewsSignal],
) -> list[NewsSignal]:
    """Group signals with the same (team, prospect, pick_no, intent)
    tuple and merge them: bump ``source_count``, union evidence urls,
    keep the max confidence, keep the most recent ``published_at``.

    This is a *Phase 5A* helper, not part of the Phase 5B pipeline. It
    exists so callers can test multi-source confidence boosting in
    isolation.
    """
    grouped: dict[tuple, list[NewsSignal]] = {}
    for s in signals:
        key = (s.team_abbr, s.prospect_name, s.pick_no, s.intent)
        grouped.setdefault(key, []).append(s)

    merged: list[NewsSignal] = []
    for key, group in grouped.items():
        if len(group) == 1:
            merged.append(group[0])
            continue
        # Multi-source boost: cap at 1.0.
        best = max(group, key=lambda x: x.confidence)
        urls: list[str] = []
        for s in group:
            for u in s.evidence_urls:
                if u and u not in urls:
                    urls.append(u)
        latest_pub = max(
            (s.published_at for s in group if s.published_at is not None),
            default=None,
        )
        min_age = min(
            (s.age_hours for s in group if s.age_hours is not None),
            default=None,
        )
        # Mild boost for multi-source (max +0.10, capped at 1.0).
        boosted = min(1.0, best.confidence + 0.10 * (len(group) - 1))
        team, prospect, pick_no, intent = key
        merged.append(NewsSignal(
            team_abbr=team,
            prospect_name=prospect,
            pick_no=pick_no,
            intent=intent,
            confidence=round(boosted, 4),
            source_count=len(group),
            evidence_urls=urls,
            summary=best.summary,
            published_at=latest_pub,
            age_hours=min_age,
        ))

    merged.sort(
        key=lambda s: (
            -s.confidence,
            s.published_at or datetime.min,
            s.intent.value,
        )
    )
    return merged
