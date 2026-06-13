from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TEAM_PROJECTION_TYPE_SCORE = {
    "manual_prediction": 95.0,
    "team_report": 84.0,
    "workout_signal": 76.0,
    "consensus_mock": 64.0,
}


@dataclass(frozen=True)
class PredictionCalibrationResult:
    range_score: float
    tier_score: float
    team_projection_score: float
    confidence_weight: float
    shadow_score: float
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
