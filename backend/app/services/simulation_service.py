from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.draft import DraftOrder
from app.models.projection import ProspectDraftProjection, TeamPickProjection
from app.models.prospect import Prospect
from app.models.scouting import ProspectScoutingProfile, TeamNeedProfile
from app.models.team import TeamNeed
from app.schemas.recommendation import RankedProspectRead, ScoreBreakdown
from app.schemas.simulation import (
    LockedPickRequest,
    SimulateRequest,
    SimulateResponse,
    SimulatedPickRead,
    TradeEvaluation,
)
from app.services.ranking_engine import ProspectRanking, rank_prospects
from app.services.prediction_calibration import (
    PredictionCalibrationResult,
    PredictionSelectionResult,
    calculate_prediction_calibration,
    calculate_prediction_sort_score,
    has_same_team_projection_priority,
)
from app.services.prospect_availability import (
    filter_available_prospects,
    is_officially_unavailable_for_draft,
)
from app.services.draft_day_accuracy import (
    reorder_rankings_by_consensus_priority,
)
from app.services.team_need_adjustment import (
    TeamNeedSnapshot,
    adjust_team_need_after_pick,
)
from app.services.team_need_service import get_or_infer_team_need
from app.services.rumor_extractor import NewsSignal, extract_signals


PROJECTION_SOURCE_PRIORITY = {
    "manual_projection": 0,
    "seed_projection": 1,
    "consensus_reference": 2,
}
TEAM_PROJECTION_TYPE_PRIORITY = {
    "manual_prediction": 0,
    "team_report": 1,
    "workout_signal": 2,
    "consensus_mock": 3,
}
SAME_TEAM_PROJECTION_PRIORITY_EPSILON = 0.01
SAME_TEAM_PROJECTION_PRIORITY_NOTE = (
    "Same-team TeamPickProjection priority applied."
)
MARKET_SLIP_WARNING = (
    "Market slip warning: selected 8+ picks later than expected market range."
)
NO_MARKET_HEURISTIC_WARNING = (
    "No market reference with heuristic stats; selection carries elevated data-risk."
)
LOW_CONFIDENCE_STATS_WARNING = (
    "Low-confidence imported stats used in ranking context."
)


@dataclass(frozen=True)
class ProjectionDiagnostics:
    prospect_projection: ProspectDraftProjection | None = None
    team_projection: TeamPickProjection | None = None
    prediction_calibration: PredictionCalibrationResult | None = None
    prediction_shadow_rank: int | None = None
    prediction_shadow_delta: int | None = None
    prediction_selection: PredictionSelectionResult | None = None


def _diagnostic_warnings(
    *,
    prospect: Prospect,
    prospect_projection: ProspectDraftProjection | None,
    selected_pick_no: int | None,
) -> list[str] | None:
    if selected_pick_no is None:
        return None

    warnings: list[str] = []
    expected_pick = (
        prospect_projection.expected_pick if prospect_projection else None
    )
    if (
        expected_pick is not None
        and expected_pick <= 30
        and selected_pick_no - expected_pick >= 8
    ):
        warnings.append(MARKET_SLIP_WARNING)

    stats_source = getattr(prospect, "stats_source", None)
    stats_confidence = getattr(prospect, "stats_confidence", None)
    if (
        expected_pick is None
        and stats_source == "nba_importer_heuristic"
        and selected_pick_no <= 40
    ):
        warnings.append(NO_MARKET_HEURISTIC_WARNING)
    if (
        stats_confidence is not None
        and stats_confidence <= 0.30
        and selected_pick_no <= 40
    ):
        warnings.append(LOW_CONFIDENCE_STATS_WARNING)

    return warnings or None


# ---------------------------------------------------------------------------
# Helper: snapshot an ORM TeamNeed row into the in-memory TeamNeedSnapshot
# ---------------------------------------------------------------------------


def _snapshot_from_orm(orm: TeamNeed) -> TeamNeedSnapshot:
    return TeamNeedSnapshot(
        team_id=orm.team_id,
        year=orm.year,
        need_pg=orm.need_pg,
        need_sg=orm.need_sg,
        need_sf=orm.need_sf,
        need_pf=orm.need_pf,
        need_c=orm.need_c,
        need_shooting=orm.need_shooting,
        need_defense=orm.need_defense,
        need_creation=orm.need_creation,
    )


def _to_ranked_read(
    ranking: ProspectRanking,
    projection: ProjectionDiagnostics | None = None,
    candidate_source: str | None = None,
    selected_pick_no: int | None = None,
    include_market_alignment: bool = False,
) -> RankedProspectRead:
    prospect_projection = projection.prospect_projection if projection else None
    team_projection = projection.team_projection if projection else None
    prediction_calibration = (
        projection.prediction_calibration if projection else None
    )
    prediction_selection = projection.prediction_selection if projection else None
    market_alignment = (
        _market_alignment_diagnostics(
            prospect_projection=prospect_projection,
            selected_pick_no=selected_pick_no,
        )
        if include_market_alignment
        else {
            "market_expected_pick": None,
            "draftmind_selected_pick": None,
            "market_pick_delta": None,
            "market_alignment_label": None,
            "market_alignment_notes": None,
        }
    )
    return RankedProspectRead(
        prospect=ranking.prospect,
        scores=ScoreBreakdown(
            talent_score=ranking.talent_score,
            fit_score=ranking.fit_score,
            pick_value_score=ranking.pick_value_score,
            risk_penalty=ranking.risk_penalty,
            final_score=ranking.final_score,
        ),
        reasons=ranking.reasons,
        risks=ranking.risks,
        scouting_fit_score=ranking.scouting_fit_score,
        scouting_fit_positives=ranking.scouting_fit_positives,
        scouting_fit_risks=ranking.scouting_fit_risks,
        ranking_sort_score=ranking.ranking_sort_score,
        scouting_tiebreaker_applied=ranking.scouting_tiebreaker_applied,
        scouting_tiebreaker_delta=ranking.scouting_tiebreaker_delta,
        projection_expected_pick=(
            prospect_projection.expected_pick if prospect_projection else None
        ),
        projection_draft_range_min=(
            prospect_projection.draft_range_min if prospect_projection else None
        ),
        projection_draft_range_max=(
            prospect_projection.draft_range_max if prospect_projection else None
        ),
        projection_tier=prospect_projection.tier if prospect_projection else None,
        projection_confidence=(
            prospect_projection.confidence if prospect_projection else None
        ),
        projection_source=prospect_projection.source if prospect_projection else None,
        projection_notes=prospect_projection.notes if prospect_projection else None,
        team_projection_type=(
            team_projection.projection_type if team_projection else None
        ),
        team_projection_confidence=(
            team_projection.confidence if team_projection else None
        ),
        team_projection_notes=team_projection.notes if team_projection else None,
        prediction_range_score=(
            prediction_calibration.range_score if prediction_calibration else None
        ),
        prediction_tier_score=(
            prediction_calibration.tier_score if prediction_calibration else None
        ),
        prediction_team_projection_score=(
            prediction_calibration.team_projection_score
            if prediction_calibration else None
        ),
        prediction_confidence_weight=(
            prediction_calibration.confidence_weight
            if prediction_calibration else None
        ),
        prediction_shadow_score=(
            prediction_calibration.shadow_score if prediction_calibration else None
        ),
        prediction_shadow_rank=(
            projection.prediction_shadow_rank if projection else None
        ),
        prediction_shadow_delta=(
            projection.prediction_shadow_delta if projection else None
        ),
        prediction_calibration_notes=(
            prediction_calibration.notes if prediction_calibration else None
        ),
        prediction_sort_score=(
            prediction_selection.sort_score if prediction_selection else None
        ),
        prediction_selection_rank=(
            prediction_selection.rank if prediction_selection else None
        ),
        prediction_selection_delta=(
            prediction_selection.delta if prediction_selection else None
        ),
        prediction_selection_applied=(
            prediction_selection.applied if prediction_selection else False
        ),
        prediction_selection_notes=(
            prediction_selection.notes if prediction_selection else None
        ),
        market_expected_pick=market_alignment["market_expected_pick"],
        draftmind_selected_pick=market_alignment["draftmind_selected_pick"],
        market_pick_delta=market_alignment["market_pick_delta"],
        market_alignment_label=market_alignment["market_alignment_label"],
        market_alignment_notes=market_alignment["market_alignment_notes"],
        diagnostics_warnings=_diagnostic_warnings(
            prospect=ranking.prospect,
            prospect_projection=prospect_projection,
            selected_pick_no=selected_pick_no,
        ),
        candidate_source=candidate_source,
    )


