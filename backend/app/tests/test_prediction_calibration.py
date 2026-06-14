from __future__ import annotations

from types import SimpleNamespace

from app.services.prediction_calibration import (
    calculate_prediction_calibration,
    calculate_prediction_sort_score,
    team_projection_type_score,
)


def _ranking(final_score: float = 70.0):
    return SimpleNamespace(final_score=final_score)


def _projection(
    *,
    expected_pick: int | None = 10,
    draft_range_min: int | None = 8,
    draft_range_max: int | None = 12,
    tier: int | None = 2,
    confidence: float = 0.8,
):
    return SimpleNamespace(
        expected_pick=expected_pick,
        draft_range_min=draft_range_min,
        draft_range_max=draft_range_max,
        tier=tier,
        confidence=confidence,
    )


def _team_projection(*, projection_type: str, confidence: float = 0.8):
    return SimpleNamespace(
        projection_type=projection_type,
        confidence=confidence,
    )


def test_pick_inside_projected_range_scores_higher_than_outside_range() -> None:
    in_range = calculate_prediction_calibration(
        pick_no=10,
        ranking=_ranking(),
        prospect_projection=_projection(),
        team_projection=None,
    )
    out_of_range = calculate_prediction_calibration(
        pick_no=30,
        ranking=_ranking(),
        prospect_projection=_projection(),
        team_projection=None,
    )

    assert in_range.range_score > out_of_range.range_score
    assert in_range.shadow_score > out_of_range.shadow_score
    assert any("within projected draft range" in note for note in in_range.notes)


def test_pick_near_projected_range_scores_higher_than_clear_reach() -> None:
    near_range = calculate_prediction_calibration(
        pick_no=14,
        ranking=_ranking(),
        prospect_projection=_projection(),
        team_projection=None,
    )
    clear_reach = calculate_prediction_calibration(
        pick_no=3,
        ranking=_ranking(),
        prospect_projection=_projection(),
        team_projection=None,
    )

    assert near_range.range_score > clear_reach.range_score


def test_team_projection_type_priority_is_encoded_as_score() -> None:
    assert team_projection_type_score("manual_prediction") > team_projection_type_score(
        "team_report"
    )
    assert team_projection_type_score("team_report") > team_projection_type_score(
        "workout_signal"
    )
    assert team_projection_type_score("workout_signal") > team_projection_type_score(
        "consensus_mock"
    )


def test_team_projection_signal_raises_shadow_score() -> None:
    without_team_signal = calculate_prediction_calibration(
        pick_no=10,
        ranking=_ranking(),
        prospect_projection=_projection(),
        team_projection=None,
    )
    with_team_signal = calculate_prediction_calibration(
        pick_no=10,
        ranking=_ranking(),
        prospect_projection=_projection(),
        team_projection=_team_projection(projection_type="manual_prediction"),
    )

    assert with_team_signal.team_projection_score > 0
    assert with_team_signal.shadow_score > without_team_signal.shadow_score


def test_low_confidence_projection_weakens_shadow_influence() -> None:
    high_confidence = calculate_prediction_calibration(
        pick_no=10,
        ranking=_ranking(final_score=60.0),
        prospect_projection=_projection(confidence=0.95),
        team_projection=_team_projection(
            projection_type="manual_prediction",
            confidence=0.95,
        ),
    )
    low_confidence = calculate_prediction_calibration(
        pick_no=10,
        ranking=_ranking(final_score=60.0),
        prospect_projection=_projection(confidence=0.15),
        team_projection=_team_projection(
            projection_type="manual_prediction",
            confidence=0.15,
        ),
    )

    assert high_confidence.confidence_weight > low_confidence.confidence_weight
    assert high_confidence.shadow_score > low_confidence.shadow_score


def test_prediction_sort_score_rewards_strong_manual_team_signal() -> None:
    sort_score, eligible, notes = calculate_prediction_sort_score(
        pick_no=2,
        ranking=_ranking(final_score=61.0),
        prospect_projection=SimpleNamespace(
            expected_pick=2,
            draft_range_min=1,
            draft_range_max=5,
            tier=1,
            source="manual_projection",
            confidence=0.95,
        ),
        team_projection=SimpleNamespace(
            projection_type="manual_prediction",
            source="manual_projection",
            confidence=0.95,
        ),
        original_top_final_score=74.8,
    )

    assert eligible is True
    assert sort_score > 74.8
    assert any("Top-tier early-pick protection" in note for note in notes)


