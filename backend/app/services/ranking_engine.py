from dataclasses import dataclass
from typing import Any, Mapping

from app.models.prospect import Prospect
from app.models.team import TeamNeed
from app.services.scouting_fit import calculate_scouting_fit


POSITION_NEED_FIELDS = {
    "PG": "need_pg",
    "SG": "need_sg",
    "SF": "need_sf",
    "PF": "need_pf",
    "C": "need_c",
}

# Composite position tokens that span multiple need slots.
# - "G" means generic guard -> contributes to need_pg AND need_sg
# - "F" means generic forward -> contributes to need_sf AND need_pf
COMBO_POSITION_NEED_FIELDS: dict[str, list[str]] = {
    "G": ["need_pg", "need_sg"],
    "F": ["need_sf", "need_pf"],
}


def _position_need_field_names(position: str) -> list[str]:
    """Return all need-field names that should be considered for a position.

    Supports single positions ("PG"), generic tokens ("G", "F"), and combo
    positions like "SG/SF" or "PF/C".  An empty list means we have no
    recognised slot, in which case downstream code falls back to a safe
    default.
    """
    if not position:
        return []
    pos = position.upper().strip()

    # Combo position: "SG/SF" -> ["SG", "SF"]
    if "/" in pos:
        fields: list[str] = []
        for token in pos.split("/"):
            token = token.strip()
            if token in POSITION_NEED_FIELDS:
                fields.append(POSITION_NEED_FIELDS[token])
            elif token in COMBO_POSITION_NEED_FIELDS:
                fields.extend(COMBO_POSITION_NEED_FIELDS[token])
        return fields

    if pos in POSITION_NEED_FIELDS:
        return [POSITION_NEED_FIELDS[pos]]
    if pos in COMBO_POSITION_NEED_FIELDS:
        return list(COMBO_POSITION_NEED_FIELDS[pos])
    return []


@dataclass(frozen=True)
class ProspectRanking:
    prospect: Prospect
    talent_score: float
    fit_score: float
    pick_value_score: float
    risk_penalty: float
    final_score: float
    reasons: list[str]
    risks: list[str]
    scouting_fit_score: float | None = None
    scouting_fit_adjustment: float | None = None
    scouting_fit_positives: list[str] | None = None
    scouting_fit_risks: list[str] | None = None


def rank_prospects(
    team_need: TeamNeed,
    pick_no: int,
    prospects: list[Prospect],
    *,
    team_need_profile: Any | None = None,
    scouting_profiles: Mapping[int | str, Any] | None = None,
    include_scouting_fit: bool = False,
) -> list[ProspectRanking]:
    rankings = [
        score_prospect(
            team_need=team_need,
            pick_no=pick_no,
            prospect=prospect,
            team_need_profile=team_need_profile,
            prospect_scouting_profile=_prospect_scouting_profile(
                prospect,
                scouting_profiles,
            ),
            include_scouting_fit=include_scouting_fit,
        )
        for prospect in prospects
    ]
    return sorted(rankings, key=lambda ranking: ranking.final_score, reverse=True)


def score_prospect(
    team_need: TeamNeed,
    pick_no: int,
    prospect: Prospect,
    *,
    team_need_profile: Any | None = None,
    prospect_scouting_profile: Any | None = None,
    include_scouting_fit: bool = False,
) -> ProspectRanking:
    talent_score = _talent_score(prospect)
    fit_score = _fit_score(team_need, prospect)
    pick_value_score = _pick_value_score(pick_no, prospect)
    risk_penalty = _risk_penalty(prospect)

    final_score = (
        talent_score * 0.40
        + fit_score * 0.30
        + pick_value_score * 0.20
        - risk_penalty * 0.10
    )

    scouting_fit = (
        calculate_scouting_fit(team_need_profile, prospect_scouting_profile)
        if include_scouting_fit
        else None
    )

    return ProspectRanking(
        prospect=prospect,
        talent_score=round(talent_score, 1),
        fit_score=round(fit_score, 1),
        pick_value_score=round(pick_value_score, 1),
        risk_penalty=round(risk_penalty, 1),
        final_score=round(final_score, 1),
        reasons=_build_reasons(team_need, prospect, talent_score, fit_score, pick_value_score),
        risks=_build_risks(prospect),
        scouting_fit_score=scouting_fit.score if scouting_fit else None,
        scouting_fit_adjustment=scouting_fit.adjustment if scouting_fit else None,
        scouting_fit_positives=scouting_fit.positives if scouting_fit else None,
        scouting_fit_risks=scouting_fit.risks if scouting_fit else None,
    )


def _prospect_scouting_profile(
    prospect: Prospect,
    scouting_profiles: Mapping[int | str, Any] | None,
) -> Any | None:
    if not scouting_profiles:
        return None
    return (
        scouting_profiles.get(prospect.id)
        or scouting_profiles.get(prospect.name)
    )


