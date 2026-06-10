from app.models.prospect import Prospect
from app.models.team import TeamNeed
from app.services.ranking_engine import rank_prospects


def _need(**overrides: int) -> TeamNeed:
    defaults = {
        "team_id": 1,
        "year": 2026,
        "need_pg": 9,
        "need_sg": 3,
        "need_sf": 4,
        "need_pf": 2,
        "need_c": 1,
        "need_shooting": 8,
        "need_defense": 4,
        "need_creation": 9,
    }
    defaults.update(overrides)
    return TeamNeed(**defaults)


def _prospect(
    name: str,
    position: str,
    upside_score: float,
    risk_score: float,
    three_pct: float,
    apg: float,
) -> Prospect:
    return Prospect(
        year=2026,
        name=name,
        position=position,
        age=19.0,
        height="6-4",
        weight=190,
        school_or_league="Mock",
        ppg=17.0,
        rpg=4.0,
        apg=apg,
        fg_pct=46.0,
        three_pct=three_pct,
        ft_pct=80.0,
        stocks=1.5,
        archetype="Pick-and-roll lead guard" if position == "PG" else "Wing finisher",
        upside_score=upside_score,
        risk_score=risk_score,
    )


def test_rank_prospects_rewards_team_fit() -> None:
    lead_guard = _prospect("Lead Guard", "PG", 82, 25, 38, 6.5)
    wing = _prospect("Wing", "SF", 84, 25, 34, 2.0)

    rankings = rank_prospects(_need(), pick_no=8, prospects=[wing, lead_guard])

    assert rankings[0].prospect.name == "Lead Guard"
    assert rankings[0].fit_score > rankings[1].fit_score


def test_rank_prospects_applies_risk_penalty() -> None:
    stable = _prospect("Stable Guard", "PG", 80, 15, 37, 6.0)
    risky = _prospect("Risky Guard", "PG", 80, 55, 37, 6.0)

    rankings = rank_prospects(_need(), pick_no=12, prospects=[risky, stable])

    assert rankings[0].prospect.name == "Stable Guard"
    assert rankings[1].risk_penalty > rankings[0].risk_penalty