def _market_alignment_label(delta: int | None) -> str:
    if delta is None:
        return "无市场参考"
    if delta == 0:
        return "一致"
    if abs(delta) <= 2:
        return "接近"
    if -6 <= delta <= -3:
        return "高于市场"
    if delta <= -7:
        return "明显高于市场"
    if 3 <= delta <= 6:
        return "低于市场"
    return "明显低于市场"


def _market_alignment_diagnostics(
    *,
    prospect_projection: ProspectDraftProjection | None,
    selected_pick_no: int | None,
) -> dict[str, int | str | list[str] | None]:
    expected_pick = (
        prospect_projection.expected_pick if prospect_projection else None
    )
    if expected_pick is None:
        return {
            "market_expected_pick": None,
            "draftmind_selected_pick": selected_pick_no,
            "market_pick_delta": None,
            "market_alignment_label": "无市场参考",
            "market_alignment_notes": [
                "暂无市场顺位参考，结果主要来自 DraftMind 原始评分。"
            ],
        }
    if selected_pick_no is None:
        return {
            "market_expected_pick": expected_pick,
            "draftmind_selected_pick": None,
            "market_pick_delta": None,
            "market_alignment_label": None,
            "market_alignment_notes": None,
        }

    delta = selected_pick_no - expected_pick
    label = _market_alignment_label(delta)
    if delta == 0:
        note = (
            f"市场预计约第 {expected_pick} 顺位，DraftMind 在第 "
            f"{selected_pick_no} 顺位选择，基本一致。"
        )
    elif abs(delta) <= 2:
        direction = "更早" if delta < 0 else "更晚"
        note = (
            f"市场预计约第 {expected_pick} 顺位，DraftMind 在第 "
            f"{selected_pick_no} 顺位选择，略比市场{direction}。"
        )
    elif delta < 0:
        note = (
            f"市场预计约第 {expected_pick} 顺位，DraftMind 在第 "
            f"{selected_pick_no} 顺位选择，说明模型比市场更看好他。"
        )
    else:
        note = (
            f"市场预计约第 {expected_pick} 顺位，DraftMind 在第 "
            f"{selected_pick_no} 顺位选择，说明模型对他比市场更保守。"
        )

    return {
        "market_expected_pick": expected_pick,
        "draftmind_selected_pick": selected_pick_no,
        "market_pick_delta": delta,
        "market_alignment_label": label,
        "market_alignment_notes": [note],
    }


def _market_top30_missing_warnings(
    db: Session,
    *,
    year: int,
    selected_prospect_ids: set[int],
    enabled: bool,
) -> list[str]:
    if not enabled:
        return []

    projections = list(
        db.scalars(
            select(ProspectDraftProjection).where(
                ProspectDraftProjection.year == year,
                ProspectDraftProjection.expected_pick <= 30,
            )
        )
    )
    warnings: list[str] = []
    for projection in sorted(
        projections,
        key=lambda item: (
            item.expected_pick if item.expected_pick is not None else 999,
            item.prospect_id,
        ),
    ):
        if projection.prospect_id in selected_prospect_ids:
            continue
        prospect = db.get(Prospect, projection.prospect_id)
        if prospect is None:
            continue
        if is_officially_unavailable_for_draft(prospect.name, draft_year=year):
            continue
        warnings.append(
            "Market top-30 missing warning: "
            f"{prospect.name} expected #{projection.expected_pick} "
            "was not selected in this simulation."
        )
    return warnings


def _load_team_need_profile(
    db: Session,
    *,
    team_id: int,
    year: int,
) -> TeamNeedProfile | None:
    for horizon in ("next_season", "now"):
        profile = db.scalar(
            select(TeamNeedProfile).where(
                TeamNeedProfile.team_id == team_id,
                TeamNeedProfile.year == year,
                TeamNeedProfile.horizon == horizon,
            )
        )
        if profile is not None:
            return profile
    return None


def _load_prospect_scouting_profiles(
    db: Session,
    *,
    year: int,
    prospects: list[Prospect],
) -> dict[int, ProspectScoutingProfile]:
    prospect_ids = [prospect.id for prospect in prospects if prospect.id is not None]
    if not prospect_ids:
        return {}
    profiles = db.scalars(
        select(ProspectScoutingProfile).where(
            ProspectScoutingProfile.year == year,
            ProspectScoutingProfile.prospect_id.in_(prospect_ids),
        )
    )
    return {profile.prospect_id: profile for profile in profiles}


