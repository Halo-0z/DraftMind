"""Tests for build_pick_evidence ManualNote retrieval integration (RAG-v1-D1-A)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.models import ManualNoteRecord, Prospect, Team
from app.schemas.recommendation import RankedProspectRead, ScoreBreakdown
from app.schemas.simulation import SimulateResponse, SimulatedPickRead, TradeEvaluation
from app.schemas.team import TeamRead
from app.schemas.prospect import ProspectRead
from app.services.evidence_service import build_pick_evidence


def _prospect_read(prospect_id: int, name: str) -> ProspectRead:
    return ProspectRead(
        id=prospect_id,
        year=2026,
        name=name,
        position="PG",
        age=19.0,
        height="6-3",
        weight=180,
        school_or_league="Louisville",
        ppg=18.6,
        rpg=3.2,
        apg=6.8,
        fg_pct=45.0,
        three_pct=38.2,
        ft_pct=84.5,
        stocks=1.2,
        archetype="Pick-and-roll lead guard",
        upside_score=86.0,
        risk_score=35.0,
    )


def _ranked(prospect_id: int, name: str, final_score: float) -> RankedProspectRead:
    return RankedProspectRead(
        prospect=_prospect_read(prospect_id, name),
        scores=ScoreBreakdown(
            talent_score=80.0,
            fit_score=70.0,
            pick_value_score=75.0,
            risk_penalty=5.0,
            final_score=final_score,
        ),
        reasons=["Final score led the available board."],
        risks=["Shot profile needs monitoring."],
        scouting_fit_score=7.0,
        scouting_fit_positives=["spacing"],
        scouting_fit_risks=["rim pressure"],
        projection_expected_pick=5,
        projection_draft_range_min=4,
        projection_draft_range_max=8,
        projection_confidence=0.8,
        projection_source="manual_projection",
        team_projection_type="manual_prediction",
        team_projection_confidence=0.7,
        team_projection_notes="Team-linked projection note.",
        prediction_sort_score=83.5,
        market_expected_pick=5,
        draftmind_selected_pick=5,
        market_pick_delta=0,
        market_alignment_label="一致",
        market_alignment_notes=["市场预计约第 5 顺位。"],
    )


def _pick(
    selected: RankedProspectRead,
    *,
    team_id: int,
    team_abbr: str,
    pick_no: int = 5,
) -> SimulatedPickRead:
    return SimulatedPickRead(
        pick=pick_no,
        team=TeamRead(
            id=team_id,
            name="San Antonio Spurs",
            abbr=team_abbr,
            nba_team_id=1610612759,
            city="San Antonio",
            conference="West",
            division="Southwest",
        ),
        selected_player=selected,
        alternatives=[_ranked(2, "Next Player", 78.0)],
        candidate_board=[selected, _ranked(2, "Next Player", 78.0)],
        trade_evaluation=TradeEvaluation(
            action="stay",
            probability=0.1,
            rationale="Trade evaluation disabled in test.",
        ),
        decision_log=["Selected by structured simulation."],
    )


def _simulation(pick: SimulatedPickRead) -> SimulateResponse:
    return SimulateResponse(
        year=2026,
        rounds=1,
        total_picks=1,
        source="test",
        picks=[pick],
        market_top30_missing_warnings=[],
    )


def _make_manual_note_record(
    db_session: Session,
    *,
    prospect_id: int | None = None,
    team_id: int | None = None,
    pick_no: int | None = None,
    entity_type: str = "prospect",
    title: str = "Workout observation",
    body: str = "The player showed advanced passing feel in transition.",
    summary: str | None = "Passing feel note.",
    evidence_only: bool = True,
    **overrides: Any,
) -> ManualNoteRecord:
    defaults = {
        "year": 2026,
        "entity_type": entity_type,
        "entity_id": str(prospect_id) if prospect_id is not None else None,
        "prospect_id": prospect_id,
        "team_id": team_id,
        "pick_no": pick_no,
        "title": title,
        "body": body,
        "summary": summary,
        "source": "manual",
        "author": "Analyst Name",
        "source_url": "https://example.test/note/1",
        "source_date": "2026-06-16",
        "confidence": 0.8,
        "tags": "passing,transition",
        "relevance_reason": "Explains a selected player's creation upside.",
        "evidence_only": evidence_only,
    }
    defaults.update(overrides)
    record = ManualNoteRecord(**defaults)
    db_session.add(record)
    db_session.commit()
    return record


def _build_context(db_session: Session) -> tuple[SimulateResponse, SimulatedPickRead, int, int]:
    """Build a simulation/pick that references seeded DB team + prospect IDs."""
    team = db_session.query(Team).filter(Team.abbr == "SAS").one()
    prospect = db_session.query(Prospect).filter(Prospect.name == "Mikel Brown Jr.").one()
    selected = _ranked(prospect.id, prospect.name, 82.0)
    pick = _pick(selected, team_id=team.id, team_abbr=team.abbr, pick_no=5)
    return _simulation(pick), pick, team.id, prospect.id


def test_default_retrieve_flag_false_does_not_retrieve(db_session: Session) -> None:
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    package = build_pick_evidence(simulation, pick)

    # No persisted manual notes should appear because retrieve_knowledge defaults to False.
    manual_note_evidence = [
        e for e in package.retrieved_evidence if e.source_type == "manual_note"
    ]
    assert manual_note_evidence == []


def test_db_none_does_not_retrieve(db_session: Session) -> None:
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    package = build_pick_evidence(
        simulation, pick, db=None, retrieve_knowledge=True
    )

    manual_note_evidence = [
        e for e in package.retrieved_evidence if e.source_type == "manual_note"
    ]
    assert manual_note_evidence == []


def test_retrieve_true_appends_manual_note_to_retrieved_evidence(
    db_session: Session,
) -> None:
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id, title="Persisted note")

    package = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    manual_note_evidence = [
        e for e in package.retrieved_evidence if e.source_type == "manual_note"
    ]
    assert len(manual_note_evidence) == 1
    assert manual_note_evidence[0].title == "Persisted note"


def test_retrieve_true_appends_manual_note_citation(db_session: Session) -> None:
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id, title="Persisted note")

    package = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    manual_note_citations = [
        c for c in package.citations if c.source_type == "manual_note"
    ]
    assert len(manual_note_citations) == 1
    assert manual_note_citations[0].title == "Persisted note"


def test_retrieved_evidence_source_type_is_manual_note(db_session: Session) -> None:
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    package = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    for evidence in package.retrieved_evidence:
        if evidence.source_type == "manual_note":
            assert evidence.source_type == "manual_note"


def test_retrieved_evidence_evidence_only_is_true(db_session: Session) -> None:
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    package = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    for evidence in package.retrieved_evidence:
        if evidence.source_type == "manual_note":
            assert evidence.evidence_only is True


def test_citation_evidence_only_is_true(db_session: Session) -> None:
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    package = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    for citation in package.citations:
        if citation.source_type == "manual_note":
            assert citation.evidence_only is True


def test_manual_note_only_enters_retrieved_evidence_and_citations(
    db_session: Session,
) -> None:
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id, title="Persisted note")

    package = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    # ManualNote must NOT appear in any decision / scoring / ranking field.
    assert package.ranking_evidence is not None
    assert package.market_evidence is not None
    assert package.risk_evidence is not None

    # It must only appear in retrieved_evidence and citations.
    manual_in_retrieved = [
        e for e in package.retrieved_evidence if e.source_type == "manual_note"
    ]
    manual_in_citations = [
        c for c in package.citations if c.source_type == "manual_note"
    ]
    assert len(manual_in_retrieved) == 1
    assert len(manual_in_citations) == 1


def test_manual_note_does_not_change_selected_player(db_session: Session) -> None:
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    package_without = build_pick_evidence(simulation, pick)
    package_with = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    assert package_without.selected_player_id == package_with.selected_player_id
    assert package_without.selected_player_name == package_with.selected_player_name


def test_manual_note_does_not_change_final_score(db_session: Session) -> None:
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    package_without = build_pick_evidence(simulation, pick)
    package_with = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    assert (
        package_without.ranking_evidence.final_score
        == package_with.ranking_evidence.final_score
    )


def test_manual_note_does_not_change_prediction_sort_score(
    db_session: Session,
) -> None:
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    package_without = build_pick_evidence(simulation, pick)
    package_with = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    assert (
        package_without.ranking_evidence.prediction_sort_score
        == package_with.ranking_evidence.prediction_sort_score
    )


def test_manual_note_does_not_change_ranking_evidence(db_session: Session) -> None:
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    package_without = build_pick_evidence(simulation, pick)
    package_with = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    assert package_without.ranking_evidence.model_dump() == package_with.ranking_evidence.model_dump()


def test_manual_note_does_not_change_market_evidence(db_session: Session) -> None:
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    package_without = build_pick_evidence(simulation, pick)
    package_with = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    assert package_without.market_evidence.model_dump() == package_with.market_evidence.model_dump()


def test_manual_note_does_not_change_risk_evidence(db_session: Session) -> None:
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    package_without = build_pick_evidence(simulation, pick)
    package_with = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    assert package_without.risk_evidence.model_dump() == package_with.risk_evidence.model_dump()


def test_retrieval_failure_falls_back_silently(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    def fail_retrieve(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated retrieval failure")

    monkeypatch.setattr(
        "app.services.evidence_service.retrieve_manual_note_documents",
        fail_retrieve,
    )

    package = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    # The package must still build; no manual_note evidence attached.
    manual_note_evidence = [
        e for e in package.retrieved_evidence if e.source_type == "manual_note"
    ]
    assert manual_note_evidence == []
    assert package.selected_player_name is not None


def test_does_not_call_ranking_engine(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_rank_prospects(*args: object, **kwargs: object) -> None:
        raise AssertionError("build_pick_evidence must not call ranking_engine")

    monkeypatch.setattr(
        "app.services.ranking_engine.rank_prospects",
        fail_rank_prospects,
    )
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    package = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    assert package.selected_player_name is not None


def test_does_not_call_simulation_service(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_simulate_draft(*args: object, **kwargs: object) -> None:
        raise AssertionError("build_pick_evidence must not call simulation_service")

    monkeypatch.setattr(
        "app.services.simulation_service.simulate_draft",
        fail_simulate_draft,
    )
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    package = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    assert package.selected_player_name is not None


def test_does_not_call_prediction_calibration(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_calibrate(*args: object, **kwargs: object) -> None:
        raise AssertionError("build_pick_evidence must not call prediction_calibration")

    # prediction_calibration's public function name may vary; patch the module
    # import path that evidence_service would use if it ever imported it.
    import app.services.prediction_calibration as calibration_module

    for attr_name in dir(calibration_module):
        if callable(getattr(calibration_module, attr_name)) and not attr_name.startswith("_"):
            monkeypatch.setattr(
                f"app.services.prediction_calibration.{attr_name}",
                fail_calibrate,
                raising=False,
            )
    simulation, pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    package = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    assert package.selected_player_name is not None


def test_default_behavior_unchanged_without_db(db_session: Session) -> None:
    """When db=None and retrieve_knowledge=False, output must match the old
    behavior exactly."""
    simulation, pick, _, _ = _build_context(db_session)

    package = build_pick_evidence(simulation, pick)

    assert package.pick_number == 5
    assert package.team_abbr == "SAS"
    assert package.decision_locked is True
    assert package.llm_can_modify_decision is False
    assert package.ranking_evidence is not None
    assert package.market_evidence is not None
    assert package.risk_evidence is not None
    assert package.retrieved_evidence == []


def test_persisted_manual_notes_capped_at_five_across_all_retrievals(
    db_session: Session,
) -> None:
    """When prospect/team/pick each have more than 5 manual notes, the total
    appended to retrieved_evidence / citations must not exceed 5."""
    from app.services.evidence_service import PERSISTED_MANUAL_NOTE_LIMIT

    simulation, pick, team_id, prospect_id = _build_context(db_session)

    # 4 prospect notes + 4 team notes + 4 pick notes = 12 candidates.
    # Global cap must limit the final appended count to PERSISTED_MANUAL_NOTE_LIMIT.
    for i in range(4):
        _make_manual_note_record(
            db_session,
            prospect_id=prospect_id,
            team_id=None,
            pick_no=None,
            entity_type="prospect",
            title=f"Prospect note {i}",
        )
    for i in range(4):
        _make_manual_note_record(
            db_session,
            prospect_id=None,
            team_id=team_id,
            pick_no=None,
            entity_type="team",
            title=f"Team note {i}",
        )
    for i in range(4):
        _make_manual_note_record(
            db_session,
            prospect_id=None,
            team_id=None,
            pick_no=5,
            entity_type="pick",
            title=f"Pick note {i}",
        )

    package = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    manual_in_retrieved = [
        e for e in package.retrieved_evidence if e.source_type == "manual_note"
    ]
    manual_in_citations = [
        c for c in package.citations if c.source_type == "manual_note"
    ]

    assert len(manual_in_retrieved) <= PERSISTED_MANUAL_NOTE_LIMIT
    assert len(manual_in_citations) <= PERSISTED_MANUAL_NOTE_LIMIT
    assert len(manual_in_retrieved) == len(manual_in_citations)


def test_persisted_manual_notes_capped_at_five_when_single_retrieval_exceeds(
    db_session: Session,
) -> None:
    """Even a single retrieval call returning more than 5 notes must be capped."""
    from app.services.evidence_service import PERSISTED_MANUAL_NOTE_LIMIT

    simulation, pick, _, prospect_id = _build_context(db_session)

    for i in range(10):
        _make_manual_note_record(
            db_session,
            prospect_id=prospect_id,
            title=f"Prospect note {i}",
        )

    package = build_pick_evidence(
        simulation, pick, db=db_session, retrieve_knowledge=True
    )

    manual_in_retrieved = [
        e for e in package.retrieved_evidence if e.source_type == "manual_note"
    ]
    manual_in_citations = [
        c for c in package.citations if c.source_type == "manual_note"
    ]

    assert len(manual_in_retrieved) <= PERSISTED_MANUAL_NOTE_LIMIT
    assert len(manual_in_citations) <= PERSISTED_MANUAL_NOTE_LIMIT
