import copy

from app.schemas.recommendation import RankedProspectRead, ScoreBreakdown
from app.schemas.simulation import SimulateResponse, SimulatedPickRead, TradeEvaluation
from app.schemas.team import TeamRead
from app.schemas.prospect import ProspectRead
from app.services.evidence_service import build_pick_evidence


def _prospect(
    prospect_id: int,
    name: str,
    *,
    position: str = "G",
) -> ProspectRead:
    return ProspectRead(
        id=prospect_id,
        year=2026,
        name=name,
        position=position,
        age=19.0,
        height="6-6",
        weight=200,
        school_or_league="Test",
        ppg=12.0,
        rpg=4.0,
        apg=3.0,
        fg_pct=45.0,
        three_pct=35.0,
        ft_pct=75.0,
        stocks=1.2,
        archetype="connector",
        upside_score=80.0,
        risk_score=20.0,
    )


def _ranked(
    prospect_id: int,
    name: str,
    final_score: float,
    *,
    prediction_sort_score: float | None = None,
    market_expected_pick: int | None = 5,
    market_pick_delta: int | None = 0,
    market_alignment_label: str | None = "一致",
    market_alignment_notes: list[str] | None = None,
    diagnostics_warnings: list[str] | None = None,
    projection_source: str | None = "manual_projection",
) -> RankedProspectRead:
    return RankedProspectRead(
        prospect=_prospect(prospect_id, name),
        scores=ScoreBreakdown(
            talent_score=80.0,
            fit_score=70.0,
            pick_value_score=75.0,
            risk_penalty=5.0,
            final_score=final_score,
        ),
        reasons=["Final score led the available board.", "Strong fit context."],
        risks=["Shot profile needs monitoring."],
        scouting_fit_score=7.0,
        scouting_fit_positives=["spacing"],
        scouting_fit_risks=["rim pressure"],
        projection_expected_pick=market_expected_pick,
        projection_draft_range_min=4 if market_expected_pick else None,
        projection_draft_range_max=8 if market_expected_pick else None,
        projection_confidence=0.8 if market_expected_pick else None,
        projection_source=projection_source if market_expected_pick else None,
        team_projection_type="manual_prediction",
        team_projection_confidence=0.7,
        team_projection_notes="Team-linked projection note.",
        prediction_sort_score=prediction_sort_score,
        market_expected_pick=market_expected_pick,
        draftmind_selected_pick=5,
        market_pick_delta=market_pick_delta,
        market_alignment_label=market_alignment_label,
        market_alignment_notes=(
            market_alignment_notes
            if market_alignment_notes is not None
            else ["市场预计约第 5 顺位。"]
        ),
        diagnostics_warnings=diagnostics_warnings,
    )


def _pick(
    selected: RankedProspectRead,
    *,
    candidate_board: list[RankedProspectRead] | None = None,
) -> SimulatedPickRead:
    board = candidate_board or [
        selected,
        _ranked(2, "Next Player", 78.0),
        _ranked(3, "Third Player", 75.0),
    ]
    return SimulatedPickRead(
        pick=5,
        team=TeamRead(
            id=1,
            name="LA Clippers",
            abbr="LAC",
            nba_team_id=1610612746,
            city="Los Angeles",
            conference="West",
            division="Pacific",
        ),
        selected_player=selected,
        alternatives=board[1:3],
        candidate_board=board,
        trade_evaluation=TradeEvaluation(
            action="stay",
            probability=0.1,
            rationale="Trade evaluation disabled in test.",
        ),
        decision_log=["Selected by structured simulation."],
    )


def _simulation(
    pick: SimulatedPickRead,
    *,
    market_top30_missing_warnings: list[str] | None = None,
) -> SimulateResponse:
    return SimulateResponse(
        year=2026,
        rounds=1,
        total_picks=1,
        source="test",
        picks=[pick],
        market_top30_missing_warnings=market_top30_missing_warnings or [],
    )