def _load_prospect_draft_projection_map(
    db: Session,
    *,
    year: int,
    prospects: list[Prospect],
) -> dict[int, ProspectDraftProjection]:
    prospect_ids = [prospect.id for prospect in prospects if prospect.id is not None]
    if not prospect_ids:
        return {}
    projections = list(
        db.scalars(
            select(ProspectDraftProjection).where(
                ProspectDraftProjection.year == year,
                ProspectDraftProjection.prospect_id.in_(prospect_ids),
            )
        )
    )
    selected: dict[int, ProspectDraftProjection] = {}
    for projection in sorted(
        projections,
        key=lambda item: (
            item.prospect_id,
            PROJECTION_SOURCE_PRIORITY.get(item.source, 99),
            -item.confidence,
        ),
    ):
        selected.setdefault(projection.prospect_id, projection)
    return selected


def _load_team_pick_projection_map(
    db: Session,
    *,
    year: int,
    pick_no: int,
    team_id: int,
) -> dict[int, TeamPickProjection]:
    projections = list(
        db.scalars(
            select(TeamPickProjection).where(
                TeamPickProjection.year == year,
                TeamPickProjection.pick_no == pick_no,
                TeamPickProjection.team_id == team_id,
            )
        )
    )
    selected: dict[int, TeamPickProjection] = {}
    for projection in sorted(
        projections,
        key=lambda item: (
            item.prospect_id,
            TEAM_PROJECTION_TYPE_PRIORITY.get(item.projection_type, 99),
            -item.confidence,
        ),
    ):
        selected.setdefault(projection.prospect_id, projection)
    return selected


def _projection_for_ranking(
    ranking: ProspectRanking,
    *,
    prospect_projection_map: dict[int, ProspectDraftProjection] | None,
    team_projection_map: dict[int, TeamPickProjection] | None,
    prediction_shadow_map: dict[int, tuple[PredictionCalibrationResult, int, int]] | None = None,
    prediction_selection_map: dict[int, PredictionSelectionResult] | None = None,
) -> ProjectionDiagnostics | None:
    prospect_id = ranking.prospect.id
    if prospect_id is None:
        return None
    prospect_projection = (
        prospect_projection_map.get(prospect_id) if prospect_projection_map else None
    )
    team_projection = (
        team_projection_map.get(prospect_id) if team_projection_map else None
    )
    shadow = prediction_shadow_map.get(prospect_id) if prediction_shadow_map else None
    selection = (
        prediction_selection_map.get(prospect_id)
        if prediction_selection_map else None
    )
    if (
        prospect_projection is None
        and team_projection is None
        and shadow is None
        and selection is None
    ):
        return None
    return ProjectionDiagnostics(
        prospect_projection=prospect_projection,
        team_projection=team_projection,
        prediction_calibration=shadow[0] if shadow else None,
        prediction_shadow_rank=shadow[1] if shadow else None,
        prediction_shadow_delta=shadow[2] if shadow else None,
        prediction_selection=selection,
    )


def _ranked_reads_with_projection(
    rankings: list[ProspectRanking],
    *,
    prospect_projection_map: dict[int, ProspectDraftProjection] | None,
    team_projection_map: dict[int, TeamPickProjection] | None,
    selected_pick_no: int | None = None,
    include_market_alignment: bool = False,
    prediction_shadow_map: dict[int, tuple[PredictionCalibrationResult, int, int]] | None = None,
    prediction_selection_map: dict[int, PredictionSelectionResult] | None = None,
    candidate_source_map: dict[int, str] | None = None,
) -> list[RankedProspectRead]:
    return [
        _to_ranked_read(
            ranking,
            _projection_for_ranking(
                ranking,
                prospect_projection_map=prospect_projection_map,
                team_projection_map=team_projection_map,
                prediction_shadow_map=prediction_shadow_map,
                prediction_selection_map=prediction_selection_map,
            ),
            (
                candidate_source_map.get(ranking.prospect.id)
                if candidate_source_map and ranking.prospect.id is not None
                else None
            ),
            selected_pick_no=selected_pick_no,
            include_market_alignment=include_market_alignment,
        )
        for ranking in rankings
    ]


def _prediction_shadow_map_for_rankings(
    rankings: list[ProspectRanking],
    *,
    pick_no: int,
    prospect_projection_map: dict[int, ProspectDraftProjection] | None,
    team_projection_map: dict[int, TeamPickProjection] | None,
) -> dict[int, tuple[PredictionCalibrationResult, int, int]]:
    original_positions: dict[int, int] = {}
    scored: list[tuple[int, PredictionCalibrationResult, float]] = []
    for index, ranking in enumerate(rankings, start=1):
        prospect_id = ranking.prospect.id
        if prospect_id is None:
            continue
        original_positions[prospect_id] = index
        result = calculate_prediction_calibration(
            pick_no=pick_no,
            ranking=ranking,
            prospect_projection=(
                prospect_projection_map.get(prospect_id)
                if prospect_projection_map else None
            ),
            team_projection=(
                team_projection_map.get(prospect_id)
                if team_projection_map else None
            ),
        )
        scored.append((prospect_id, result, ranking.final_score))

    shadow_positions: dict[int, int] = {}
    for shadow_rank, (prospect_id, _result, _final_score) in enumerate(
        sorted(
            scored,
            key=lambda item: (item[1].shadow_score, item[2]),
            reverse=True,
        ),
        start=1,
    ):
        shadow_positions[prospect_id] = shadow_rank

    return {
        prospect_id: (
            result,
            shadow_positions[prospect_id],
            original_positions[prospect_id] - shadow_positions[prospect_id],
        )
        for prospect_id, result, _final_score in scored
    }


