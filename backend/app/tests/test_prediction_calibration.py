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