def _talent_score(prospect: Prospect) -> float:
    production = (
        min(prospect.ppg / 24, 1) * 35
        + min(prospect.rpg / 11, 1) * 15
        + min(prospect.apg / 7, 1) * 15
        + min(prospect.stocks / 3, 1) * 10
    )
    efficiency = (
        min(prospect.fg_pct / 60, 1) * 8
        + min(prospect.three_pct / 42, 1) * 9
        + min(prospect.ft_pct / 86, 1) * 8
    )
    upside = prospect.upside_score * 0.35
    return _clamp(production + efficiency + upside, 0, 100)


def _fit_score(team_need: TeamNeed, prospect: Prospect) -> float:
    field_names = _position_need_field_names(prospect.position)
    if not field_names:
        # Unknown position — fall back to SF slot to stay safe (no crash).
        field_names = ["need_sf"]
    position_needs = [getattr(team_need, name, 0) for name in field_names]
    # Use the *max* across combo slots so a prospect whose position spans
    # multiple needs (e.g. "SG/SF" when the team badly needs an SG) is still
    # fairly scored.
    position_need = max(position_needs)

    skill_fit = 0.0
    archetype = prospect.archetype.lower()

    skill_fit += team_need.need_shooting * _shooting_fit(prospect, archetype)
    skill_fit += team_need.need_creation * _creation_fit(prospect, archetype)
    skill_fit += team_need.need_defense * _defense_fit(prospect, archetype)

    raw_score = position_need * 5.5 + skill_fit * 1.6
    return _clamp(raw_score, 0, 100)


def _pick_value_score(pick_no: int, prospect: Prospect) -> float:
    expected_upside = _expected_upside_for_pick(pick_no)
    value_delta = prospect.upside_score - expected_upside
    return _clamp(72 + value_delta * 1.7, 0, 100)


def _risk_penalty(prospect: Prospect) -> float:
    efficiency_risk = 0.0
    if prospect.three_pct < 32:
        efficiency_risk += 8
    if prospect.ft_pct < 68:
        efficiency_risk += 6
    if prospect.age > 20:
        efficiency_risk += 4
    return _clamp(prospect.risk_score * 0.75 + efficiency_risk, 0, 100)


def _shooting_fit(prospect: Prospect, archetype: str) -> float:
    if prospect.three_pct >= 38 or "shooter" in archetype or "stretch" in archetype:
        return 1.2
    if prospect.three_pct >= 35:
        return 0.9
    if prospect.three_pct >= 32:
        return 0.55
    return 0.25


def _creation_fit(prospect: Prospect, archetype: str) -> float:
    if "creator" in archetype or "lead guard" in archetype:
        return 1.2
    if prospect.apg >= 5:
        return 1.0
    if prospect.apg >= 3:
        return 0.75
    return 0.35


def _defense_fit(prospect: Prospect, archetype: str) -> float:
    if "defender" in archetype or "defensive" in archetype or "rim protector" in archetype:
        return 1.2
    if prospect.stocks >= 2:
        return 1.0
    if prospect.stocks >= 1.4:
        return 0.75
    return 0.4


def _expected_upside_for_pick(pick_no: int) -> float:
    if pick_no <= 3:
        return 94
    if pick_no <= 7:
        return 88
    if pick_no <= 14:
        return 80
    if pick_no <= 20:
        return 74
    return 68


def _build_reasons(
    team_need: TeamNeed,
    prospect: Prospect,
    talent_score: float,
    fit_score: float,
    pick_value_score: float,
) -> list[str]:
    reasons: list[str] = []
    field_names = _position_need_field_names(prospect.position) or ["need_sf"]
    position_need = max(getattr(team_need, name, 0) for name in field_names)

    if position_need >= 7:
        reasons.append(f"补强球队最缺的 {prospect.position} 位置")
    if talent_score >= 85:
        reasons.append("综合天赋和基础产量处在本届前段")
    if fit_score >= 75:
        reasons.append("技能画像与球队需求匹配度高")
    if pick_value_score >= 80:
        reasons.append("在当前签位具备明显天赋溢价")
    if prospect.three_pct >= 37:
        reasons.append("外线投射样本能缓解球队空间压力")
    if prospect.stocks >= 2:
        reasons.append("抢断盖帽数据体现防守影响力")

    return reasons[:4] or ["综合评分领先同组候选人"]


def _build_risks(prospect: Prospect) -> list[str]:
    risks: list[str] = []
    archetype = prospect.archetype.lower()

    if prospect.risk_score >= 35:
        risks.append("风险评分偏高，需要进一步确认稳定性")
    if prospect.three_pct < 33:
        risks.append("三分投射存在 NBA 转化疑问")
    if prospect.ft_pct < 70:
        risks.append("罚球表现可能预示投篮手感波动")
    if prospect.apg < 2.5 and ("guard" in archetype or prospect.position in {"PG", "SG"}):
        risks.append("后卫位置的组织样本偏少")
    if prospect.stocks < 1.2:
        risks.append("防守数据影响力仍需验证")

    return risks[:3] or ["主要风险可控，仍需结合试训和体测验证"]


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