def _prediction_selection_map_for_rankings(
    rankings: list[ProspectRanking],
    *,
    pick_no: int,
    prospect_projection_map: dict[int, ProspectDraftProjection] | None,
    team_projection_map: dict[int, TeamPickProjection] | None,
    selected_prospect_id: int | None = None,
) -> dict[int, PredictionSelectionResult]:
    if not rankings:
        return {}

    original_positions: dict[int, int] = {}
    scored: list[tuple[int, float, list[str], bool, float]] = []
    original_top_final_score = rankings[0].final_score
    for index, ranking in enumerate(rankings, start=1):
        prospect_id = ranking.prospect.id
        if prospect_id is None:
            continue
        original_positions[prospect_id] = index
        sort_score, eligible, notes = calculate_prediction_sort_score(
            pick_no=pick_no,
            ranking=ranking,
            prospect_projection=(
                prospect_projection_map.get(prospect_id)
                if prospect_projection_map else None
            ),
            team_projection=(
                team_projection_map.get(prospect_id)
                if team_projection_map else None
            ),
            original_top_final_score=original_top_final_score,
        )
        scored.append((prospect_id, sort_score, notes, eligible, ranking.final_score))

    priority_ids: set[int] = set()
    if team_projection_map:
        for prospect_id, sort_score, notes, eligible, final_score in scored:
            if not eligible or prospect_id not in team_projection_map:
                continue
            if has_same_team_projection_priority(
                pick_no=pick_no,
                final_score=final_score,
                original_top_final_score=original_top_final_score,
                prospect_projection=(
                    prospect_projection_map.get(prospect_id)
                    if prospect_projection_map else None
                ),
                team_projection=team_projection_map.get(prospect_id),
            ):
                priority_ids.add(prospect_id)

    if priority_ids:
        ordinary_top_sort_score = max(
            (
                sort_score
                for prospect_id, sort_score, _notes, eligible, _final_score in scored
                if eligible and prospect_id not in priority_ids
            ),
            default=None,
        )
        if ordinary_top_sort_score is not None:
            priority_floor = (
                ordinary_top_sort_score + SAME_TEAM_PROJECTION_PRIORITY_EPSILON
            )
            adjusted: list[tuple[int, float, list[str], bool, float]] = []
            for prospect_id, sort_score, notes, eligible, final_score in scored:
                if prospect_id in priority_ids:
                    notes = [*notes, SAME_TEAM_PROJECTION_PRIORITY_NOTE]
                    if sort_score < priority_floor:
                        sort_score = round(priority_floor, 2)
                adjusted.append(
                    (prospect_id, sort_score, notes, eligible, final_score)
                )
            scored = adjusted

    selection_positions: dict[int, int] = {}
    for selection_rank, (prospect_id, _sort_score, _notes, _eligible, _final_score) in enumerate(
        sorted(
            scored,
            key=lambda item: (item[1], item[4]),
            reverse=True,
        ),
        start=1,
    ):
        selection_positions[prospect_id] = selection_rank

    return {
        prospect_id: PredictionSelectionResult(
            sort_score=sort_score,
            rank=selection_positions[prospect_id],
            delta=original_positions[prospect_id] - selection_positions[prospect_id],
            applied=(
                selected_prospect_id is not None
                and prospect_id == selected_prospect_id
                and original_positions[prospect_id] != 1
            ),
            eligible=eligible,
            notes=notes,
        )
        for prospect_id, sort_score, notes, eligible, _final_score in scored
    }


def _prediction_calibration_lines(
    *,
    original_top: ProspectRanking,
    selected: ProspectRanking,
    selection_map: dict[int, PredictionSelectionResult] | None,
) -> list[str]:
    if not selection_map:
        return []
    lines = ["Prediction calibration enabled."]
    if selected.prospect.id == original_top.prospect.id:
        lines.append("Original top candidate remained selected.")
        return lines

    selected_signal = (
        selection_map.get(selected.prospect.id)
        if selected.prospect.id is not None
        else None
    )
    lines.extend(
        [
            f"Original top candidate was {original_top.prospect.name}.",
            f"Calibrated top candidate is {selected.prospect.name}.",
            "Selected by prediction_sort_score.",
        ]
    )
    if selected_signal and selected_signal.notes:
        lines.append("Reasons: " + " ".join(selected_signal.notes[:4]))
    return lines


def _candidate_board_with_prediction_watchlist(
    *,
    rankings: list[ProspectRanking],
    base_rankings: list[ProspectRanking],
    team_projection_map: dict[int, TeamPickProjection] | None,
    prediction_shadow_map: dict[int, tuple[PredictionCalibrationResult, int, int]] | None,
    shadow_limit: int = 3,
) -> tuple[list[ProspectRanking], dict[int, str]]:
    """Return the normal candidate board plus prediction diagnostics watchlist.

    The board keeps the original ranking order.  This is diagnostics-only:
    it makes strong prediction signals visible without changing selected_player,
    alternatives, final_score, fit_score, or the ranking engine order.
    """
    candidate_source_map: dict[int, str] = {}
    board: list[ProspectRanking] = []
    included_ids: set[int] = set()

    for ranking in base_rankings:
        prospect_id = ranking.prospect.id
        if prospect_id is None or prospect_id in included_ids:
            continue
        included_ids.add(prospect_id)
        candidate_source_map[prospect_id] = "ranking_top"
        board.append(ranking)

    watch_ids: set[int] = set()
    if team_projection_map:
        watch_ids.update(team_projection_map.keys())
    if prediction_shadow_map:
        shadow_top_ids = [
            prospect_id
            for prospect_id, (_result, shadow_rank, _delta) in sorted(
                prediction_shadow_map.items(),
                key=lambda item: item[1][1],
            )
            if shadow_rank <= shadow_limit
        ]
        watch_ids.update(shadow_top_ids)

    if not watch_ids:
        return board, candidate_source_map

    for ranking in rankings:
        prospect_id = ranking.prospect.id
        if prospect_id is None or prospect_id in included_ids:
            continue
        if prospect_id not in watch_ids:
            continue
        included_ids.add(prospect_id)
        candidate_source_map[prospect_id] = (
            "team_projection_match"
            if team_projection_map and prospect_id in team_projection_map
            else "prediction_shadow_top"
        )
        board.append(ranking)

    return board, candidate_source_map


def _scouting_tiebreaker_line(ranking: ProspectRanking) -> str | None:
    if not ranking.scouting_tiebreaker_applied:
        return None
    positives = ranking.scouting_fit_positives or []
    addressed = ", ".join(positives[:4]) if positives else "profile fit"
    return (
        "Scouting fit tie-breaker applied: selected within same talent tier "
        f"because profile fit addressed {addressed}."
    )


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------

def _resolve_locked_prospect(
    db: Session,
    year: int,
    locked: LockedPickRequest,
) -> Prospect:
    """Resolve a single LockedPickRequest to a Prospect in the given year.

    Returns the resolved Prospect, or raises HTTPException(400).

    Rules:
      - Must provide prospect_id or non-empty prospect_name.
      - prospect_id must match an existing prospect with year == year.
      - prospect_name is matched case-insensitive (exact, after strip).
      - prospect_name matching multiple rows is rejected as ambiguous.
    """
    if locked.prospect_id is None and not (
        locked.prospect_name and locked.prospect_name.strip()
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"pick_no={locked.pick_no}: prospect_id or prospect_name is required"
            ),
        )

    if locked.prospect_id is not None:
        prospect = db.scalar(
            select(Prospect).where(
                Prospect.id == locked.prospect_id,
                Prospect.year == year,
            )
        )
        if prospect is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"pick_no={locked.pick_no}: prospect_id={locked.prospect_id} "
                    f"not found in year {year}"
                ),
            )
        return prospect

    # prospect_name: case-insensitive exact match
    name_norm = locked.prospect_name.strip().lower()
    matches = list(
        db.scalars(
            select(Prospect).where(
                Prospect.year == year,
                func.lower(Prospect.name) == name_norm,
            )
        )
    )
    if not matches:
        raise HTTPException(
            status_code=400,
            detail=(
                f"pick_no={locked.pick_no}: prospect_name={locked.prospect_name!r} "
                f"not found in year {year}"
            ),
        )
    if len(matches) > 1:
        raise HTTPException(
            status_code=400,
            detail=(
                f"pick_no={locked.pick_no}: prospect_name={locked.prospect_name!r} "
                f"is ambiguous ({len(matches)} matches)"
            ),
        )
    return matches[0]


