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


# ---------------------------------------------------------------------------
# Phase 6A-A: ranking_engine test hardening.
#
# These tests are *additive* — they only assert behaviour the engine
# already has, in service of the §7.4 / "ranking_engine is the only
# source of truth" guarantee.  The current file has 2 tests; this
# block lifts that to 11 tests, covering:
#   * combo positions (SG/SF, PF/C)
#   * generic position tokens (G, F)
#   * unknown position fallback
#   * pick_value segment boundaries
#   * risk penalty actually lowering final_score
#   * final_score formula stability (locked-weight regression)
#   * same-talent / higher-fit ranks higher
# ---------------------------------------------------------------------------


def test_combo_position_sg_sf_uses_max_need() -> None:
    """`SG/SF` should take max(need_sg, need_sf) for fit_score.

    A prospect spanning two slots should never be **under-scored**
    relative to the slot the team needs more.
    """
    # need_sg=10 is the dominant need; need_sf is intentionally low.
    need = _need(need_sg=10, need_sf=3, need_shooting=5, need_creation=5, need_defense=5)
    combo = _prospect("Combo Wing", "SG/SF", 80, 25, 35, 2.5)
    single_sg = _prospect("Pure SG", "SG", 80, 25, 35, 2.5)
    single_sf = _prospect("Pure SF", "SF", 80, 25, 35, 2.5)

    rankings = rank_prospects(need, pick_no=10, prospects=[combo, single_sf, single_sg])
    by_name = {r.prospect.name: r for r in rankings}

    # Combo should be roughly equal to a pure SG (both use need_sg=10
    # as the max), and strictly higher than a pure SF (which is
    # capped at need_sf=3).
    assert by_name["Combo Wing"].fit_score >= by_name["Pure SG"].fit_score - 0.1
    assert by_name["Combo Wing"].fit_score > by_name["Pure SF"].fit_score + 5


def test_combo_position_pf_c_uses_max_need() -> None:
    """`PF/C` should take max(need_pf, need_c) for fit_score."""
    need = _need(need_pf=3, need_c=10, need_shooting=5, need_creation=5, need_defense=5)
    combo = _prospect("Stretch Big", "PF/C", 80, 25, 35, 2.0)
    pure_c = _prospect("Pure C", "C", 80, 25, 35, 2.0)
    pure_pf = _prospect("Pure PF", "PF", 80, 25, 35, 2.0)

    rankings = rank_prospects(need, pick_no=10, prospects=[combo, pure_pf, pure_c])
    by_name = {r.prospect.name: r for r in rankings}

    # Combo should match a pure C (both see need_c=10) and beat a pure PF.
    assert by_name["Stretch Big"].fit_score >= by_name["Pure C"].fit_score - 0.1
    assert by_name["Stretch Big"].fit_score > by_name["Pure PF"].fit_score + 5


def test_generic_g_position_uses_pg_and_sg_needs() -> None:
    """Generic `"G"` should map to *both* need_pg and need_sg and
    take the max — never silently degrade to a single slot.

    Note: a pure `"PG"` may score slightly higher than a generic `"G"`
    because position-specific archetype / creation fits reward the
    exact slot.  The contract here is the weaker one: a `"G"` must
    never be under-scored **relative to `"SG"`** when need_pg is
    dominant, i.e. it picks up the high-PG signal but does not have
    to match a `"PG"` exactly.
    """
    need = _need(need_pg=10, need_sg=3, need_shooting=5, need_creation=5, need_defense=5)
    generic_g = _prospect("Generic G", "G", 80, 25, 35, 3.0)
    pure_pg = _prospect("Pure PG", "PG", 80, 25, 35, 3.0)
    pure_sg = _prospect("Pure SG", "SG", 80, 25, 35, 3.0)

    rankings = rank_prospects(need, pick_no=8, prospects=[generic_g, pure_pg, pure_sg])
    by_name = {r.prospect.name: r for r in rankings}

    # Core invariant: a generic "G" with high need_pg must beat a
    # pure "SG" (capped at need_sg=3) by a comfortable margin.
    assert by_name["Generic G"].fit_score > by_name["Pure SG"].fit_score + 3, (
        f"generic G should benefit from need_pg, got "
        f"G={by_name['Generic G'].fit_score} vs SG={by_name['Pure SG'].fit_score}"
    )
    # A pure "PG" may still edge out the generic "G" because of
    # position-specific archetype / creation bonuses — that is fine.
    assert by_name["Pure PG"].fit_score >= by_name["Generic G"].fit_score