def test_prediction_sort_score_blocks_large_gap_consensus_lock() -> None:
    sort_score, eligible, notes = calculate_prediction_sort_score(
        pick_no=2,
        ranking=_ranking(final_score=45.0),
        prospect_projection=SimpleNamespace(
            expected_pick=2,
            draft_range_min=1,
            draft_range_max=5,
            tier=1,
            source="consensus_reference",
            confidence=0.95,
        ),
        team_projection=SimpleNamespace(
            projection_type="consensus_mock",
            source="consensus_reference",
            confidence=0.95,
        ),
        original_top_final_score=74.8,
    )

    assert eligible is False
    assert sort_score < 74.8
    assert any("guardrail blocked" in note for note in notes)


def test_news_display_only_projection_source_does_not_boost_selection() -> None:
    sort_score, eligible, notes = calculate_prediction_sort_score(
        pick_no=2,
        ranking=_ranking(final_score=70.0),
        prospect_projection=SimpleNamespace(
            expected_pick=2,
            draft_range_min=1,
            draft_range_max=5,
            tier=1,
            source="news_display_only",
            confidence=0.99,
        ),
        team_projection=SimpleNamespace(
            projection_type="manual_prediction",
            source="news_display_only",
            confidence=0.99,
        ),
        original_top_final_score=74.8,
    )

    assert eligible is True
    assert sort_score <= 70.0
    assert sort_score < 74.8
    assert any("within projected draft range" in note for note in notes)


# ---------------------------------------------------------------------------
# B0-I: high market-prior availability guardrail
# ---------------------------------------------------------------------------


def _market_prior_projection(
    *,
    expected_pick: int = 5,
    draft_range_min: int = 4,
    draft_range_max: int = 7,
    tier: int = 2,
    confidence: float = 0.74,
    source: str = "consensus_reference",
):
    """A top-8 consensus_reference projection (the Keaton profile)."""
    return SimpleNamespace(
        expected_pick=expected_pick,
        draft_range_min=draft_range_min,
        draft_range_max=draft_range_max,
        tier=tier,
        source=source,
        confidence=confidence,
    )


def test_availability_guardrail_triggers_for_in_range_top_market_prior() -> None:
    """Keaton-style case: expected #5, range 4-7, in range, final_score gap
    11.7 (which exceeds the normal 8.0 guardrail).  The availability floor
    must make him eligible and raise his sort_score near the original top."""
    sort_score, eligible, notes = calculate_prediction_sort_score(
        pick_no=5,
        ranking=_ranking(final_score=55.4),
        prospect_projection=_market_prior_projection(),
        team_projection=SimpleNamespace(
            projection_type="consensus_mock",
            source="consensus_reference",
            confidence=0.62,
        ),
        original_top_final_score=67.1,
    )

    assert eligible is True
    # Team-match floor = original_top - 0.5 = 66.6
    assert sort_score == 66.6
    assert any("availability protection" in note.lower() for note in notes)
    assert any("matching team projection signal" in note for note in notes)


def test_availability_guardrail_floor_raises_score_above_plain_adjustment() -> None:
    """Without the floor, the best a consensus_reference prospect can reach is
    final_score + small adjustment (~+2.5).  The floor must beat that."""
    with_floor, _, _ = calculate_prediction_sort_score(
        pick_no=5,
        ranking=_ranking(final_score=55.4),
        prospect_projection=_market_prior_projection(),
        team_projection=SimpleNamespace(
            projection_type="consensus_mock",
            source="consensus_reference",
            confidence=0.62,
        ),
        original_top_final_score=67.1,
    )
    # The plain adjustment path tops out around 55.4 + 2.5 = 57.9 (verified in
    # the preflight diagnosis).  The floor must be meaningfully higher.
    assert with_floor > 60.0


def test_availability_guardrail_hard_rejected_when_final_score_gap_is_huge() -> None:
    """gap = 67.1 - 45 = 22.1 > HARD_REJECT 20 -> DraftMind vetoes consensus,
    floor must NOT apply, and the prospect stays below the original top."""
    sort_score, eligible, notes = calculate_prediction_sort_score(
        pick_no=5,
        ranking=_ranking(final_score=45.0),
        prospect_projection=_market_prior_projection(),
        team_projection=SimpleNamespace(
            projection_type="consensus_mock",
            source="consensus_reference",
            confidence=0.62,
        ),
        original_top_final_score=67.1,
    )

    assert eligible is False
    assert sort_score < 67.1
    assert not any("availability protection" in note.lower() for note in notes)
    assert any("vetoed" in note.lower() for note in notes)


def test_availability_guardrail_does_not_trigger_when_expected_pick_above_8() -> None:
    sort_score, eligible, notes = calculate_prediction_sort_score(
        pick_no=9,
        ranking=_ranking(final_score=60.0),
        prospect_projection=_market_prior_projection(
            expected_pick=9, draft_range_min=7, draft_range_max=11,
        ),
        team_projection=None,
        original_top_final_score=71.0,
    )

    # gap is 11 (>8), so without the floor this would be ineligible.
    assert eligible is False
    assert not any("availability protection" in note.lower() for note in notes)