def _validate_locked_picks(
    db: Session,
    request: SimulateRequest,
    draft_pick_nos: list[int],
) -> dict[int, Prospect]:
    """Validate the locked_picks block and return a `pick_no -> Prospect` map.

    All errors are HTTP 400 with a structured detail message. The map
    contains only those pick_nos that the user requested to lock; the main
    loop can simply check `pick_no in locked_prospects` to branch.
    """
    if not request.locked_picks:
        return {}

    valid_picks = set(draft_pick_nos)
    seen_pick_nos: set[int] = set()
    seen_prospect_ids: set[int] = set()
    resolved: dict[int, Prospect] = {}

    for locked in request.locked_picks:
        # duplicate pick_no
        if locked.pick_no in seen_pick_nos:
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate locked pick_no={locked.pick_no}",
            )
        seen_pick_nos.add(locked.pick_no)

        # pick_no not in draft order
        if locked.pick_no not in valid_picks:
            raise HTTPException(
                status_code=400,
                detail=f"pick_no={locked.pick_no} is not in the draft order",
            )

        # resolve the prospect (this also enforces year, name, presence)
        prospect = _resolve_locked_prospect(db, request.year, locked)

        # duplicate prospect across two locked picks
        if prospect.id in seen_prospect_ids:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Prospect {prospect.name!r} (id={prospect.id}) is already "
                    f"locked by another pick"
                ),
            )
        seen_prospect_ids.add(prospect.id)
        resolved[locked.pick_no] = prospect

    return resolved


