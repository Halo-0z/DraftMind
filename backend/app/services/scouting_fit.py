from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SOURCE_WEIGHTS = {
    "manual": 1.0,
    "seed": 0.75,
    "scouting_inferred": 0.60,
    "api_inferred": 0.35,
    "news_display_only": 0.0,
}

FIT_MATCHES = [
    ("need_rim_protection", "rim_protection", "rim_protection_fit"),
    ("need_defensive_rebounding", "defensive_rebounding", "defensive_rebounding_fit"),
    ("need_offensive_rebounding", "offensive_rebounding", "offensive_rebounding_fit"),
    ("need_spacing", "spacing_value", "spacing_fit"),
    ("need_shooting_volume", "shooting_volume", "shooting_volume_fit"),
    ("need_movement_shooting", "shooting_versatility", "movement_shooting_fit"),
    ("need_self_creation", "self_creation", "self_creation_fit"),
    ("need_secondary_creation", "secondary_creation", "secondary_creation_fit"),
    ("need_playmaking", "passing_feel", "playmaking_fit"),
    ("need_rim_pressure", "rim_pressure", "rim_pressure_fit"),
    ("need_finishing", "finishing", "finishing_fit"),
    ("need_point_of_attack_defense", "point_of_attack_defense", "point_of_attack_fit"),
    ("need_switchability", "switchability", "switchability_fit"),
    ("need_team_defense", "team_defense", "team_defense_fit"),
    ("need_physicality", "physicality", "physicality_fit"),
    ("need_nba_ready", "nba_readiness", "nba_readiness_fit"),
    ("need_upside", "upside", "upside_fit"),
]


@dataclass(frozen=True)
class ScoutingFitResult:
    score: float
    adjustment: float
    positives: list[str]
    risks: list[str]
    source_weight: float
    confidence_weight: float


def calculate_scouting_fit(
    team_need_profile: Any | None,
    prospect_profile: Any | None,
) -> ScoutingFitResult:
    """Return diagnostic scouting fit without touching draft ranking.

    M3-A contract: this value is read-only explanatory data. It is not
    imported by ``ranking_engine`` and does not alter ``final_score`` or
    ``selected_player``.
    """
    if team_need_profile is None or prospect_profile is None:
        return _empty_result()

    source_weight = min(
        _profile_source_weight(_safe_str(team_need_profile, "source")),
        _profile_source_weight(_safe_str(prospect_profile, "source")),
    )
    confidence_weight = _profile_confidence_weight(
        _safe_number(team_need_profile, "need_confidence", 0.5),
        _safe_number(prospect_profile, "profile_confidence", 0.5),
        source_weight,
    )

    weighted_total = 0.0
    weight_sum = 0.0
    positives: list[str] = []

    for need_field, trait_field, positive_key in FIT_MATCHES:
        need = _rating(team_need_profile, need_field)
        trait = _rating(prospect_profile, trait_field)
        weight = _need_weight(need)
        weighted_total += trait * weight
        weight_sum += weight
        if need >= 8 and trait >= 8:
            positives.append(positive_key)

    for positive_key, need, trait in _body_type_matches(team_need_profile, prospect_profile):
        weight = _need_weight(need)
        weighted_total += trait * weight
        weight_sum += weight
        if need >= 8 and trait >= 8:
            positives.append(positive_key)

    base_score = weighted_total / weight_sum if weight_sum else 0.0
    score = round(_clamp(base_score * confidence_weight, 0.0, 10.0), 2)
    adjustment = round(_clamp((score - 5.0) * 0.4, 0.0, 2.0), 2)

    return ScoutingFitResult(
        score=score,
        adjustment=adjustment,
        positives=_dedupe(positives),
        risks=_fit_risks(team_need_profile, prospect_profile),
        source_weight=round(source_weight, 2),
        confidence_weight=round(confidence_weight, 2),
    )


def _profile_source_weight(source: str | None) -> float:
    if not source:
        return 0.0
    return SOURCE_WEIGHTS.get(source, 0.0)


def _profile_confidence_weight(
    team_confidence: float | None,
    prospect_confidence: float | None,
    source_weight: float,
) -> float:
    if source_weight <= 0:
        return 0.0
    team = _clamp(team_confidence if team_confidence is not None else 0.5, 0.0, 1.0)
    prospect = _clamp(
        prospect_confidence if prospect_confidence is not None else 0.5,
        0.0,
        1.0,
    )
    return _clamp(source_weight * team * prospect, 0.0, 1.0)


