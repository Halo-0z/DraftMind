"""M4-P / M4-W tests: curated prospect overrides for import_nba_prospects.

Verifies that hand-curated stats/position/archetype overrides are applied
correctly and survive subsequent importer runs.  Canonical cases:

* Yaxel Lendeborg (M4-P): NBA.com heuristic stats were SF-position template
  values rather than real stats.
* Brayden Burries (M4-W): NBA.com heuristic stats were PG/SG-position
  template values rather than real stats.  upside_score is also lifted from
  72.6 to 78.0 (M4-V S4 sweet spot) so Brayden lands in his projected
  range 8-13.  risk_score is intentionally NOT overridden.
"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.models import Prospect
from scripts.import_nba_prospects import (
    CURATED_PROSPECT_OVERRIDES,
    apply_curated_override,
    apply_curated_overrides_to_db,
    build_prospect,
    update_bio,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_prospect(
    name: str = "Yaxel Lendeborg",
    year: int = 2026,
    **overrides,
) -> SimpleNamespace:
    """Build a SimpleNamespace mock with default heuristic-like values."""
    base = {
        "name": name,
        "year": year,
        "position": "SF",
        "archetype": "Senior wing prospect",
        "age": 23.0,
        "height": "6-9",
        "weight": 241,
        "school_or_league": "Michigan",
        "ppg": 13.4,
        "rpg": 5.9,
        "apg": 2.4,
        "fg_pct": 47.0,
        "three_pct": 33.5,
        "ft_pct": 73.0,
        "stocks": 1.5,
        "upside_score": 74.2,
        "risk_score": 45.7,
        "stats_source": "nba_importer_heuristic",
        "stats_confidence": 0.30,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _nba_row(name: str = "Yaxel Lendeborg") -> dict:
    return {
        "displayName": name,
        "position": "F",
        "age": "23",
        "heightFeet": 6,
        "heightInches": 9,
        "weightLbs": 241,
        "school": "Michigan",
        "status": "Senior",
        "country": "USA",
        "profileLink": "",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_curated_overrides_map_contains_yaxel() -> None:
    """The override map must contain Yaxel Lendeborg for 2026."""
    assert ("Yaxel Lendeborg", 2026) in CURATED_PROSPECT_OVERRIDES
    override = CURATED_PROSPECT_OVERRIDES[("Yaxel Lendeborg", 2026)]
    assert override["position"] == "PF"
    assert override["archetype"] == "Connector frontcourt"
    assert override["ppg"] == 15.1
    assert override["rpg"] == 6.8
    assert override["apg"] == 3.2
    assert override["fg_pct"] == 51.5
    assert override["three_pct"] == 37.2
    assert override["ft_pct"] == 82.4
    assert override["stocks"] == 2.3
    assert override["stats_source"] == "seed_manual"
    assert override["stats_confidence"] == 0.80


def test_curated_overrides_do_not_touch_risk_upside_age() -> None:
    """The override map must NOT contain risk_score, upside_score, or age."""
    override = CURATED_PROSPECT_OVERRIDES[("Yaxel Lendeborg", 2026)]
    assert "risk_score" not in override
    assert "upside_score" not in override
    assert "age" not in override


def test_apply_curated_override_applies_yaxel_fields() -> None:
    """apply_curated_override overwrites Yaxel's heuristic fields."""
    prospect = _make_prospect()
    applied = apply_curated_override(prospect)

    assert applied is True
    assert prospect.position == "PF"
    assert prospect.archetype == "Connector frontcourt"
    assert prospect.ppg == 15.1
    assert prospect.rpg == 6.8
    assert prospect.apg == 3.2
    assert prospect.fg_pct == 51.5
    assert prospect.three_pct == 37.2
    assert prospect.ft_pct == 82.4
    assert prospect.stocks == 2.3
    assert prospect.stats_source == "seed_manual"
    assert prospect.stats_confidence == 0.80