def simulate_draft(db: Session, request: SimulateRequest) -> SimulateResponse:
    # 1. Compute effective_limit so that rounds actually constrains picks
    effective_limit = min(request.limit, 30 if request.rounds == 1 else 60)

    draft_order = list(
        db.scalars(
            select(DraftOrder)
            .where(DraftOrder.year == request.year)
            .options(selectinload(DraftOrder.team))
            .order_by(DraftOrder.pick_no)
            .limit(effective_limit)
        )
    )
    if not draft_order:
        raise HTTPException(status_code=404, detail="Draft order not found")

    # 2. Validate locked_picks BEFORE we walk the board. Any error here is
    #    a 400, not a 404 or 500. The map `locked_prospects[pick_no]` is the
    #    resolved Prospect object the main loop will use.
    draft_pick_nos = [draft_pick.pick_no for draft_pick in draft_order]
    locked_prospects = _validate_locked_picks(
        db=db, request=request, draft_pick_nos=draft_pick_nos,
    )

    prospects = list(
        db.scalars(
            select(Prospect)
            .where(Prospect.year == request.year)
            .order_by(Prospect.upside_score.desc())
        )
    )
    if not prospects:
        raise HTTPException(status_code=404, detail="No prospects found for year")

    # M4-CC: Official withdrawal / availability guard. Remove officially
    # withdrawn / ineligible prospects from the candidate pool BEFORE ranking.
    # This is eligibility-only: it does not change talent_score, final_score,
    # prediction weights, or ranking order. Scoped to draft_year == 2026.
    prospects = filter_available_prospects(
        prospects, draft_year=request.year
    )

    selected_prospect_ids: set[int] = set()
    picks: list[SimulatedPickRead] = []

    # Dynamic team-need state: updated after each pick so that later picks
    # by the same team reflect already-addressed needs.
    team_need_state: dict[int, TeamNeedSnapshot] = {}
    team_need_profile_state: dict[int, TeamNeedProfile | None] = {}
    include_scouting_fit = (
        request.include_scouting_diagnostics
        or request.use_scouting_tiebreaker
    )
    include_projection_context_for_response = (
        request.include_projection_diagnostics
        or request.include_prediction_shadow
        or request.use_prediction_calibration
    )
    # M4-CF: Draft-Day Accuracy Mode needs projection data to drive S1
    # consensus-priority selection. Force-load projections when the mode
    # is enabled, even if the caller did not request diagnostics.
    draft_day_accuracy_mode = bool(request.draft_day_accuracy_mode)

    # Market context (Phase 5B-M1): read cached news once per simulation
    # and pass it to decision_log. This MUST NOT touch selected_player,
    # ranking, or trade_evaluation — see _load_market_signals docstring.
    market_signals: list[NewsSignal] = _load_market_signals(db)

    for draft_pick in draft_order:
        available_prospects = [
            prospect for prospect in prospects if prospect.id not in selected_prospect_ids
        ]
        if not available_prospects:
            break

        # Fetch or reuse team need (snapshot, never ORM)
        if draft_pick.team_id not in team_need_state:
            orm_need = get_or_infer_team_need(
                db=db,
                team_id=draft_pick.team_id,
                year=request.year,
            )
            team_need_state[draft_pick.team_id] = _snapshot_from_orm(orm_need)

        team_need = team_need_state[draft_pick.team_id]
        team_need_profile = None
        scouting_profiles = None
        if include_scouting_fit:
            if draft_pick.team_id not in team_need_profile_state:
                team_need_profile_state[draft_pick.team_id] = _load_team_need_profile(
                    db=db,
                    team_id=draft_pick.team_id,
                    year=request.year,
                )
            team_need_profile = team_need_profile_state[draft_pick.team_id]
            scouting_profiles = _load_prospect_scouting_profiles(
                db=db,
                year=request.year,
                prospects=available_prospects,
            )

        # Rank the live board regardless of whether this is a locked pick.
        # Locked picks still want alternatives + candidate_board populated
        # so the frontend can render a side-by-side comparison.
        rankings = rank_prospects(
            team_need=team_need,
            pick_no=draft_pick.pick_no,
            prospects=available_prospects,
            team_need_profile=team_need_profile,
            scouting_profiles=scouting_profiles,
            include_scouting_fit=include_scouting_fit,
            enable_scouting_tiebreaker=request.use_scouting_tiebreaker,
        )
        prospect_projection_map = None
        team_projection_map = None
        prediction_shadow_map = None
        prediction_selection_map = None
        include_projection_context = (
            request.include_projection_diagnostics
            or request.include_prediction_shadow
            or request.use_prediction_calibration
            or draft_day_accuracy_mode
        )
        if include_projection_context:
            prospect_projection_map = _load_prospect_draft_projection_map(
                db=db,
                year=request.year,
                prospects=available_prospects,
            )
            team_projection_map = _load_team_pick_projection_map(
                db=db,
                year=request.year,
                pick_no=draft_pick.pick_no,
                team_id=draft_pick.team_id,
            )
        if request.include_prediction_shadow:
            prediction_shadow_map = _prediction_shadow_map_for_rankings(
                rankings,
                pick_no=draft_pick.pick_no,
                prospect_projection_map=prospect_projection_map,
                team_projection_map=team_projection_map,
            )
        if request.use_prediction_calibration:
            prediction_selection_map = _prediction_selection_map_for_rankings(
                rankings,
                pick_no=draft_pick.pick_no,
                prospect_projection_map=prospect_projection_map,
                team_projection_map=team_projection_map,
            )

        if draft_pick.pick_no in locked_prospects:
            chosen = locked_prospects[draft_pick.pick_no]

            # Defence in depth: locked prospect must still be in the
            # available board (i.e. not already auto-picked above). The
            # validator already rejects duplicate prospect_ids across two
            # locked picks, so the only way this can fail is when an
            # earlier auto pick already took this prospect.
            chosen_ranking = next(
                (r for r in rankings if r.prospect.id == chosen.id), None,
            )
            if chosen_ranking is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"pick_no={draft_pick.pick_no}: locked prospect "
                        f"{chosen.name!r} is no longer available"
                    ),
                )

            # Surface the chosen prospect at position 0; the rest of the
            # board stays in score order. This keeps alternatives and
            # candidate_board meaningful for the UI.
            override_rankings = [chosen_ranking] + [
                r for r in rankings if r.prospect.id != chosen.id
            ]
            candidate_rankings = override_rankings[:5]
            candidate_source_map = None
            if request.include_prediction_shadow:
                candidate_rankings, candidate_source_map = (
                    _candidate_board_with_prediction_watchlist(
                        rankings=rankings,
                        base_rankings=override_rankings[:5],
                        team_projection_map=team_projection_map,
                        prediction_shadow_map=prediction_shadow_map,
                    )
                )
            alternatives = override_rankings[1:4]
            trade_evaluation = evaluate_trade_market(
                pick_no=draft_pick.pick_no,
                top_score=chosen_ranking.final_score,
                alternative_scores=[r.final_score for r in alternatives],
                evaluate_trades=request.evaluate_trades,
            )
            decision_log = build_decision_log(
                pick_no=draft_pick.pick_no,
                team_abbr=draft_pick.team.abbr,
                selected_name=chosen.name,
                selected_score=chosen_ranking.final_score,
                alternatives=alternatives,
                trade_evaluation=trade_evaluation,
                draft_order_note=draft_pick.notes,
                locked=True,
                market_context_lines=_market_context_lines_for_pick(
                    signals=market_signals,
                    team_abbr=draft_pick.team.abbr,
                    pick_no=draft_pick.pick_no,
                    selected_prospect_name=chosen.name,
                ),
            )
            selected_prospect_ids.add(chosen.id)
            adjust_team_need_after_pick(team_need, chosen)

            picks.append(
                SimulatedPickRead(
                    pick=draft_pick.pick_no,
                    team=draft_pick.team,
                    original_team=draft_pick.original_team,
                    draft_order_note=draft_pick.notes,
                    selected_player=_to_ranked_read(
                        chosen_ranking,
                        _projection_for_ranking(
                            chosen_ranking,
                            prospect_projection_map=prospect_projection_map,
                            team_projection_map=team_projection_map,
                            prediction_shadow_map=prediction_shadow_map,
                            prediction_selection_map=prediction_selection_map,
                        ),
                        selected_pick_no=draft_pick.pick_no,
                        include_market_alignment=include_projection_context,
                    ),
                    alternatives=_ranked_reads_with_projection(
                        alternatives,
                        prospect_projection_map=prospect_projection_map,
                        team_projection_map=team_projection_map,
                        prediction_shadow_map=prediction_shadow_map,
                        prediction_selection_map=prediction_selection_map,
                    ),
                    candidate_board=_ranked_reads_with_projection(
                        candidate_rankings,
                        prospect_projection_map=prospect_projection_map,
                        team_projection_map=team_projection_map,
                        prediction_shadow_map=prediction_shadow_map,
                        prediction_selection_map=prediction_selection_map,
                        candidate_source_map=candidate_source_map,
                    ),
                    trade_evaluation=trade_evaluation,
                    decision_log=decision_log,
                )
            )
        else:
            # ---- AUTO PICK BRANCH (v1) ----
            original_top = rankings[0]
            selection_rankings = rankings
            # M4-CF-B: Draft-Day Accuracy Mode (S1 consensus-priority) MUST
            # take precedence over prediction_calibration. Previously this
            # was an `elif` after `if use_prediction_calibration`, which
            # meant that when the frontend sent both flags (the frontend
            # default for use_prediction_calibration is True), the S1
            # branch was never reached and the mode silently fell back to
            # the default Auto Simulation selection. Now S1 is checked
            # first; when it is enabled we still update the
            # prediction_selection_map afterwards so that diagnostics
            # remain consistent if calibration is also requested.
            if draft_day_accuracy_mode:
                # M4-CF: S1 consensus-priority. Reorder the ranking board
                # by projection expected_pick / range / confidence / team
                # signal, using final_score only as a tie-breaker. This
                # does NOT change ranking_engine, talent_score, or
                # final_score — it only changes the selection order.
                selection_rankings = reorder_rankings_by_consensus_priority(
                    rankings,
                    prospect_projection_map=prospect_projection_map,
                    team_projection_map=team_projection_map,
                    pick_no=draft_pick.pick_no,
                )
                if request.use_prediction_calibration and prediction_selection_map:
                    selected_id = (
                        selection_rankings[0].prospect.id
                        if selection_rankings[0].prospect.id is not None
                        else None
                    )
                    prediction_selection_map = _prediction_selection_map_for_rankings(
                        rankings,
                        pick_no=draft_pick.pick_no,
                        prospect_projection_map=prospect_projection_map,
                        team_projection_map=team_projection_map,
                        selected_prospect_id=selected_id,
                    )
            elif request.use_prediction_calibration and prediction_selection_map:
                selection_rankings = sorted(
                    rankings,
                    key=lambda ranking: (
                        prediction_selection_map.get(ranking.prospect.id).sort_score
                        if ranking.prospect.id is not None
                        and ranking.prospect.id in prediction_selection_map
                        else ranking.final_score,
                        ranking.final_score,
                    ),
                    reverse=True,
                )
                selected_id = (
                    selection_rankings[0].prospect.id
                    if selection_rankings[0].prospect.id is not None
                    else None
                )
                prediction_selection_map = _prediction_selection_map_for_rankings(
                    rankings,
                    pick_no=draft_pick.pick_no,
                    prospect_projection_map=prospect_projection_map,
                    team_projection_map=team_projection_map,
                    selected_prospect_id=selected_id,
                )
            selected = selection_rankings[0]
            alternatives = selection_rankings[1:4]
            candidate_rankings = selection_rankings[:5]
            candidate_source_map = None
            if request.include_prediction_shadow:
                candidate_rankings, candidate_source_map = (
                    _candidate_board_with_prediction_watchlist(
                        rankings=rankings,
                        base_rankings=selection_rankings[:5],
                        team_projection_map=team_projection_map,
                        prediction_shadow_map=prediction_shadow_map,
                    )
                )
            trade_evaluation = evaluate_trade_market(
                pick_no=draft_pick.pick_no,
                top_score=selected.final_score,
                alternative_scores=[ranking.final_score for ranking in alternatives],
                evaluate_trades=request.evaluate_trades,
            )
            decision_log = build_decision_log(
                pick_no=draft_pick.pick_no,
                team_abbr=draft_pick.team.abbr,
                selected_name=selected.prospect.name,
                selected_score=selected.final_score,
                alternatives=alternatives,
                trade_evaluation=trade_evaluation,
                draft_order_note=draft_pick.notes,
                scouting_tiebreaker_line=_scouting_tiebreaker_line(selected),
                prediction_calibration_lines=_prediction_calibration_lines(
                    original_top=original_top,
                    selected=selected,
                    selection_map=prediction_selection_map,
                ),
                market_context_lines=_market_context_lines_for_pick(
                    signals=market_signals,
                    team_abbr=draft_pick.team.abbr,
                    pick_no=draft_pick.pick_no,
                    selected_prospect_name=selected.prospect.name,
                ),
            )
            selected_prospect_ids.add(selected.prospect.id)
            adjust_team_need_after_pick(team_need, selected.prospect)

            picks.append(
                SimulatedPickRead(
                    pick=draft_pick.pick_no,
                    team=draft_pick.team,
                    original_team=draft_pick.original_team,
                    draft_order_note=draft_pick.notes,
                    selected_player=_to_ranked_read(
                        selected,
                        _projection_for_ranking(
                            selected,
                            prospect_projection_map=prospect_projection_map,
                            team_projection_map=team_projection_map,
                            prediction_shadow_map=prediction_shadow_map,
                            prediction_selection_map=prediction_selection_map,
                        ),
                        selected_pick_no=draft_pick.pick_no,
                        include_market_alignment=include_projection_context,
                    ),
                    alternatives=_ranked_reads_with_projection(
                        alternatives,
                        prospect_projection_map=prospect_projection_map,
                        team_projection_map=team_projection_map,
                        prediction_shadow_map=prediction_shadow_map,
                        prediction_selection_map=prediction_selection_map,
                    ),
                    candidate_board=_ranked_reads_with_projection(
                        candidate_rankings,
                        prospect_projection_map=prospect_projection_map,
                        team_projection_map=team_projection_map,
                        prediction_shadow_map=prediction_shadow_map,
                        prediction_selection_map=prediction_selection_map,
                        candidate_source_map=candidate_source_map,
                    ),
                    trade_evaluation=trade_evaluation,
                    decision_log=decision_log,
                )
            )

    return SimulateResponse(
        year=request.year,
        rounds=request.rounds,
        total_picks=len(picks),
        source=draft_order[0].source if draft_order else None,
        picks=picks,
        market_top30_missing_warnings=_market_top30_missing_warnings(
            db,
            year=request.year,
            selected_prospect_ids=selected_prospect_ids,
            # M4-CF: in Draft-Day Accuracy Mode the warnings are still
            # useful for diagnostics, so enable them when the mode is on.
            enabled=include_projection_context_for_response
            or draft_day_accuracy_mode,
        ),
        mode="draft_day_accuracy" if draft_day_accuracy_mode else "auto_simulation",
        draft_day_accuracy_mode=draft_day_accuracy_mode,
    )


