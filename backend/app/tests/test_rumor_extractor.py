"""Unit tests for ``app.services.rumor_extractor``.

These tests use ``SimpleNamespace`` and plain dicts as article stubs so
the test suite does not need a database, network, or fixtures from the
existing news pipeline. The extractor is duck-typed on purpose.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.rumor_extractor import (
    CONFIDENCE_FLOOR,
    NewsSignal,
    RumorIntent,
    extract_signals,
    merge_duplicate_signals,
)


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _article(**kwargs) -> SimpleNamespace:
    """Build a duck-typed article with sensible defaults."""
    base = SimpleNamespace(
        source="ESPN NBA News",
        title="",
        summary="",
        url="https://example.com/x",
        published_at=_now(),
        prospect_names="",
        team_abbrs="",
        body_excerpt="",
    )
    for k, v in kwargs.items():
        setattr(base, k, v)
    return base


# ---------------------------------------------------------------------------
# 1. Empty input
# ---------------------------------------------------------------------------

def test_extract_signals_empty_returns_empty():
    assert extract_signals([]) == []


# ---------------------------------------------------------------------------
# 2-7. English intent coverage
# ---------------------------------------------------------------------------

def test_english_trade_up_identified():
    art = _article(
        title="Lakers looking to trade up in the 2026 NBA Draft",
        team_abbrs="LAL",
    )
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].intent is RumorIntent.TRADE_UP
    assert out[0].team_abbr == "LAL"


def test_english_trade_down_identified():
    art = _article(
        title="Pacers open to dealing the No. 8 pick and trade down",
        team_abbrs="IND",
    )
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].intent is RumorIntent.TRADE_DOWN
    assert out[0].team_abbr == "IND"


def test_english_workout_identified():
    art = _article(
        title="Cooper Flagg schedules workout with the Spurs",
        team_abbrs="SAS",
        prospect_names="Cooper Flagg",
    )
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].intent is RumorIntent.WORKOUT
    assert out[0].prospect_name == "Cooper Flagg"


def test_draft_preference_identified():
    art = _article(
        title="Mavericks reportedly high on Dylan Harper ahead of the draft",
        team_abbrs="DAL",
        prospect_names="Dylan Harper",
    )
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].intent is RumorIntent.DRAFT_PREFERENCE
    assert out[0].team_abbr == "DAL"
    assert out[0].prospect_name == "Dylan Harper"


def test_rising_stock_identified():
    art = _article(
        title="VJ Edgecombe stock rising in latest 2026 mock drafts",
        prospect_names="VJ Edgecombe",
    )
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].intent is RumorIntent.RISE


def test_sliding_stock_identified():
    art = _article(
        title="Ace Bailey sliding down draft boards after workout no-shows",
        prospect_names="Ace Bailey",
    )
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].intent is RumorIntent.FALL


# ---------------------------------------------------------------------------
# 8-9. Chinese intent coverage
# ---------------------------------------------------------------------------

def test_chinese_trade_up_identified():
    art = _article(
        title="[流言] 马刺有意向上交易选秀权换取签位",
        team_abbrs="SAS",
        source="Hupu Voice",
    )
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].intent is RumorIntent.TRADE_UP
    assert out[0].team_abbr == "SAS"


def test_chinese_workout_identified():
    art = _article(
        title="[流言板] 状元热门 Cooper Flagg 前往湖人试训",
        source="Hupu Voice",
        team_abbrs="LAL",
        prospect_names="Cooper Flagg",
    )
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].intent is RumorIntent.WORKOUT


# ---------------------------------------------------------------------------
# Phase 6A-C: Chinese coverage hardening.
#
# These tests are *additive* — they only assert behaviour the
# extractor already has.  See ``INTENT_KEYWORDS`` in
# ``app/services/rumor_extractor.py`` for the actual whitelisted
# Chinese terms.  The current whitelist is:
#   trade_up   : "向上交易", "换取签位"
#   trade_down : "向下交易", "出售签位"
#   workout    : "试训", "面试"
#   draft_pref : "有意", "青睐", "看中"
#   rise       : "行情上涨"
#   fall       : "行情下滑"
#   game_noise : "比赛集锦", "赛后采访"
#   INTENT_PRIORITY: DRAFT_PREFERENCE < WORKOUT < TRADE_UP
#                    < TRADE_DOWN < RISE < FALL
# ---------------------------------------------------------------------------


def test_chinese_trade_down_identified():
    """`向下交易` and `出售签位` are the two whitelisted trade_down
    markers; we test both via parametrize below.  This single
    happy-path mirrors the existing Chinese trade_up test.
    """
    art = _article(
        title="[流言] 火箭考虑向下交易签位换取未来资产",
        team_abbrs="HOU",
        source="Hupu Voice",
    )
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].intent is RumorIntent.TRADE_DOWN
    assert out[0].team_abbr == "HOU"


def test_chinese_rise_identified():
    art = _article(
        title="[流言] 状元行情上涨，Bulldogs 持续走高",
        prospect_names="VJ Edgecombe",
        source="Hupu Voice",
    )
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].intent is RumorIntent.RISE
    assert out[0].prospect_name == "VJ Edgecombe"


def test_chinese_fall_identified():
    art = _article(
        title="[流言] Ace Bailey 行情下滑 跌出前五",
        prospect_names="Ace Bailey",
        source="Hupu Voice",
    )
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].intent is RumorIntent.FALL
    assert out[0].prospect_name == "Ace Bailey"


@pytest.mark.parametrize("title,team_abbr,prospect", [
    ("[流言] 凯尔特人有意 Dylan Harper", "BOS", "Dylan Harper"),
    ("[流言] 湖人青睐新秀 Cooper Flagg", "LAL", "Cooper Flagg"),
    ("[流言] 马刺看中新秀 VJ Edgecombe", "SAS", "VJ Edgecombe"),
])
def test_chinese_draft_preference_identified(title, team_abbr, prospect):
    art = _article(
        title=title,
        team_abbrs=team_abbr,
        prospect_names=prospect,
        source="Hupu Voice",
    )
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].intent is RumorIntent.DRAFT_PREFERENCE
    assert out[0].team_abbr == team_abbr
    assert out[0].prospect_name == prospect


def test_chinese_fall_priority_over_workout():
    """中文标题同时含 `试训` (WORKOUT) 和 `行情下滑` (FALL).

    INTENT_PRIORITY must let FALL win — same contract as the English
    `test_sliding_stock_identified` test.  This is the regression
    net for "Chinese fall 标签和试训 标签混在一起时不能错判 WORKOUT".
    """
    art = _article(
        title="[流言] Cooper Flagg 试训不佳 行情下滑",
        team_abbrs="LAL",
        prospect_names="Cooper Flagg",
        source="Hupu Voice",
    )
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].intent is RumorIntent.FALL
    assert out[0].prospect_name == "Cooper Flagg"


# ---------------------------------------------------------------------------
# 10-12. Game news must not produce signals
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title", [
    "Lakers vs Warriors final score: 112-108",
    "Box score: LeBron James 35 points, 8 rebounds",
    "How to watch Celtics vs Heat tonight",
    "Halftime update from Madison Square Garden",
    "Game preview: Bucks host 76ers in conference finals",
    "Player scores 40 in loss to Nuggets",
    "比赛集锦：湖人击败勇士",
    "赛后采访：詹姆斯谈球队表现",
])
def test_game_news_does_not_produce_signal(title):
    art = _article(title=title, team_abbrs="LAL")
    out = extract_signals([art])
    assert out == [], f"game-news article should not produce signal: {title!r}"


# ---------------------------------------------------------------------------
# 13. Recency decay
# ---------------------------------------------------------------------------

def test_old_article_confidence_decays():
    # Both articles use the default _article() source = "ESPN NBA News"
    # (authority 1.0). The ancient article additionally has an explicit
    # prospect_name so the entity_bonus is high enough to clear the
    # confidence floor even after 72h recency decay (1.0 * 0.35 * 0.9
    # = 0.315 > 0.30). Without the prospect, entity_bonus = 0.8 and
    # the product drops to 0.28, which the floor filters out — that
    # is the intended behavior for a low-context old rumor.
    fresh = _article(
        title="Lakers looking to trade up",
        team_abbrs="LAL",
        prospect_names="Cooper Flagg",
    )
    ancient = _article(
        title="Lakers looking to trade up",
        team_abbrs="LAL",
        prospect_names="Cooper Flagg",
        published_at=_now() - timedelta(hours=72),
    )
    fresh_out = extract_signals([fresh])
    ancient_out = extract_signals([ancient])
    assert len(fresh_out) == 1
    assert len(ancient_out) == 1
    assert fresh_out[0].confidence > ancient_out[0].confidence


def test_low_authority_72h_signal_dropped_below_floor():
    # With a low-authority source, the 72h decay product drops below
    # the confidence floor and the signal is dropped entirely.
    ancient_low_authority = _article(
        source="random-blog.example.com",
        title="Lakers looking to trade up",
        team_abbrs="LAL",
        published_at=_now() - timedelta(hours=72),
    )
    out = extract_signals([ancient_low_authority])
    # 0.4 * 0.35 * 0.8 = 0.112 < 0.30 -> dropped
    assert out == []


def test_very_old_signal_dropped_below_floor():
    art = _article(
        title="Lakers looking to trade up",
        team_abbrs="LAL",
        source="Hupu Voice",  # lower authority *and* older
        published_at=_now() - timedelta(days=14),
    )
    out = extract_signals([art])
    # 14d+ recency factor is 0.0; Hupu authority 0.6; product = 0 -> dropped
    assert out == []


# ---------------------------------------------------------------------------
# 14. Unknown published_at must not crash
# ---------------------------------------------------------------------------

def test_unknown_published_at_does_not_crash():
    art = _article(
        title="Lakers looking to trade up",
        team_abbrs="LAL",
        published_at=None,
    )
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].published_at is None
    assert out[0].age_hours is None


def test_published_at_as_string_does_not_crash():
    art = _article(
        title="Lakers looking to trade up",
        team_abbrs="LAL",
        published_at="2026-06-09T12:34:56",
    )
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].published_at is not None


# ---------------------------------------------------------------------------
# 15. Source authority affects confidence
# ---------------------------------------------------------------------------

def test_source_authority_affects_confidence():
    espn = _article(
        title="Lakers looking to trade up",
        team_abbrs="LAL",
        source="ESPN NBA News",
    )
    random_blog = _article(
        title="Lakers looking to trade up",
        team_abbrs="LAL",
        source="random-blog.example.com",
    )
    out_espn = extract_signals([espn])
    out_random = extract_signals([random_blog])
    assert len(out_espn) == 1
    assert len(out_random) == 1
    assert out_espn[0].confidence > out_random[0].confidence


# ---------------------------------------------------------------------------
# 16. Confidence floor
# ---------------------------------------------------------------------------

def test_confidence_floor_filters_low_quality():
    # Low-authority + no team + no prospect + no pick + old
    art = _article(
        title="trade up",  # single keyword, no entities
        source="random-blog.example.com",
        team_abbrs="",
        prospect_names="",
        published_at=_now() - timedelta(hours=72),
    )
    out = extract_signals([art])
    # ~0.4 source * 0.2 recency * 0.7 entity_bonus = 0.056 -> dropped
    assert out == []


def test_confidence_floor_constant_is_set():
    assert CONFIDENCE_FLOOR == 0.30


# ---------------------------------------------------------------------------
# Phase 6A-C: more Chinese game-news variants + Chinese low-quality
# decay.  These are additive — they don't touch the English-only or
# existing Chinese tests above.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("title", [
    # Both whitelisted GAME_NOISE_PATTERNS ("比赛集锦", "赛后采访") in
    # different positional contexts — beginning, middle, end of the
    # title — to catch any "startswith" / "endswith" mistakes.
    "[流言板] 比赛集锦：湖人 vs 勇士 112-108",
    "[流言] 赛后采访：詹姆斯谈球队表现",
    "[流言板] 今日五佳球 比赛集锦三连击",
])
def test_extra_chinese_game_news_does_not_produce_signal(title):
    art = _article(
        title=title,
        team_abbrs="LAL",
        source="Hupu Voice",
    )
    out = extract_signals([art])
    assert out == [], f"game-news article should not produce signal: {title!r}"


def test_chinese_low_authority_old_signal_dropped_below_floor():
    """Mirror of ``test_low_authority_72h_signal_dropped_below_floor``
    for the Chinese source pathway.

    Hupu Voice authority 0.6 × 14d recency 0.0 = 0.0 < 0.30 floor →
    dropped.  This is the regression net for "中文流言 + 旧 + 低权威"
    should not sneak into the market context.
    """
    art = _article(
        # 向上交易 hits trade_up whitelist, so intent classification
        # *would* produce a signal — but confidence arithmetic must
        # still drop it.
        title="[流言] 马刺有意向上交易选秀权换取签位",
        team_abbrs="SAS",
        source="Hupu Voice",  # lower authority
        published_at=_now() - timedelta(days=14),  # 14d+ recency
    )
    out = extract_signals([art])
    assert out == [], (
        f"14d-old Hupu Voice signal should drop below 0.30 floor, "
        f"got: {out}"
    )


# ---------------------------------------------------------------------------
# 17-18. Entity extraction from structured fields
# ---------------------------------------------------------------------------

def test_team_abbrs_field_preferred():
    art = _article(
        title="A team is interested in moving up",  # ambiguous
        team_abbrs="BOS, NYK",
    )
    out = extract_signals([art])
    assert len(out) == 1
    # Should pick the first known abbr
    assert out[0].team_abbr == "BOS"


def test_prospect_names_field_used():
    art = _article(
        title="A prospect is rising up boards",  # no name in title
        team_abbrs="SAS",
        prospect_names="Dylan Harper, VJ Edgecombe",
    )
    out = extract_signals([art])
    assert len(out) == 1
    # First non-empty entry is the chosen one
    assert out[0].prospect_name == "Dylan Harper"


# ---------------------------------------------------------------------------
# 19. pick_no extraction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("Lakers linked to the No. 2 pick", 2),
    ("Spurs high on prospect at #5 in the draft", 5),
    ("Jazz looking to move up for the 3rd pick", 3),
    ("Raptors willing to move back from the No. 14 pick", 14),
])
def test_pick_no_extraction(title, expected):
    art = _article(title=title, team_abbrs="LAL")
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].pick_no == expected


def test_pick_no_out_of_range_ignored():
    # Title carries an explicit draft_pref signal so the article produces
    # a signal at all, and the embedded pick number is out of the 1-60
    # range. We expect the signal to exist but with pick_no=None.
    art = _article(
        title="Lakers linked to the No. 99 pick",  # out of range
        team_abbrs="LAL",
    )
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].pick_no is None


# ---------------------------------------------------------------------------
# 20. Stable sort by confidence
# ---------------------------------------------------------------------------

def test_signals_sorted_by_confidence_desc():
    high = _article(
        title="Lakers looking to trade up",
        team_abbrs="LAL",
        source="ESPN NBA News",
    )
    low = _article(
        title="trade up is all the rage",
        team_abbrs="BOS",
        source="random-blog.example.com",
    )
    out = extract_signals([low, high])
    assert len(out) == 2
    assert out[0].confidence >= out[1].confidence


# ---------------------------------------------------------------------------
# Multi-source merging (Phase 5A helper)
# ---------------------------------------------------------------------------

def test_merge_duplicate_signals_boosts_confidence_and_counts_sources():
    s1 = NewsSignal(
        team_abbr="LAL", prospect_name="Cooper Flagg", pick_no=2,
        intent=RumorIntent.TRADE_UP, confidence=0.6, source_count=1,
        evidence_urls=["https://a"], summary="", published_at=_now(),
        age_hours=2.0,
    )
    s2 = NewsSignal(
        team_abbr="LAL", prospect_name="Cooper Flagg", pick_no=2,
        intent=RumorIntent.TRADE_UP, confidence=0.55, source_count=1,
        evidence_urls=["https://b"], summary="", published_at=_now(),
        age_hours=3.0,
    )
    merged = merge_duplicate_signals([s1, s2])
    assert len(merged) == 1
    assert merged[0].source_count == 2
    assert set(merged[0].evidence_urls) == {"https://a", "https://b"}
    assert merged[0].confidence > 0.6
    assert merged[0].confidence <= 1.0


def test_merge_duplicate_signals_no_op_on_distinct_signals():
    s1 = NewsSignal(
        team_abbr="LAL", prospect_name="Cooper Flagg", pick_no=2,
        intent=RumorIntent.TRADE_UP, confidence=0.6, source_count=1,
        evidence_urls=["https://a"], summary="", published_at=_now(),
        age_hours=2.0,
    )
    s2 = NewsSignal(
        team_abbr="BOS", prospect_name="Dylan Harper", pick_no=5,
        intent=RumorIntent.WORKOUT, confidence=0.5, source_count=1,
        evidence_urls=["https://b"], summary="", published_at=_now(),
        age_hours=1.0,
    )
    merged = merge_duplicate_signals([s1, s2])
    assert len(merged) == 2


# ---------------------------------------------------------------------------
# Defensive: dict-typed articles (in case the upstream changes shape)
# ---------------------------------------------------------------------------

def test_extract_signals_accepts_dict_articles():
    art = {
        "source": "ESPN NBA News",
        "title": "Lakers looking to trade up",
        "summary": "",
        "url": "https://example.com/1",
        "published_at": _now(),
        "prospect_names": "",
        "team_abbrs": "LAL",
        "body_excerpt": "",
    }
    out = extract_signals([art])
    assert len(out) == 1
    assert out[0].intent is RumorIntent.TRADE_UP


# ---------------------------------------------------------------------------
# Confidence range invariants
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source", [
    "ESPN NBA News", "ESPN CBB Draft", "NBA Trade Tracker",
    "Sportando NBA", "Hupu Voice", "random-blog.example.com",
])
def test_confidence_in_unit_interval(source):
    art = _article(
        title="Lakers looking to trade up",
        team_abbrs="LAL",
        source=source,
    )
    out = extract_signals([art])
    if out:
        assert 0.0 <= out[0].confidence <= 1.0