def test_generic_f_position_uses_sf_and_pf_needs() -> None:
    """Generic `"F"` should map to *both* need_sf and need_pf and
    take the max — never silently degrade to a single slot.

    Mirror contract to `test_generic_g_position_uses_pg_and_sg_needs`:
    a pure `"SF"` may still edge out a generic `"F"` because of
    position-specific archetype / skill-fit bonuses.  The contract
    here is the weaker one: a `"F"` must never be under-scored
    **relative to `"PF"`** when need_sf is dominant.
    """
    need = _need(need_sf=10, need_pf=3, need_shooting=5, need_creation=5, need_defense=5)
    generic_f = _prospect("Generic F", "F", 80, 25, 35, 2.0)
    pure_sf = _prospect("Pure SF", "SF", 80, 25, 35, 2.0)
    pure_pf = _prospect("Pure PF", "PF", 80, 25, 35, 2.0)

    rankings = rank_prospects(need, pick_no=8, prospects=[generic_f, pure_sf, pure_pf])
    by_name = {r.prospect.name: r for r in rankings}

    # Core invariant: a generic "F" with high need_sf must beat a
    # pure "PF" (capped at need_pf=3) by a comfortable margin.
    assert by_name["Generic F"].fit_score > by_name["Pure PF"].fit_score + 3, (
        f"generic F should benefit from need_sf, got "
        f"F={by_name['Generic F'].fit_score} vs PF={by_name['Pure PF'].fit_score}"
    )
    # A pure "SF" may still edge out the generic "F" because of
    # position-specific archetype / skill-fit bonuses — that is fine.
    assert by_name["Pure SF"].fit_score >= by_name["Generic F"].fit_score


def test_unknown_position_falls_back_to_sf_safely() -> None:
    """Empty / unknown position strings must not crash.  The engine
    falls back to a safe SF slot (see `_fit_score` line ~127).

    This is the regression net for "unknown DB row shouldn't 500".
    """
    need = _need(need_sf=9, need_pg=2, need_shooting=5, need_creation=5, need_defense=5)
    mystery_empty = Prospect(
        year=2026,
        name="Mystery Empty",
        position="",
        age=19.0,
        height="6-4",
        weight=190,
        school_or_league="Mock",
        ppg=17.0,
        rpg=4.0,
        apg=2.0,
        fg_pct=46.0,
        three_pct=35.0,
        ft_pct=80.0,
        stocks=1.5,
        archetype="Wing finisher",
        upside_score=80,
        risk_score=20,
    )
    real_sf = _prospect("Real SF", "SF", 80, 20, 35, 2.0)
    rankings = rank_prospects(need, pick_no=8, prospects=[mystery_empty, real_sf])

    assert len(rankings) == 2
    # Fallback should land the unknown prospect near the SF slot —
    # within 1 point of an actual SF on the same team need.
    by_name = {r.prospect.name: r for r in rankings}
    assert abs(
        by_name["Mystery Empty"].fit_score - by_name["Real SF"].fit_score
    ) < 1.0
    # And the scoring must remain in the valid [0, 100] range.
    for r in rankings:
        assert 0.0 <= r.fit_score <= 100.0
        assert 0.0 <= r.final_score <= 100.0


def test_pick_value_segment_boundaries() -> None:
    """`_expected_upside_for_pick` is piecewise in 4 segments, but
    `pick_value_score` itself is a **match score** — how well the
    prospect's `upside_score` aligns with the slot's expected upside.

    A prospect with `upside_score=80` is therefore not "highest at
    pick 1" — it is highest at the segment whose expected upside
    is closest to 80.  The contract we lock here is:

      1. Within a segment, the score is stable (no jitter from
         floating-point inside one bracket).
      2. Different segments yield different scores for the same
         prospect (the piecewise function is non-degenerate).
      3. For a mid-lottery-flavoured upside (80), the mid-lottery
         segment (pick 8) scores higher than the top-3 segment
         (pick 1) — which would otherwise expect upside ~94.

    We do **not** assert cross-segment monotonicity; the engine is
    explicitly a *match* score, not a "higher pick = higher score".
    """
    prospect = _prospect("Same", "PG", 80, 25, 38, 6.0)
    need = _need()

    def pv(pick_no: int) -> float:
        return rank_prospects(need, pick_no=pick_no, prospects=[prospect])[0].pick_value_score

    p1 = pv(1)
    p3 = pv(3)
    p4 = pv(4)
    p7 = pv(7)
    p8 = pv(8)
    p14 = pv(14)
    p15 = pv(15)
    p20 = pv(20)
    p25 = pv(25)
    p60 = pv(60)

    # (1) Within-segment stability — pairs (1, 3) / (4, 7) / (8, 14) /
    # (15, 20) / (25, 60) all land in the same bracket and return
    # the same score.
    assert abs(p1 - p3) < 0.01, f"pick 1 vs 3 should share a segment: {p1} vs {p3}"
    assert abs(p4 - p7) < 0.01, f"pick 4 vs 7 should share a segment: {p4} vs {p7}"
    assert abs(p8 - p14) < 0.01, f"pick 8 vs 14 should share a segment: {p8} vs {p14}"
    assert abs(p15 - p20) < 0.01, f"pick 15 vs 20 should share a segment: {p15} vs {p20}"
    assert abs(p25 - p60) < 0.01, f"pick 25 vs 60 should share a segment: {p25} vs {p60}"

    # (2) Non-degeneracy — the function actually changes between
    # segments for the same prospect, not just a constant.
    segment_picks = {p1, p4, p8, p15, p25}
    assert len(segment_picks) > 1, (
        f"pick_value_score collapsed to a single value across segments: "
        f"{{p1={p1}, p4={p4}, p8={p8}, p15={p15}, p25={p25}}}"
    )

    # (3) For upside_score=80, the mid-lottery segment (pick 8,
    # expected upside ~80) is a *better match* than the top-3
    # segment (pick 1, expected upside ~94).  This is the whole
    # point of `pick_value` as a *match* score.
    assert p8 > p1, (
        f"prospect with upside=80 should match mid-lottery (pick 8, "
        f"expected ~80) better than top-3 (pick 1, expected ~94): "
        f"got p8={p8} vs p1={p1}"
    )