# ---------------------------------------------------------------------------
# Trade evaluation (signal only — never executes real trades)
# ---------------------------------------------------------------------------

def evaluate_trade_market(
    pick_no: int,
    top_score: float,
    alternative_scores: list[float],
    evaluate_trades: bool,
) -> TradeEvaluation:
    # MVP only evaluates trade market signals. It does not execute real trades.
    if not evaluate_trades:
        return TradeEvaluation(
            action="keep_pick",
            probability=0.0,
            rationale="Trade evaluation disabled for this simulation.",
        )

    next_best = alternative_scores[0] if alternative_scores else 0.0
    score_gap = top_score - next_best

    if pick_no <= 10 and top_score >= 82:
        return TradeEvaluation(
            action="field_trade_up_calls",
            probability=0.35,
            rationale=(
                "A high-value prospect is available in the lottery, so other teams "
                "may call about moving up. Current GM keeps the pick unless an "
                "overpay arrives."
            ),
        )

    if pick_no <= 20 and score_gap <= 2.0:
        return TradeEvaluation(
            action="shop_down",
            probability=0.42,
            rationale=(
                "The board is flat at this range, so trading down is plausible if "
                "the team can add a future second or move into a similar tier."
            ),
        )

    if pick_no > 35 and top_score < 67:
        return TradeEvaluation(
            action="sell_pick_or_two_way",
            probability=0.28,
            rationale=(
                "Late second-round value is modest; a cash, stash, or two-way path "
                "is realistic."
            ),
        )

    return TradeEvaluation(
        action="keep_pick",
        probability=0.16,
        rationale="The top ranked player separates enough from the board to submit the pick.",
    )


# ---------------------------------------------------------------------------
# Decision log
# ---------------------------------------------------------------------------

