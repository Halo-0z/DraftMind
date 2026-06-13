from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TEAM_PROJECTION_TYPE_SCORE = {
    "manual_prediction": 95.0,
    "team_report": 84.0,
    "workout_signal": 76.0,
    "consensus_mock": 64.0,
}
PROSPECT_PROJECTION_SOURCE_WEIGHT = {
    "manual_projection": 1.0,
    "seed_projection": 0.7,
    "consensus_reference": 0.45,
}
TEAM_PROJECTION_TYPE_ADJUSTMENT = {
    "manual_prediction": 6.0,
    "team_report": 4.8,
    "workout_signal": 3.6,
    "consensus_mock": 2.4,
}
MAX_CALIBRATION_FINAL_SCORE_GAP = 8.0
VERY_STRONG_MANUAL_FINAL_SCORE_GAP = 16.0


@dataclass(frozen=True)
class PredictionCalibrationResult:
    range_score: float
    tier_score: float
    team_projection_score: float
    confidence_weight: float
    shadow_score: float
    notes: list[str]


@dataclass(frozen=True)
class PredictionSelectionResult:
    sort_score: float
    rank: int
    delta: int
    applied: bool
    eligible: bool
    notes: list[str]


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _get_number(obj: Any, attr: str) -> float | None:
    value = getattr(obj, attr, None)
    if value is None:
        return None
    return float(value)


def team_projection_type_score(projection_type: str | None) -> float:
    if not projection_type:
        return 0.0
    return TEAM_PROJECTION_TYPE_SCORE.get(projection_type, 50.0)


def _source_weight(source: str | None) -> float:
    if not source:
        return 0.0
    return PROSPECT_PROJECTION_SOURCE_WEIGHT.get(source, 0.0)


def _team_adjustment(projection_type: str | None) -> float:
    if not projection_type:
        return 0.0
    return TEAM_PROJECTION_TYPE_ADJUSTMENT.get(projection_type, 0.0)


def _range_score(
    *,
    pick_no: int,
    prospect_projection: Any | None,
    notes: list[str],
) -> float:
    if prospect_projection is None:
        notes.append("No prospect projection signal available.")
        return 50.0

    range_min = _get_number(prospect_projection, "draft_range_min")
    range_max = _get_number(prospect_projection, "draft_range_max")
    expected_pick = _get_number(prospect_projection, "expected_pick")

    if range_min is None and range_max is None and expected_pick is None:
        notes.append("Projection signal has no expected pick or draft range.")
        return 50.0

    if range_min is None:
        range_min = expected_pick
    if range_max is None:
        range_max = expected_pick
    if range_min is None or range_max is None:
        return 50.0

    if range_min > range_max:
        range_min, range_max = range_max, range_min

    if range_min <= pick_no <= range_max:
        notes.append("Pick is within projected draft range.")
        return 90.0

    if pick_no < range_min:
        distance = range_min - pick_no
        if distance <= 3:
            notes.append("Pick is slightly earlier than projected range.")
            return 68.0
        notes.append("Pick is much earlier than projected range; possible reach.")
        return 32.0

    distance = pick_no - range_max
    if distance <= 3:
        notes.append("Pick is slightly later than projected range.")
        return 72.0
    notes.append("Pick is much later than projected range; availability risk.")
    return 36.0


def _tier_band(tier: int | None) -> tuple[int, int] | None:
    if tier is None:
        return None
    if tier <= 1:
        return (1, 5)
    if tier == 2:
        return (6, 10)
    if tier == 3:
        return (1, 14)
    if tier == 4:
        return (1, 30)
    return (1, 60)


def _tier_score(
    *,
    pick_no: int,
    prospect_projection: Any | None,
    notes: list[str],
) -> float:
    if prospect_projection is None:
        return 50.0
    tier_value = getattr(prospect_projection, "tier", None)
    if tier_value is None:
        return 50.0
    band = _tier_band(int(tier_value))
    if band is None:
        return 50.0
    low, high = band
    if low <= pick_no <= high:
        notes.append(f"Pick is reasonable for projected tier {int(tier_value)}.")
        return 85.0
    distance = min(abs(pick_no - low), abs(pick_no - high))
    if distance <= 5:
        notes.append(f"Pick is near projected tier {int(tier_value)} band.")
        return 65.0
    notes.append(f"Pick is outside projected tier {int(tier_value)} band.")
    return 42.0


def _confidence_weight(
    *,
    prospect_projection: Any | None,
    team_projection: Any | None,
) -> float:
    prospect_confidence = _get_number(prospect_projection, "confidence") or 0.0
    team_confidence = _get_number(team_projection, "confidence") or 0.0
    return _clamp(max(prospect_confidence, team_confidence), 0.0, 1.0)