def test_risk_penalty_lowers_final_score() -> None:
    """The formula is `final = talent*0.40 + fit*0.30 + pv*0.20 - risk*0.10`.

    Two prospects that are identical in talent / fit / pick_value must
    differ in final_score solely because of `risk_penalty`, with the
    riskier prospect scoring strictly lower.
    """
    need = _need(need_pg=5, need_sg=5, need_sf=5, need_pf=5, need_c=5,
                 need_shooting=5, need_creation=5, need_defense=5)
    stable = _prospect("Stable", "PG", 80, 10, 37, 6.0)
    risky = _prospect("Risky", "PG", 80, 80, 37, 6.0)

    rankings = rank_prospects(need, pick_no=8, prospects=[risky, stable])
    by_name = {r.prospect.name: r for r in rankings}
    stable_r = by_name["Stable"]
    risky_r = by_name["Risky"]

    # Same everything except risk.
    assert stable_r.talent_score == risky_r.talent_score
    assert stable_r.fit_score == risky_r.fit_score
    assert stable_r.pick_value_score == risky_r.pick_value_score
    # Risk differs as expected.
    assert risky_r.risk_penalty > stable_r.risk_penalty
    # Final score is *lower* for the risky prospect — the -0.10 weight bites.
    assert stable_r.final_score > risky_r.final_score
    # And the margin matches -0.10 * (risky.risk - stable.risk) within 0.5.
    expected_drop = (risky_r.risk_penalty - stable_r.risk_penalty) * 0.10
    actual_drop = stable_r.final_score - risky_r.final_score
    assert abs(actual_drop - expected_drop) < 0.5, (
        f"expected drop ~{expected_drop}, got {actual_drop}"
    )


def test_final_score_formula_is_stable() -> None:
    """Lock the formula: `final = round(talent*0.40 + fit*0.30 + pv*0.20 - risk*0.10, 1)`.

    If this test ever fails, somebody changed the weights or the
    rounding policy without updating Phase 6A's contract.
    """
    need = _need(need_pg=5, need_sg=5, need_sf=5, need_pf=5, need_c=5,
                 need_shooting=5, need_creation=5, need_defense=5)
    prospect = _prospect("Manual", "PG", 80, 20, 38, 6.0)
    r = rank_prospects(need, pick_no=8, prospects=[prospect])[0]

    expected = round(
        r.talent_score * 0.40
        + r.fit_score * 0.30
        + r.pick_value_score * 0.20
        - r.risk_penalty * 0.10,
        1,
    )
    assert r.final_score == expected

    # And the sub-scores must each be in [0, 100].
    for sub in (r.talent_score, r.fit_score, r.pick_value_score, r.risk_penalty):
        assert 0.0 <= sub <= 100.0


def test_same_talent_higher_fit_ranks_higher() -> None:
    """When two prospects have identical talent / pick_value / risk,
    the one with higher fit_score (because of team need) must rank
    strictly above the other.  This is the deterministic-decision
    contract: ranking is *fully* explained by the 4 sub-scores.
    """
    # All numeric inputs identical — same talent curve, same risk.
    high_fit = _prospect("High Fit", "PG", 80, 25, 38, 6.0)
    low_fit = _prospect("Low Fit", "SF", 80, 25, 38, 6.0)
    need = _need(need_pg=9, need_sg=2, need_sf=3, need_pf=2, need_c=2,
                 need_shooting=5, need_creation=5, need_defense=5)

    rankings = rank_prospects(need, pick_no=8, prospects=[low_fit, high_fit])

    # Talent / pick_value / risk must be identical.
    assert rankings[0].talent_score == rankings[1].talent_score
    assert rankings[0].pick_value_score == rankings[1].pick_value_score
    assert rankings[0].risk_penalty == rankings[1].risk_penalty
    # Fit must differ.
    assert rankings[0].fit_score > rankings[1].fit_score
    # And the higher-fit prospect must be the top-ranked.
    assert rankings[0].prospect.name == "High Fit"
    assert rankings[0].final_score > rankings[1].final_score