def build_decision_log(
    pick_no: int,
    team_abbr: str,
    selected_name: str,
    selected_score: float,
    alternatives,
    trade_evaluation: TradeEvaluation,
    draft_order_note: str | None,
    locked: bool = False,
    scouting_tiebreaker_line: str | None = None,
    prediction_calibration_lines: list[str] | None = None,
    market_context_lines: list[str] | None = None,
) -> list[str]:
    alt_summary = ", ".join(
        f"{ranking.prospect.name} ({ranking.final_score})" for ranking in alternatives
    )
    log = [
        f"Pick {pick_no}: {team_abbr} goes on the clock.",
    ]
    if draft_order_note:
        log.append(f"Draft-order context: {draft_order_note}.")
    log.extend(
        [
            f"Agent filters out already selected prospects and re-ranks the live board.",
            f"Top candidate: {selected_name} with final score {selected_score}.",
            f"Alternatives checked: {alt_summary or 'none available'}.",
            (
                f"Trade check: {trade_evaluation.action} "
                f"({round(trade_evaluation.probability * 100)}%). "
                f"{trade_evaluation.rationale}"
            ),
            f"GM submits {selected_name}; player is removed from later picks.",
        ]
    )
    if scouting_tiebreaker_line:
        log.append(scouting_tiebreaker_line)
    if prediction_calibration_lines:
        log.extend(prediction_calibration_lines)
    if locked:
        log.append("This pick was locked by user override.")
    log.append("Team needs are updated after the pick for later selections.")
    if market_context_lines:
        log.extend(market_context_lines)
    return log


# ---------------------------------------------------------------------------
# Market context (Phase 5B-M1, decision_log only)
# ---------------------------------------------------------------------------
#
# These helpers only feed decision_log. They DO NOT touch:
#   * ranking_engine / final_score
#   * selected_player
#   * evaluate_trade_market / TradeEvaluation
#   * trade action, probability, or rationale
#   * any API response shape
#
# A signal only appears in decision_log for a given pick if it matches
# the pick's team_abbr, pick_no, or the selected prospect's name.
# Mismatched signals (e.g. an LAL rumor on a SAS pick) are filtered out.

MARKET_CONTEXT_LIMIT = 3
MARKET_CONTEXT_LABEL = "Market context:"
_NEWS_KEYWORD_QUERY = "draft trade prospect workout pick"

# Imports kept inside helpers to keep top-of-file imports stable.
def _load_market_signals(db: Session, *, limit: int = 30) -> list[NewsSignal]:
    """Read cached news from the database and convert them to
    ``NewsSignal`` view objects. Pure read-only: no network, no
    ``fetch_recent_articles`` call. Returns ``[]`` on any failure
    (the simulation must never break because of an unrelated news
    table problem).
    """
    try:
        from app.services.news_service import search_articles

        articles = search_articles(
            db,
            keyword=_NEWS_KEYWORD_QUERY,
            limit=limit,
        )
    except Exception:  # noqa: BLE001
        return []
    try:
        return extract_signals(list(articles))
    except Exception:  # noqa: BLE001
        return []


def _signal_matches_pick(
    signal: NewsSignal,
    *,
    team_abbr: str,
    pick_no: int,
    selected_prospect_name: str | None,
) -> bool:
    """Decide whether a cached news signal is relevant to a given pick.

    The decision is **conservative on cross-team leak**: a signal that
    explicitly names a *different* team is *never* allowed to leak into
    the current pick via ``pick_no`` or ``prospect_name`` fallbacks. This
    is the strong guarantee that README §7.4 advertises.

    Matching rules, in order:

    1. **Hard team guard.** If ``signal.team_abbr`` is set (non-empty),
       and it normalises to a team *different* from the current pick's
       team, the signal is dropped (``return False``). It is irrelevant
       regardless of whether ``pick_no`` or ``prospect_name`` happen to
       match.
    2. **Same-team signal** (including empty-team signals that we
       already eliminated above). A same-team signal is shown when:
       - it is team-level (no ``pick_no`` and no ``prospect_name``), or
       - it is pick-specific (``signal.pick_no == pick_no``), or
       - it names the selected prospect (case-insensitive substring).
    3. **Teamless signal** (``signal.team_abbr`` empty/``None``) was
       short-circuited in step 1. We re-check it here: it may match
       by ``pick_no`` or by ``prospect_name`` only. A teamless signal
       that matches neither is dropped.

    Signals with no team, no pick, and no prospect context are *never*
    shown: there is no way to tie them to a specific draft situation.
    """
    signal_team = (signal.team_abbr or "").strip().upper()
    pick_team = (team_abbr or "").strip().upper()

    has_pick_match = (
        signal.pick_no is not None and signal.pick_no == pick_no
    )
    has_prospect_match = bool(
        signal.prospect_name
        and selected_prospect_name
        and signal.prospect_name.lower() in selected_prospect_name.lower()
    )

    # Step 1: hard cross-team guard.  A signal that names a different
    # team must never leak via pick_no / prospect_name fallbacks.
    if signal_team:
        if signal_team != pick_team:
            return False
        # Step 2: same-team signal is relevant if it is team-level,
        # pick-specific, or prospect-specific.
        is_team_level = (
            signal.pick_no is None and not signal.prospect_name
        )
        return is_team_level or has_pick_match or has_prospect_match

    # Step 3: teamless signals may only match by pick_no or prospect.
    return has_pick_match or has_prospect_match


def _format_market_line(signal: NewsSignal) -> str:
    """Render a single signal as a short, non-prescriptive line.

    The wording is intentionally *observational* ("recent cached news
    links ...") rather than prescriptive ("system recommends ...").
    """
    confidence_pct = int(round(signal.confidence * 100))
    parts: list[str] = []
    if signal.team_abbr:
        parts.append(signal.team_abbr)
    intent_label = signal.intent.value.replace("_", " ")
    parts.append(f"has a recent {intent_label} signal")
    if signal.pick_no is not None:
        parts.append(f"around pick #{signal.pick_no}")
    summary = signal.summary
    if summary:
        snippet = summary if len(summary) <= 50 else summary[:47] + "..."
        parts.append(f"({snippet})")
    return (
        f"{MARKET_CONTEXT_LABEL} "
        + " ".join(parts)
        + f" (confidence {confidence_pct}%)."
    )


def _market_context_lines_for_pick(
    *,
    signals: list[NewsSignal],
    team_abbr: str,
    pick_no: int,
    selected_prospect_name: str | None = None,
    limit: int = MARKET_CONTEXT_LIMIT,
) -> list[str]:
    """Filter the global signal list down to the subset that is
    relevant to one pick, then return up to ``limit`` rendered lines.

    The filter is team/pick/prospect based — see
    :func:`_signal_matches_pick`. The input ``signals`` is assumed to
    be sorted by ``-confidence`` (this is what
    :func:`app.services.rumor_extractor.extract_signals` already
    returns), so we keep the top ``limit`` matches in that order.
    """
    if not signals:
        return []
    matches = [
        s for s in signals
        if _signal_matches_pick(
            s,
            team_abbr=team_abbr,
            pick_no=pick_no,
            selected_prospect_name=selected_prospect_name,
        )
    ]
    return [_format_market_line(s) for s in matches[:limit]]
