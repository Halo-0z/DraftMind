from __future__ import annotations

from app.schemas.evidence import (
    ConflictEvidence,
    EvidenceCitation,
    EvidenceSufficiency,
    MarketEvidence,
    PickEvidencePackage,
    RankingEvidence,
    RiskEvidence,
    TeamFitEvidence,
)
from app.schemas.recommendation import RankedProspectRead
from app.schemas.simulation import SimulateResponse, SimulatedPickRead


MARKET_DELTA_CONFLICT_THRESHOLD = 8


def build_pick_evidence(
    simulation: SimulateResponse,
    pick: SimulatedPickRead,
) -> PickEvidencePackage:
    selected = pick.selected_player
    ranking_evidence = _build_ranking_evidence(pick)
    team_fit_evidence = _build_team_fit_evidence(selected)
    market_evidence = _build_market_evidence(selected)
    risk_evidence = _build_risk_evidence(
        selected,
        market_top30_missing_warnings=simulation.market_top30_missing_warnings,
    )
    conflict_evidence = _build_conflict_evidence(
        selected,
        market_evidence=market_evidence,
        diagnostics_warnings=risk_evidence.diagnostics_warnings,
        market_top30_missing_warnings=simulation.market_top30_missing_warnings,
    )

    return PickEvidencePackage(
        pick_number=pick.pick,
        team_abbr=pick.team.abbr,
        selected_player_id=selected.prospect.id,
        selected_player_name=selected.prospect.name,
        ranking_evidence=ranking_evidence,
        team_fit_evidence=team_fit_evidence,
        market_evidence=market_evidence,
        risk_evidence=risk_evidence,
        conflict_evidence=conflict_evidence,
        evidence_sufficiency=_build_evidence_sufficiency(
            ranking_evidence=ranking_evidence,
            market_evidence=market_evidence,
            risk_evidence=risk_evidence,
            conflict_evidence=conflict_evidence,
        ),
        citations=_build_citations(selected),
    )


def _build_ranking_evidence(pick: SimulatedPickRead) -> RankingEvidence:
    selected = pick.selected_player
    selected_index = _selected_index_in_candidate_board(pick)
    score_gap_to_next = None
    score_gap_to_previous = None
    if selected_index is not None:
        score_gap_to_next = _score_gap(
            pick.candidate_board,
            selected_index,
            selected_index + 1,
        )
        score_gap_to_previous = _score_gap(
            pick.candidate_board,
            selected_index - 1,
            selected_index,
        )

    return RankingEvidence(
        final_score=selected.scores.final_score,
        prediction_sort_score=selected.prediction_sort_score,
        rank_in_available_pool=(
            selected_index + 1 if selected_index is not None else None
        ),
        score_gap_to_next=score_gap_to_next,
        score_gap_to_previous=score_gap_to_previous,
        primary_score_drivers=_primary_score_drivers(selected),
    )


def _build_team_fit_evidence(selected: RankedProspectRead) -> TeamFitEvidence:
    basis: list[str] = []
    matched_needs = list(selected.scouting_fit_positives or [])
    unmatched_needs = list(selected.scouting_fit_risks or [])
    if selected.scouting_fit_score is not None:
        basis.append(f"scouting_fit_score={selected.scouting_fit_score}")
    if selected.team_projection_type:
        basis.append(f"team_projection_type={selected.team_projection_type}")
    if selected.team_projection_notes:
        basis.append(selected.team_projection_notes)

    same_team_priority = any(
        "Same-team TeamPickProjection priority applied." in note
        for note in selected.prediction_selection_notes or []
    )

    return TeamFitEvidence(
        matched_needs=matched_needs,
        unmatched_needs=unmatched_needs,
        fit_strength=_fit_strength(selected.scouting_fit_score),
        same_team_projection_priority=same_team_priority,
        explanation_basis=basis,
    )


def _build_market_evidence(selected: RankedProspectRead) -> MarketEvidence:
    expected_pick = selected.market_expected_pick or selected.projection_expected_pick
    range_min = selected.projection_draft_range_min
    range_max = selected.projection_draft_range_max
    has_market_reference = any(
        value is not None
        for value in (
            expected_pick,
            range_min,
            range_max,
            selected.projection_source,
        )
    )
    if selected.market_alignment_label == "无市场参考":
        has_market_reference = False

    market_sources = [
        source
        for source in (
            selected.projection_source,
            selected.team_projection_type,
        )
        if source
    ]

    return MarketEvidence(
        has_market_reference=has_market_reference,
        market_expected_pick=expected_pick,
        market_range_min=range_min,
        market_range_max=range_max,
        market_pick_delta=selected.market_pick_delta,
        market_alignment_label=selected.market_alignment_label,
        market_alignment_notes=list(selected.market_alignment_notes or []),
        market_sources=market_sources,
    )


def _build_risk_evidence(
    selected: RankedProspectRead,
    *,
    market_top30_missing_warnings: list[str],
) -> RiskEvidence:
    diagnostics_warnings = list(selected.diagnostics_warnings or [])
    selected_market_top30_warnings = _warnings_for_selected_player(
        selected,
        market_top30_missing_warnings,
    )
    market_risk_flags = [
        warning
        for warning in diagnostics_warnings
        if "market" in warning.lower()
    ]
    market_risk_flags.extend(selected_market_top30_warnings)
    stats_risk_flags = [
        warning
        for warning in diagnostics_warnings
        if "stats" in warning.lower()
    ]
    data_quality_flags = [
        warning
        for warning in diagnostics_warnings
        if any(token in warning.lower() for token in ("data", "heuristic", "confidence"))
    ]

    return RiskEvidence(
        diagnostics_warnings=diagnostics_warnings,
        market_risk_flags=market_risk_flags,
        stats_risk_flags=stats_risk_flags,
        data_quality_flags=data_quality_flags,
        overall_risk_level=_overall_risk_level(
            diagnostics_warnings=diagnostics_warnings,
            market_top30_missing_warnings=selected_market_top30_warnings,
        ),
    )