def test_availability_guardrail_does_not_trigger_when_confidence_below_threshold() -> None:
    sort_score, eligible, notes = calculate_prediction_sort_score(
        pick_no=5,
        ranking=_ranking(final_score=60.0),
        prospect_projection=_market_prior_projection(confidence=0.69),
        team_projection=None,
        original_top_final_score=71.0,
    )

    assert eligible is False
    assert not any("availability protection" in note.lower() for note in notes)


def test_availability_guardrail_does_not_trigger_before_range_min() -> None:
    """Pick earlier than draft_range_min is a reach and must not be propped up
    by the floor (otherwise the guardrail would force an early reach)."""
    sort_score, eligible, notes = calculate_prediction_sort_score(
        pick_no=3,
        ranking=_ranking(final_score=55.4),
        prospect_projection=_market_prior_projection(),  # range 4-7
        team_projection=None,
        original_top_final_score=67.1,
    )

    assert not any("availability protection" in note.lower() for note in notes)


def test_availability_guardrail_does_not_trigger_past_range_plus_grace() -> None:
    """Pick beyond draft_range_max + grace has left the protection window."""
    sort_score, eligible, notes = calculate_prediction_sort_score(
        pick_no=10,  # range_max(7) + grace(2) = 9, so 10 is past the window
        ranking=_ranking(final_score=55.4),
        prospect_projection=_market_prior_projection(),
        team_projection=None,
        original_top_final_score=67.1,
    )

    assert not any("availability protection" in note.lower() for note in notes)


def test_availability_guardrail_generic_floor_is_weaker_than_team_match_floor() -> None:
    """Without a TeamPickProjection for the current pick, the floor uses the
    larger GENERIC_FLOOR_GAP (2.0) and sits lower than the team-match floor
    (0.5).  Both still prevent an abnormal slide, but a same-team signal is
    stronger and can win a near-tie that the generic floor would lose."""
    team_match_score, _, _ = calculate_prediction_sort_score(
        pick_no=5,
        ranking=_ranking(final_score=55.4),
        prospect_projection=_market_prior_projection(),
        team_projection=SimpleNamespace(
            projection_type="consensus_mock",
            source="consensus_reference",
            confidence=0.62,
        ),
        original_top_final_score=67.1,
    )
    generic_score, _, generic_notes = calculate_prediction_sort_score(
        pick_no=5,
        ranking=_ranking(final_score=55.4),
        prospect_projection=_market_prior_projection(),
        team_projection=None,
        original_top_final_score=67.1,
    )

    assert team_match_score > generic_score  # 66.6 vs 65.1
    # Generic floor still triggers protection (just at a lower level).
    assert any("availability protection" in note.lower() for note in generic_notes)
    assert all("matching team projection signal" not in note for note in generic_notes)


def test_availability_guardrail_floor_never_exceeds_original_top() -> None:
    """The floor may at most tie the original top from below; it must never
    let a consensus prospect leapfrog the original top.  This is the
    anti-mock-lock guarantee.

    We use a gap of 15 (within the relaxed 16 gap, below the 20 hard-reject)
    so the floor is genuinely applied rather than hard-rejected.
    """
    sort_score, eligible, _ = calculate_prediction_sort_score(
        pick_no=5,
        ranking=_ranking(final_score=52.1),  # gap 15, below hard-reject 20
        prospect_projection=_market_prior_projection(),
        team_projection=SimpleNamespace(
            projection_type="consensus_mock",
            source="consensus_reference",
            confidence=0.62,
        ),
        original_top_final_score=67.1,
    )

    assert eligible is True
    assert sort_score <= 67.1  # never above the original top
    # team-match floor = 67.1 - 0.5 = 66.6, exactly at the floor.
    assert sort_score == 66.6


def test_availability_guardrail_boundary_pick_at_range_max_plus_grace_triggers() -> None:
    """pick == draft_range_max + grace is the last pick inside the window."""
    sort_score, eligible, notes = calculate_prediction_sort_score(
        pick_no=9,  # 7 + grace(2) = 9, inclusive boundary
        ranking=_ranking(final_score=55.4),
        prospect_projection=_market_prior_projection(),
        team_projection=None,
        original_top_final_score=67.1,
    )

    assert eligible is True
    assert any("availability protection" in note.lower() for note in notes)


# ---------------------------------------------------------------------------
# B0-I edge fix: availability floor is gated by projection source.
#
# Only ``consensus_reference`` (market prior) and ``manual_projection``
# (explicit human prediction) may trigger the strong availability floor.
# ``seed_projection`` is demo/development data and must not gain the floor
# even when its other gate signals (expected_pick, confidence, range) look
# strong — otherwise seed data would acquire outsized selection power.
# It can still participate in the ordinary weak prediction-calibration
# adjustment (verified separately).
# ---------------------------------------------------------------------------