def test_apply_curated_override_preserves_risk_upside_age() -> None:
    """apply_curated_override must NOT change risk_score, upside_score, age."""
    prospect = _make_prospect(risk_score=45.7, upside_score=74.2, age=23.0)
    apply_curated_override(prospect)

    assert prospect.risk_score == 45.7
    assert prospect.upside_score == 74.2
    assert prospect.age == 23.0


def test_apply_curated_override_returns_false_for_non_curated() -> None:
    """apply_curated_override returns False for prospects not in the map."""
    prospect = _make_prospect(name="Someone Else", year=2026)
    applied = apply_curated_override(prospect)
    assert applied is False
    assert prospect.position == "SF"  # unchanged


def test_apply_curated_override_returns_false_for_wrong_year() -> None:
    """apply_curated_override returns False if the year doesn't match."""
    prospect = _make_prospect(name="Yaxel Lendeborg", year=2025)
    applied = apply_curated_override(prospect)
    assert applied is False


def test_curated_override_wins_after_update_bio() -> None:
    """update_bio sets position from NBA.com, then curated override wins.

    This is the key persistence test: even if the importer runs again and
    update_bio overwrites position back to SF, the curated override applied
    immediately after restores it to PF.
    """
    prospect = _make_prospect()
    # Simulate importer update_bio overwriting position
    update_bio(prospect, _nba_row())
    assert prospect.position == "SF"  # update_bio set it back to SF

    # Now apply curated override
    apply_curated_override(prospect)
    assert prospect.position == "PF"  # curated wins


def test_apply_curated_overrides_to_db_updates_existing_row(
    db_session: Session,
) -> None:
    """apply_curated_overrides_to_db updates Yaxel in a real DB session."""
    p = Prospect(
        year=2026,
        name="Yaxel Lendeborg",
        position="SF",
        archetype="Senior wing prospect",
        age=23.0,
        height="6-9",
        weight=241,
        school_or_league="Michigan",
        ppg=13.4,
        rpg=5.9,
        apg=2.4,
        fg_pct=47.0,
        three_pct=33.5,
        ft_pct=73.0,
        stocks=1.5,
        upside_score=74.2,
        risk_score=45.7,
        stats_source="nba_importer_heuristic",
        stats_confidence=0.30,
    )
    db_session.add(p)
    db_session.commit()
    db_session.expire_all()

    # Apply override directly to this session's row
    reloaded = db_session.get(Prospect, p.id)
    assert reloaded is not None
    applied = apply_curated_override(reloaded)
    db_session.commit()

    assert applied is True
    assert reloaded.position == "PF"
    assert reloaded.archetype == "Connector frontcourt"
    assert reloaded.ppg == 15.1
    assert reloaded.three_pct == 37.2
    assert reloaded.stats_source == "seed_manual"
    assert reloaded.stats_confidence == 0.80
    # Untouched fields
    assert reloaded.risk_score == 45.7
    assert reloaded.upside_score == 74.2
    assert reloaded.age == 23.0


# ---------------------------------------------------------------------------
# M4-W: Brayden Burries curated override
# ---------------------------------------------------------------------------


def test_curated_overrides_map_contains_brayden() -> None:
    """The override map must contain Brayden Burries for 2026."""
    assert ("Brayden Burries", 2026) in CURATED_PROSPECT_OVERRIDES
    override = CURATED_PROSPECT_OVERRIDES[("Brayden Burries", 2026)]
    assert override["position"] == "SG"
    assert override["archetype"] == "Two-way combo guard"
    assert override["ppg"] == 16.1
    assert override["rpg"] == 4.9
    assert override["apg"] == 2.4
    assert override["fg_pct"] == 49.1
    assert override["three_pct"] == 39.1
    assert override["ft_pct"] == 80.5
    assert override["stocks"] == 1.7
    assert override["upside_score"] == 78.0
    assert override["stats_source"] == "seed_manual"
    assert override["stats_confidence"] == 0.80