def test_build_pick_evidence_from_simulated_pick() -> None:
    selected = _ranked(1, "Keaton Sample", 82.0, prediction_sort_score=83.5)
    pick = _pick(selected)
    package = build_pick_evidence(_simulation(pick), pick)

    assert package.pick_number == 5
    assert package.team_abbr == "LAC"
    assert package.selected_player_id == 1
    assert package.selected_player_name == "Keaton Sample"
    assert package.ranking_evidence is not None
    assert package.ranking_evidence.final_score == 82.0
    assert package.ranking_evidence.prediction_sort_score == 83.5
    assert package.ranking_evidence.rank_in_available_pool == 1
    assert package.ranking_evidence.score_gap_to_next == 4.0
    assert package.market_evidence is not None
    assert package.risk_evidence is not None


def test_build_pick_evidence_locks_decision_boundary() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))
    package = build_pick_evidence(_simulation(pick), pick)

    assert package.decision_locked is True
    assert package.llm_can_modify_decision is False


def test_build_pick_evidence_does_not_mutate_original_pick() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))
    before = copy.deepcopy(pick.model_dump())

    build_pick_evidence(_simulation(pick), pick)

    assert pick.model_dump() == before


def test_market_reference_present_sets_market_evidence_true() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0, market_expected_pick=7))
    package = build_pick_evidence(_simulation(pick), pick)

    assert package.market_evidence is not None
    assert package.market_evidence.has_market_reference is True
    assert package.market_evidence.market_expected_pick == 7


def test_missing_market_reference_generates_limited_evidence_and_conflict() -> None:
    selected = _ranked(
        1,
        "No Market Player",
        82.0,
        market_expected_pick=None,
        market_pick_delta=None,
        market_alignment_label="无市场参考",
        market_alignment_notes=["暂无市场顺位参考。"],
    )
    pick = _pick(selected)
    package = build_pick_evidence(_simulation(pick), pick)

    assert package.market_evidence is not None
    assert package.market_evidence.has_market_reference is False
    assert package.evidence_sufficiency.level == "limited"
    assert any(
        conflict.type == "missing_market_reference"
        for conflict in package.conflict_evidence
    )


def test_diagnostics_warnings_enter_risk_evidence() -> None:
    selected = _ranked(
        1,
        "Risk Player",
        82.0,
        diagnostics_warnings=[
            "Low-confidence imported stats used in ranking context."
        ],
    )
    pick = _pick(selected)
    package = build_pick_evidence(_simulation(pick), pick)

    assert package.risk_evidence is not None
    assert package.risk_evidence.diagnostics_warnings == [
        "Low-confidence imported stats used in ranking context."
    ]
    assert package.risk_evidence.stats_risk_flags
    assert package.risk_evidence.data_quality_flags
    assert any(
        conflict.type == "diagnostics_warning"
        for conflict in package.conflict_evidence
    )


def test_large_market_delta_generates_conflict() -> None:
    selected = _ranked(
        1,
        "Market Delta Player",
        82.0,
        market_expected_pick=10,
        market_pick_delta=-8,
        market_alignment_label="明显高于市场",
    )
    pick = _pick(selected)
    package = build_pick_evidence(_simulation(pick), pick)

    assert any(
        conflict.type == "market_model_delta"
        and conflict.severity == "high"
        for conflict in package.conflict_evidence
    )


def test_candidate_board_only_feeds_score_gap_not_replacement_fields() -> None:
    selected = _ranked(1, "Selected Player", 82.0)
    candidate_board = [
        _ranked(4, "Higher Context Player", 84.0),
        selected,
        _ranked(2, "Lower Context Player", 79.5),
    ]
    pick = _pick(selected, candidate_board=candidate_board)
    package = build_pick_evidence(_simulation(pick), pick)

    assert package.ranking_evidence is not None
    assert package.ranking_evidence.rank_in_available_pool == 2
    assert package.ranking_evidence.score_gap_to_previous == 2.0
    assert package.ranking_evidence.score_gap_to_next == 2.5
    forbidden_fields = {
        "recommended_player",
        "replacement_player",
        "new_selected_player",
        "rerank_score",
    }
    assert forbidden_fields.isdisjoint(package.model_dump())