def test_availability_floor_excludes_seed_projection_prospect_source() -> None:
    """A seed_projection prospect with an otherwise-strong gate (top-8, high
    confidence, in range) must NOT trigger the availability floor."""
    sort_score, eligible, notes = calculate_prediction_sort_score(
        pick_no=5,
        ranking=_ranking(final_score=55.4),
        prospect_projection=_market_prior_projection(source="seed_projection"),
        team_projection=SimpleNamespace(
            projection_type="consensus_mock",
            source="consensus_reference",
            confidence=0.62,
        ),
        original_top_final_score=67.1,
    )

    # final_score gap 11.7 > 8.0, so without the relaxed gap the prospect is
    # ineligible.  The floor must NOT rescue him.
    assert eligible is False
    assert not any("availability protection" in note.lower() for note in notes)


def test_seed_projection_still_gets_ordinary_calibration_adjustment() -> None:
    """seed_projection must remain eligible for the ordinary weak
    prediction-calibration adjustment (range/tier/team adjustments).  It is
    only the strong availability FLOOR that is withheld.

    We use a gap that is comfortably inside the normal 8.0 guardrail so the
    seed prospect is eligible on its own merits, then confirm its sort_score
    reflects the ordinary adjustment path and is NOT lifted to the floor."""
    # gap = 67.1 - 60.0 = 7.1, inside the 8.0 guardrail -> eligible.
    sort_score, eligible, notes = calculate_prediction_sort_score(
        pick_no=5,
        ranking=_ranking(final_score=60.0),
        prospect_projection=_market_prior_projection(source="seed_projection"),
        team_projection=SimpleNamespace(
            projection_type="consensus_mock",
            source="consensus_reference",
            confidence=0.62,
        ),
        original_top_final_score=67.1,
    )

    assert eligible is True
    # The seed prospect IS eligible and gets the ordinary range/tier/team
    # adjustments (so sort_score rises above the raw 60.0), but it must NOT
    # be lifted to the team-match floor (67.1 - 0.5 = 66.6) or even the
    # generic floor (67.1 - 2.0 = 65.1).
    assert sort_score > 60.0
    assert sort_score < 65.1  # well below the generic floor
    assert not any("availability protection" in note.lower() for note in notes)


def test_availability_floor_triggers_for_consensus_reference_prospect_source() -> None:
    """Regression guard: consensus_reference (the Keaton path) still
    triggers the floor after the source allow-list was introduced."""
    sort_score, eligible, notes = calculate_prediction_sort_score(
        pick_no=5,
        ranking=_ranking(final_score=55.4),
        prospect_projection=_market_prior_projection(source="consensus_reference"),
        team_projection=SimpleNamespace(
            projection_type="consensus_mock",
            source="consensus_reference",
            confidence=0.62,
        ),
        original_top_final_score=67.1,
    )

    assert eligible is True
    assert sort_score == 66.6  # team-match floor = 67.1 - 0.5
    assert any("availability protection" in note.lower() for note in notes)


def test_availability_floor_triggers_for_manual_projection_prospect_source() -> None:
    """manual_projection is the other allowed source for the floor."""
    sort_score, eligible, notes = calculate_prediction_sort_score(
        pick_no=5,
        ranking=_ranking(final_score=55.4),
        prospect_projection=_market_prior_projection(source="manual_projection"),
        team_projection=SimpleNamespace(
            projection_type="manual_prediction",
            source="manual_projection",
            confidence=0.85,
        ),
        original_top_final_score=67.1,
    )

    assert eligible is True
    assert sort_score == 66.6  # team-match floor
    assert any("availability protection" in note.lower() for note in notes)


def test_display_only_team_source_falls_back_to_generic_floor() -> None:
    """When the prospect source is allowed (consensus_reference) but the
    team projection's source is display-only / unknown, the team_match flag
    must be False so the weaker generic floor (orig_top - 2.0) is used
    instead of the stronger team-match floor (orig_top - 0.5).

    This protects against future display-only / unknown team sources being
    treated as strong same-team market signals."""
    sort_score, eligible, notes = calculate_prediction_sort_score(
        pick_no=5,
        ranking=_ranking(final_score=55.4),
        prospect_projection=_market_prior_projection(source="consensus_reference"),
        team_projection=SimpleNamespace(
            projection_type="manual_prediction",
            source="news_display_only",  # display-only -> NOT a strong team match
            confidence=0.99,
        ),
        original_top_final_score=67.1,
    )

    assert eligible is True
    # Generic floor = 67.1 - 2.0 = 65.1 (NOT the team-match 66.6).
    assert sort_score == 65.1
    notes_joined = " ".join(notes).lower()
    assert "availability protection" in notes_joined
    # And the note must NOT claim a matching team signal.
    assert "matching team projection signal" not in notes_joined