def test_brayden_override_does_not_contain_risk_or_age() -> None:
    """Brayden's override must NOT contain risk_score or age.

    upside_score IS present (M4-V S4 sweet spot), but risk_score is
    intentionally left at the DB value (36.3) and age is never overridden.
    """
    override = CURATED_PROSPECT_OVERRIDES[("Brayden Burries", 2026)]
    assert "risk_score" not in override
    assert "age" not in override
    # upside_score IS expected to be present for Brayden
    assert "upside_score" in override
    assert override["upside_score"] == 78.0


def test_apply_curated_override_applies_brayden_fields() -> None:
    """apply_curated_override overwrites Brayden's heuristic fields."""
    prospect = _make_prospect(
        name="Brayden Burries",
        year=2026,
        position="SG",
        archetype="Heuristic combo guard",
        ppg=13.0,
        rpg=3.4,
        apg=4.2,
        fg_pct=44.5,
        three_pct=35.5,
        ft_pct=77.5,
        stocks=1.2,
        upside_score=72.6,
        risk_score=36.3,
    )
    applied = apply_curated_override(prospect)

    assert applied is True
    assert prospect.position == "SG"
    assert prospect.archetype == "Two-way combo guard"
    assert prospect.ppg == 16.1
    assert prospect.rpg == 4.9
    assert prospect.apg == 2.4
    assert prospect.fg_pct == 49.1
    assert prospect.three_pct == 39.1
    assert prospect.ft_pct == 80.5
    assert prospect.stocks == 1.7
    assert prospect.upside_score == 78.0
    assert prospect.stats_source == "seed_manual"
    assert prospect.stats_confidence == 0.80


def test_apply_curated_override_preserves_brayden_risk_score() -> None:
    """apply_curated_override must NOT change Brayden's risk_score.

    M4-V concluded risk_score=36.3 should stay; only upside_score is lifted.
    """
    prospect = _make_prospect(
        name="Brayden Burries",
        year=2026,
        upside_score=72.6,
        risk_score=36.3,
        age=19.5,
    )
    apply_curated_override(prospect)

    assert prospect.risk_score == 36.3
    assert prospect.upside_score == 78.0  # lifted
    assert prospect.age == 19.5  # untouched


def test_apply_curated_overrides_to_db_updates_brayden_row(
    db_session: Session,
) -> None:
    """apply_curated_overrides_to_db updates Brayden in a real DB session."""
    p = Prospect(
        year=2026,
        name="Brayden Burries",
        position="SG",
        archetype="Heuristic combo guard",
        age=19.5,
        height="6-5",
        weight=195,
        school_or_league="Arizona",
        ppg=13.0,
        rpg=3.4,
        apg=4.2,
        fg_pct=44.5,
        three_pct=35.5,
        ft_pct=77.5,
        stocks=1.2,
        upside_score=72.6,
        risk_score=36.3,
        stats_source="nba_importer_heuristic",
        stats_confidence=0.30,
    )
    db_session.add(p)
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.get(Prospect, p.id)
    assert reloaded is not None
    applied = apply_curated_override(reloaded)
    db_session.commit()

    assert applied is True
    assert reloaded.position == "SG"
    assert reloaded.archetype == "Two-way combo guard"
    assert reloaded.ppg == 16.1
    assert reloaded.rpg == 4.9
    assert reloaded.apg == 2.4
    assert reloaded.fg_pct == 49.1
    assert reloaded.three_pct == 39.1
    assert reloaded.ft_pct == 80.5
    assert reloaded.stocks == 1.7
    assert reloaded.upside_score == 78.0
    assert reloaded.stats_source == "seed_manual"
    assert reloaded.stats_confidence == 0.80
    # Untouched fields
    assert reloaded.risk_score == 36.3
    assert reloaded.age == 19.5