def test_evidence_service_does_not_call_ranking_engine(monkeypatch) -> None:
    def fail_rank_prospects(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("evidence service must not call ranking_engine")

    monkeypatch.setattr(
        "app.services.ranking_engine.rank_prospects",
        fail_rank_prospects,
    )
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))

    package = build_pick_evidence(_simulation(pick), pick)

    assert package.selected_player_name == "Keaton Sample"


def test_unrelated_market_top30_missing_warning_does_not_attach_to_pick() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))
    package = build_pick_evidence(
        _simulation(
            pick,
            market_top30_missing_warnings=[
                "Market top-30 missing warning: Brayden Burries expected #10 "
                "was not selected in this simulation."
            ],
        ),
        pick,
    )

    assert not any(
        conflict.type == "market_top30_missing_warning"
        for conflict in package.conflict_evidence
    )
    assert package.risk_evidence is not None
    assert not any(
        "Brayden Burries" in warning
        for warning in package.risk_evidence.market_risk_flags
    )
    assert package.evidence_sufficiency.level == "strong"


def test_build_pick_evidence_defaults_retrieved_evidence_to_empty_list() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0, prediction_sort_score=83.5))
    package = build_pick_evidence(_simulation(pick), pick)

    assert package.retrieved_evidence == []


def test_build_pick_evidence_retrieved_evidence_default_not_shared_across_packages() -> None:
    pick_a = _pick(_ranked(1, "Player A", 82.0))
    pick_b = _pick(_ranked(4, "Player B", 80.0))

    package_a = build_pick_evidence(_simulation(pick_a), pick_a)
    package_b = build_pick_evidence(_simulation(pick_b), pick_b)

    assert package_a.retrieved_evidence == []
    assert package_b.retrieved_evidence == []
    assert package_a.retrieved_evidence is not package_b.retrieved_evidence


def test_build_pick_evidence_does_not_call_ranking_engine_for_retrieved_evidence(
    monkeypatch,
) -> None:
    def fail_rank_prospects(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("evidence service must not call ranking_engine")

    monkeypatch.setattr(
        "app.services.ranking_engine.rank_prospects",
        fail_rank_prospects,
    )
    pick = _pick(_ranked(1, "Keaton Sample", 82.0, prediction_sort_score=83.5))

    package = build_pick_evidence(_simulation(pick), pick)

    assert package.retrieved_evidence == []


def test_retrieved_evidence_does_not_change_selected_player_name() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))
    package = build_pick_evidence(_simulation(pick), pick)

    assert package.retrieved_evidence == []
    assert package.selected_player_name == "Keaton Sample"
    assert package.selected_player_id == 1


def test_retrieved_evidence_does_not_change_ranking_final_score() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0, prediction_sort_score=83.5))
    package = build_pick_evidence(_simulation(pick), pick)

    assert package.retrieved_evidence == []
    assert package.ranking_evidence is not None
    assert package.ranking_evidence.final_score == 82.0


def test_retrieved_evidence_does_not_change_prediction_sort_score() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0, prediction_sort_score=83.5))
    package = build_pick_evidence(_simulation(pick), pick)

    assert package.retrieved_evidence == []
    assert package.ranking_evidence is not None
    assert package.ranking_evidence.prediction_sort_score == 83.5


def test_retrieved_evidence_does_not_expose_decision_override_fields() -> None:
    pick = _pick(_ranked(1, "Keaton Sample", 82.0))
    package = build_pick_evidence(_simulation(pick), pick)

    forbidden_fields = {
        "recommended_player",
        "replacement_player",
        "new_selected_player",
        "rerank_score",
        "new_score",
        "selection_override",
    }

    assert forbidden_fields.isdisjoint(package.model_dump())
    assert package.retrieved_evidence == []