def calculate_prediction_calibration(
    *,
    pick_no: int,
    ranking: Any,
    prospect_projection: Any | None,
    team_projection: Any | None,
) -> PredictionCalibrationResult:
    notes: list[str] = []
    range_score = _range_score(
        pick_no=pick_no,
        prospect_projection=prospect_projection,
        notes=notes,
    )
    tier_score = _tier_score(
        pick_no=pick_no,
        prospect_projection=prospect_projection,
        notes=notes,
    )
    team_score = team_projection_type_score(
        getattr(team_projection, "projection_type", None),
    )
    if team_projection is not None:
        notes.append(
            f"Team-specific projection signal: {team_projection.projection_type}.",
        )

    confidence = _confidence_weight(
        prospect_projection=prospect_projection,
        team_projection=team_projection,
    )
    base_final_score = _clamp(float(getattr(ranking, "final_score", 0.0)))
    market_component = (
        range_score * 0.45
        + tier_score * 0.20
        + team_score * 0.35
    )
    market_weight = confidence * 0.35
    shadow_score = (
        base_final_score * (1.0 - market_weight)
        + market_component * market_weight
    )

    return PredictionCalibrationResult(
        range_score=round(range_score, 1),
        tier_score=round(tier_score, 1),
        team_projection_score=round(team_score, 1),
        confidence_weight=round(confidence, 3),
        shadow_score=round(shadow_score, 2),
        notes=notes,
    )


def calculate_prediction_sort_score(
    *,
    pick_no: int,
    ranking: Any,
    prospect_projection: Any | None,
    team_projection: Any | None,
    original_top_final_score: float,
) -> tuple[float, bool, list[str]]:
    """Return an opt-in selection score for actual-outcome prediction mode.

    This deliberately does not mutate ``final_score`` or any ranking-engine
    component.  It is a separate sort key with guardrails so weak consensus
    signals cannot hard-lock a large reach.
    """
    notes: list[str] = []
    final_score = float(getattr(ranking, "final_score", 0.0))
    final_gap = original_top_final_score - final_score
    prospect_confidence = _get_number(prospect_projection, "confidence") or 0.0
    team_confidence = _get_number(team_projection, "confidence") or 0.0
    confidence = _clamp(max(prospect_confidence, team_confidence), 0.0, 1.0)
    source_weight = _source_weight(getattr(prospect_projection, "source", None))
    team_type = getattr(team_projection, "projection_type", None)
    team_source_weight = _source_weight(getattr(team_projection, "source", None))

    strong_manual_signal = (
        team_type == "manual_prediction"
        and getattr(team_projection, "source", None) == "manual_projection"
        and team_confidence >= 0.85
    )
    max_gap = (
        VERY_STRONG_MANUAL_FINAL_SCORE_GAP
        if strong_manual_signal
        else MAX_CALIBRATION_FINAL_SCORE_GAP
    )
    eligible = final_gap <= max_gap
    if not eligible:
        notes.append(
            f"Calibration guardrail blocked selection: final_score gap {round(final_gap, 2)} exceeds {max_gap}."
        )

    range_score = _range_score(
        pick_no=pick_no,
        prospect_projection=prospect_projection,
        notes=notes,
    )
    tier_score = _tier_score(
        pick_no=pick_no,
        prospect_projection=prospect_projection,
        notes=notes,
    )
    adjustment = 0.0
    adjustment += (range_score - 50.0) * 0.12 * confidence * source_weight
    adjustment += (tier_score - 50.0) * 0.06 * confidence * source_weight

    if team_projection is not None:
        adjustment += _team_adjustment(team_type) * team_confidence * team_source_weight
        notes.append(f"Team projection adjustment from {team_type}.")

    expected_pick = _get_number(prospect_projection, "expected_pick")
    range_min = _get_number(prospect_projection, "draft_range_min")
    range_max = _get_number(prospect_projection, "draft_range_max")
    tier = getattr(prospect_projection, "tier", None)
    if (
        tier is not None
        and int(tier) <= 1
        and expected_pick is not None
        and expected_pick <= 3
        and range_min is not None
        and range_max is not None
        and range_min <= pick_no <= range_max
    ):
        adjustment += 2.5 * confidence * source_weight
        notes.append("Top-tier early-pick protection applied.")

    if range_min is not None and pick_no < range_min - 2:
        reach_penalty = min(14.0, 6.0 + (range_min - pick_no - 2) * 1.5)
        adjustment -= reach_penalty * max(source_weight, 0.3)
        notes.append(f"Reach penalty applied: {round(reach_penalty, 1)}.")

    sort_score = final_score + adjustment
    if not eligible:
        sort_score = min(sort_score, original_top_final_score - 0.01)

    return round(sort_score, 2), eligible, notes