def _build_conflict_evidence(
    selected: RankedProspectRead,
    *,
    market_evidence: MarketEvidence,
    diagnostics_warnings: list[str],
    market_top30_missing_warnings: list[str],
) -> list[ConflictEvidence]:
    conflicts: list[ConflictEvidence] = []
    delta = market_evidence.market_pick_delta
    if delta is not None and abs(delta) >= MARKET_DELTA_CONFLICT_THRESHOLD:
        conflicts.append(
            ConflictEvidence(
                type="market_model_delta",
                severity="high",
                description=(
                    "DraftMind selected this player "
                    f"{abs(delta)} picks {'earlier' if delta < 0 else 'later'} "
                    "than the market reference."
                ),
                related_fields=["market_pick_delta", "market_expected_pick"],
            )
        )

    if not market_evidence.has_market_reference:
        conflicts.append(
            ConflictEvidence(
                type="missing_market_reference",
                severity="medium",
                description="No market reference is available for this selected player.",
                related_fields=[
                    "market_expected_pick",
                    "projection_expected_pick",
                    "market_alignment_label",
                ],
            )
        )

    for warning in diagnostics_warnings:
        conflicts.append(
            ConflictEvidence(
                type="diagnostics_warning",
                severity="medium",
                description=warning,
                related_fields=["diagnostics_warnings"],
            )
        )

    selected_name = selected.prospect.name.lower()
    for warning in market_top30_missing_warnings:
        warning_lower = warning.lower()
        if selected_name in warning_lower:
            conflicts.append(
                ConflictEvidence(
                    type="market_top30_missing_warning",
                    severity="medium",
                    description=warning,
                    related_fields=["market_top30_missing_warnings"],
                )
            )

    return conflicts


def _warnings_for_selected_player(
    selected: RankedProspectRead,
    warnings: list[str],
) -> list[str]:
    selected_name = selected.prospect.name.lower()
    return [
        warning
        for warning in warnings
        if selected_name in warning.lower()
    ]


def _build_evidence_sufficiency(
    *,
    ranking_evidence: RankingEvidence,
    market_evidence: MarketEvidence,
    risk_evidence: RiskEvidence,
    conflict_evidence: list[ConflictEvidence],
) -> EvidenceSufficiency:
    missing_sections: list[str] = []
    weak_sections: list[str] = []
    explanation_limits: list[str] = []

    if ranking_evidence.final_score is None:
        missing_sections.append("ranking_evidence")
        explanation_limits.append("Selected player ranking evidence is incomplete.")
    if not market_evidence.has_market_reference:
        missing_sections.append("market_evidence")
        explanation_limits.append("No stable market reference is available.")
    if risk_evidence.diagnostics_warnings:
        weak_sections.append("risk_evidence")
        explanation_limits.append("Diagnostics warnings should be shown as caveats.")

    if "ranking_evidence" in missing_sections:
        level = "insufficient"
    elif (
        not market_evidence.has_market_reference
        or risk_evidence.diagnostics_warnings
        or any(conflict.severity == "high" for conflict in conflict_evidence)
    ):
        level = "limited"
    elif missing_sections or weak_sections:
        level = "moderate"
    else:
        level = "strong"

    return EvidenceSufficiency(
        level=level,
        missing_sections=missing_sections,
        weak_sections=weak_sections,
        explanation_limits=explanation_limits,
    )


def _build_citations(selected: RankedProspectRead) -> list[EvidenceCitation]:
    citations: list[EvidenceCitation] = []
    if selected.projection_source:
        citations.append(
            EvidenceCitation(
                source_type="market_projection",
                source_id=selected.projection_source,
                title="Prospect draft projection",
                confidence=selected.projection_confidence,
            )
        )
    if selected.team_projection_type:
        citations.append(
            EvidenceCitation(
                source_type="team_projection",
                source_id=selected.team_projection_type,
                title="Team pick projection",
                excerpt=selected.team_projection_notes,
                confidence=selected.team_projection_confidence,
            )
        )
    return citations


def _selected_index_in_candidate_board(pick: SimulatedPickRead) -> int | None:
    selected_id = pick.selected_player.prospect.id
    selected_name = pick.selected_player.prospect.name
    for index, candidate in enumerate(pick.candidate_board):
        if candidate.prospect.id == selected_id:
            return index
        if candidate.prospect.name == selected_name:
            return index
    return None


def _score_gap(
    candidate_board: list[RankedProspectRead],
    left_index: int,
    right_index: int,
) -> float | None:
    if left_index < 0 or right_index >= len(candidate_board):
        return None
    left = candidate_board[left_index].scores.final_score
    right = candidate_board[right_index].scores.final_score
    return round(left - right, 3)


def _primary_score_drivers(selected: RankedProspectRead) -> list[str]:
    drivers = list(selected.reasons[:3])
    if selected.prediction_selection_notes:
        drivers.extend(selected.prediction_selection_notes[:2])
    if selected.prediction_sort_score is not None:
        drivers.append("prediction_sort_score available for explanation context")
    return drivers


def _fit_strength(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 8:
        return "strong"
    if score >= 6:
        return "moderate"
    return "limited"


def _overall_risk_level(
    *,
    diagnostics_warnings: list[str],
    market_top30_missing_warnings: list[str],
) -> str:
    if len(diagnostics_warnings) >= 2:
        return "high"
    if diagnostics_warnings or market_top30_missing_warnings:
        return "moderate"
    return "low"