def _talent_gap_cap(talent_gap: float) -> float:
    gap = abs(talent_gap)
    if gap > 6:
        return 0.5
    if gap > 4:
        return 1.0
    return 2.0


def _fit_risks(team_need_profile: Any, prospect_profile: Any) -> list[str]:
    risks: list[str] = []
    if (
        max(_rating(team_need_profile, "need_spacing"), _rating(team_need_profile, "need_shooting_volume")) >= 8
        and min(_rating(prospect_profile, "spacing_value"), _rating(prospect_profile, "shooting_volume")) <= 4
    ):
        risks.append("spacing_risk")
    if (
        max(_rating(team_need_profile, "need_team_defense"), _rating(team_need_profile, "need_switchability")) >= 8
        and min(_rating(prospect_profile, "team_defense"), _rating(prospect_profile, "switchability")) <= 4
    ):
        risks.append("defense_risk")
    if _rating(team_need_profile, "need_nba_ready") >= 8 and _rating(prospect_profile, "nba_readiness") <= 4:
        risks.append("readiness_risk")
    if _rating(prospect_profile, "medical_risk") >= 8:
        risks.append("medical_risk")
    if (
        _rating(team_need_profile, "need_rim_protection") >= 8
        and _rating(prospect_profile, "foul_discipline") <= 4
    ):
        risks.append("foul_risk")
    if (
        max(_rating(team_need_profile, "need_size"), _rating(team_need_profile, "need_wing_depth")) >= 8
        and _size_trait(prospect_profile) <= 4
    ):
        risks.append("size_risk")
    return _dedupe(risks)


def _body_type_matches(team_need_profile: Any, prospect_profile: Any) -> list[tuple[str, int, float]]:
    size_trait = _size_trait(prospect_profile)
    big_trait = max(
        _position_trait(prospect_profile, {"C", "PF/C", "PF"}),
        _rating(prospect_profile, "rim_protection"),
        _rating(prospect_profile, "defensive_rebounding"),
        _rating(prospect_profile, "physicality"),
    )
    wing_trait = max(
        _position_trait(prospect_profile, {"SF", "SG/SF", "F"}),
        _rating(prospect_profile, "switchability"),
        _rating(prospect_profile, "team_defense"),
        size_trait,
    )
    center_trait = max(
        _position_trait(prospect_profile, {"C", "PF/C"}),
        _rating(prospect_profile, "rim_protection"),
        _rating(prospect_profile, "defensive_rebounding"),
    )
    return [
        ("center_depth_fit", _rating(team_need_profile, "need_center"), center_trait),
        ("big_depth_fit", _rating(team_need_profile, "need_big_depth"), big_trait),
        ("wing_depth_fit", _rating(team_need_profile, "need_wing_depth"), wing_trait),
        ("size_fit", _rating(team_need_profile, "need_size"), size_trait),
    ]


def _position_trait(profile: Any, matching_positions: set[str]) -> int:
    position = _safe_str(profile, "position").upper()
    if position in matching_positions:
        return 8
    if "/" in position and any(token in matching_positions for token in position.split("/")):
        return 7
    return 5


def _size_trait(profile: Any) -> float:
    height_inches = _height_inches(_safe_str(profile, "height"))
    height_score = 5.0
    if height_inches >= 82:
        height_score = 9.0
    elif height_inches >= 80:
        height_score = 8.0
    elif height_inches >= 78:
        height_score = 7.0
    elif height_inches <= 75:
        height_score = 4.0
    return max(
        height_score,
        _rating(profile, "physicality"),
        _rating(profile, "switchability"),
    )


def _height_inches(height: str) -> int:
    if not height or "-" not in height:
        return 0
    feet, inches = height.split("-", 1)
    try:
        return int(feet) * 12 + int(inches)
    except ValueError:
        return 0


def _need_weight(need_value: int) -> float:
    if need_value >= 8:
        return 1.5
    if need_value >= 6:
        return 1.0
    return 0.5


def _rating(profile: Any, field: str, default: int = 5) -> int:
    value = getattr(profile, field, default)
    if value is None:
        return default
    try:
        return int(_clamp(float(value), 1, 10))
    except (TypeError, ValueError):
        return default


def _safe_number(profile: Any, field: str, default: float) -> float:
    value = getattr(profile, field, default)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_str(profile: Any, field: str) -> str:
    value = getattr(profile, field, "")
    return value if isinstance(value, str) else ""


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _empty_result() -> ScoutingFitResult:
    return ScoutingFitResult(
        score=0.0,
        adjustment=0.0,
        positives=[],
        risks=[],
        source_weight=0.0,
        confidence_weight=0.0,
    )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
