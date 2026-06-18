"""Router-level tests for config-gated ManualNote retrieval (RAG-v1-D1-C).

These tests verify the wiring in ``app.routers.evidence.build_pick_evidence_api``:

* config flag ``evidence_retrieve_manual_notes`` defaults to False
* when False, the router does NOT trigger persisted ManualNote retrieval
  (even if the DB has matching ManualNoteRecord rows)
* when True, the router injects the DB session and persisted manual notes
  appear in ``retrieved_evidence`` / ``citations``
* manual notes never leak into decision / scoring / ranking fields
* the router does NOT call ranking_engine / simulation_service /
  prediction_calibration
* the API request body cannot control the flag (no ``retrieve_knowledge``
  field in PickEvidenceRequest)

The tests use the shared ``client`` fixture from conftest.py (which overrides
``get_db`` to yield the in-memory ``db_session``) and monkeypatch
``app.routers.evidence.get_settings`` to flip the flag — matching the pattern
in ``test_evidence_real_explanation_api.py``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import ManualNoteRecord, Prospect, Team
from app.schemas.evidence import ManualNote
from app.schemas.prospect import ProspectRead
from app.schemas.recommendation import RankedProspectRead, ScoreBreakdown
from app.schemas.simulation import SimulateResponse, SimulatedPickRead, TradeEvaluation
from app.schemas.team import TeamRead


# ---------------------------------------------------------------------------
# Settings helper
# ---------------------------------------------------------------------------


def _settings_with(*, retrieve: bool) -> Settings:
    """Build a Settings instance with the retrieval flag set explicitly."""
    return Settings(evidence_retrieve_manual_notes=retrieve)


@pytest.fixture()
def retrieve_off(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Pin the retrieval flag to False (the default) for the duration of a test."""
    settings = _settings_with(retrieve=False)
    monkeypatch.setattr("app.routers.evidence.get_settings", lambda: settings)
    get_settings.cache_clear()
    yield settings
    get_settings.cache_clear()


@pytest.fixture()
def retrieve_on(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Pin the retrieval flag to True for the duration of a test."""
    settings = _settings_with(retrieve=True)
    monkeypatch.setattr("app.routers.evidence.get_settings", lambda: settings)
    get_settings.cache_clear()
    yield settings
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Payload builders (mirror test_evidence_api.py / test_evidence_service_manual_note_retrieval.py)
# ---------------------------------------------------------------------------


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


def _payload(pick: SimulatedPickRead) -> dict:
    simulation = _simulation(pick)
    return {
        "simulation": simulation.model_dump(),
        "pick": pick.model_dump(),
        "manual_notes": [],
    }


def _build_context(db_session: Session) -> tuple[SimulatedPickRead, int, int]:
    """Build a pick that references seeded DB team + prospect IDs."""
    team = db_session.query(Team).filter(Team.abbr == "SAS").one()
    prospect = db_session.query(Prospect).filter(Prospect.name == "Mikel Brown Jr.").one()
    selected = _ranked(prospect.id, prospect.name, 82.0)
    pick = _pick(selected, team_id=team.id, team_abbr=team.abbr, pick_no=5)
    return pick, team.id, prospect.id


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
) -> ManualNoteRecord:
    record = ManualNoteRecord(
        year=2026,
        entity_type=entity_type,
        entity_id=str(prospect_id) if prospect_id is not None else None,
        prospect_id=prospect_id,
        team_id=team_id,
        pick_no=pick_no,
        title=title,
        body=body,
        summary=summary,
        source="manual",
        author="Analyst Name",
        source_url="https://example.test/note/1",
        source_date="2026-06-16",
        confidence=0.8,
        tags="passing,transition",
        relevance_reason="Explains a selected player's creation upside.",
        evidence_only=evidence_only,
    )
    db_session.add(record)
    db_session.commit()
    return record


# ---------------------------------------------------------------------------
# 1. Config flag default
# ---------------------------------------------------------------------------


def test_config_flag_defaults_to_false() -> None:
    """The new config flag must default to False to preserve legacy behavior."""
    settings = Settings()
    assert settings.evidence_retrieve_manual_notes is False


# ---------------------------------------------------------------------------
# 2. flag=False → no persisted retrieval
# ---------------------------------------------------------------------------


def test_flag_false_does_not_return_persisted_manual_notes(
    client: TestClient,
    db_session: Session,
    retrieve_off: Settings,
) -> None:
    """When the flag is False, persisted ManualNote rows must NOT appear in
    retrieved_evidence, even if the DB has matching rows."""
    pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id, title="Persisted note")

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    manual_in_retrieved = [
        e for e in body["retrieved_evidence"] if e.get("source_type") == "manual_note"
    ]
    assert manual_in_retrieved == []


def test_flag_false_does_not_return_persisted_citation(
    client: TestClient,
    db_session: Session,
    retrieve_off: Settings,
) -> None:
    """When the flag is False, persisted ManualNote citations must NOT appear."""
    pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    manual_in_citations = [
        c for c in body["citations"] if c.get("source_type") == "manual_note"
    ]
    assert manual_in_citations == []


def test_flag_false_behavior_matches_legacy(
    client: TestClient,
    db_session: Session,
    retrieve_off: Settings,
) -> None:
    """When the flag is False, the response shape is identical to pre-RAG-v1."""
    pick, _, _ = _build_context(db_session)

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    assert body["pick_number"] == 5
    assert body["team_abbr"] == "SAS"
    assert body["decision_locked"] is True
    assert body["llm_can_modify_decision"] is False
    assert body["retrieved_evidence"] == []
    assert body["ranking_evidence"] is not None
    assert body["market_evidence"] is not None
    assert body["risk_evidence"] is not None


# ---------------------------------------------------------------------------
# 3. flag=True → persisted retrieval fires
# ---------------------------------------------------------------------------


def test_flag_true_appends_persisted_manual_note_to_retrieved_evidence(
    client: TestClient,
    db_session: Session,
    retrieve_on: Settings,
) -> None:
    """When the flag is True, persisted ManualNote rows must appear in
    retrieved_evidence."""
    pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id, title="Persisted note")

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    manual_in_retrieved = [
        e for e in body["retrieved_evidence"] if e.get("source_type") == "manual_note"
    ]
    assert len(manual_in_retrieved) == 1
    assert manual_in_retrieved[0]["title"] == "Persisted note"


def test_flag_true_appends_persisted_manual_note_citation(
    client: TestClient,
    db_session: Session,
    retrieve_on: Settings,
) -> None:
    """When the flag is True, persisted ManualNote citations must appear."""
    pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id, title="Persisted note")

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    manual_in_citations = [
        c for c in body["citations"] if c.get("source_type") == "manual_note"
    ]
    assert len(manual_in_citations) == 1
    assert manual_in_citations[0]["title"] == "Persisted note"


def test_flag_true_does_not_duplicate_when_no_persisted_notes(
    client: TestClient,
    db_session: Session,
    retrieve_on: Settings,
) -> None:
    """When the flag is True but no persisted notes exist, retrieved_evidence
    stays empty (no spurious entries, no errors)."""
    pick, _, _ = _build_context(db_session)

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    assert body["retrieved_evidence"] == []


# ---------------------------------------------------------------------------
# 4. manual_note only enters retrieved_evidence / citations
# ---------------------------------------------------------------------------


def test_manual_note_only_enters_retrieved_evidence_and_citations(
    client: TestClient,
    db_session: Session,
    retrieve_on: Settings,
) -> None:
    """Persisted manual notes must only surface in retrieved_evidence and
    citations — never in ranking / market / risk / conflict evidence."""
    pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id, title="Persisted note")

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()

    # retrieved_evidence + citations should contain the manual note
    assert any(
        e.get("source_type") == "manual_note"
        for e in body["retrieved_evidence"]
    )
    assert any(
        c.get("source_type") == "manual_note"
        for c in body["citations"]
    )

    # ranking / market / risk / conflict evidence must NOT carry a manual_note
    # marker — these objects don't have source_type, but they must be unchanged
    # from the legacy shape.  We assert they are present and non-null.
    assert body["ranking_evidence"] is not None
    assert body["market_evidence"] is not None
    assert body["risk_evidence"] is not None
    assert body["conflict_evidence"] is not None


# ---------------------------------------------------------------------------
# 5. manual_note does NOT change decision / scoring / ranking fields
# ---------------------------------------------------------------------------


def test_manual_note_does_not_change_selected_player(
    client: TestClient,
    db_session: Session,
    retrieve_on: Settings,
) -> None:
    """Persisted manual notes must not change selected_player fields."""
    pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    assert body["selected_player_id"] == pick.selected_player.prospect.id
    assert body["selected_player_name"] == pick.selected_player.prospect.name


def test_manual_note_does_not_change_final_score(
    client: TestClient,
    db_session: Session,
    retrieve_on: Settings,
) -> None:
    """Persisted manual notes must not change ranking_evidence.final_score."""
    pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    assert (
        body["ranking_evidence"]["final_score"]
        == pick.selected_player.scores.final_score
    )


def test_manual_note_does_not_change_prediction_sort_score(
    client: TestClient,
    db_session: Session,
    retrieve_on: Settings,
) -> None:
    """Persisted manual notes must not change ranking_evidence.prediction_sort_score."""
    pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    assert (
        body["ranking_evidence"]["prediction_sort_score"]
        == pick.selected_player.prediction_sort_score
    )


def test_manual_note_does_not_change_ranking_market_risk_evidence(
    client: TestClient,
    db_session: Session,
    retrieve_on: Settings,
) -> None:
    """Persisted manual notes must not change ranking / market / risk evidence
    payloads (beyond their existence).  Compare against a flag=False baseline."""
    pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    # Baseline: flag=False (no persisted retrieval)
    retrieve_off_settings = _settings_with(retrieve=False)
    import app.routers.evidence as evidence_router

    original_get_settings = evidence_router.get_settings
    evidence_router.get_settings = lambda: retrieve_off_settings
    get_settings.cache_clear()
    try:
        baseline_response = client.post("/api/evidence/pick", json=_payload(pick))
    finally:
        evidence_router.get_settings = original_get_settings
        get_settings.cache_clear()

    # flag=True (persisted retrieval active)
    retrieve_on_settings = _settings_with(retrieve=True)
    evidence_router.get_settings = lambda: retrieve_on_settings
    get_settings.cache_clear()
    try:
        enriched_response = client.post("/api/evidence/pick", json=_payload(pick))
    finally:
        evidence_router.get_settings = original_get_settings
        get_settings.cache_clear()

    assert baseline_response.status_code == 200
    assert enriched_response.status_code == 200
    baseline = baseline_response.json()
    enriched = enriched_response.json()

    # Decision / scoring / ranking fields must be identical
    assert enriched["selected_player_id"] == baseline["selected_player_id"]
    assert enriched["selected_player_name"] == baseline["selected_player_name"]
    assert enriched["ranking_evidence"] == baseline["ranking_evidence"]
    assert enriched["market_evidence"] == baseline["market_evidence"]
    assert enriched["risk_evidence"] == baseline["risk_evidence"]
    assert enriched["conflict_evidence"] == baseline["conflict_evidence"]
    assert enriched["evidence_sufficiency"] == baseline["evidence_sufficiency"]

    # retrieved_evidence / citations may differ (enriched has manual_note)
    assert len(enriched["retrieved_evidence"]) >= len(baseline["retrieved_evidence"])
    assert len(enriched["citations"]) >= len(baseline["citations"])


# ---------------------------------------------------------------------------
# 6. API request body cannot control the flag
# ---------------------------------------------------------------------------


def test_request_body_retrieve_knowledge_field_is_ignored(
    client: TestClient,
    db_session: Session,
    retrieve_off: Settings,
) -> None:
    """PickEvidenceRequest has no retrieve_knowledge field.  Sending one in the
    body must NOT enable retrieval (Pydantic extra='ignore' or forbid)."""
    pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    payload = _payload(pick)
    payload["retrieve_knowledge"] = True  # must be ignored

    response = client.post("/api/evidence/pick", json=payload)

    assert response.status_code == 200
    body = response.json()
    manual_in_retrieved = [
        e for e in body["retrieved_evidence"] if e.get("source_type") == "manual_note"
    ]
    assert manual_in_retrieved == []


def test_request_body_include_knowledge_field_is_ignored(
    client: TestClient,
    db_session: Session,
    retrieve_off: Settings,
) -> None:
    """Any non-schema field named like a retrieval switch must be ignored."""
    pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    payload = _payload(pick)
    payload["include_knowledge"] = True
    payload["enable_retrieval"] = True

    response = client.post("/api/evidence/pick", json=payload)

    assert response.status_code == 200
    body = response.json()
    manual_in_retrieved = [
        e for e in body["retrieved_evidence"] if e.get("source_type") == "manual_note"
    ]
    assert manual_in_retrieved == []


# ---------------------------------------------------------------------------
# 7. Schema boundary: PickEvidenceRequest has no retrieve_knowledge field
# ---------------------------------------------------------------------------


def test_pick_evidence_request_schema_has_no_retrieve_knowledge_field() -> None:
    """PickEvidenceRequest must not expose a retrieve_knowledge field."""
    from app.schemas.evidence import PickEvidenceRequest

    fields = set(PickEvidenceRequest.model_fields.keys())
    assert "retrieve_knowledge" not in fields
    assert "include_knowledge" not in fields
    assert "enable_retrieval" not in fields
    assert "db" not in fields


# ---------------------------------------------------------------------------
# 8. Router does NOT call ranking_engine / simulation_service / prediction_calibration
# ---------------------------------------------------------------------------


def test_router_does_not_call_ranking_engine(
    client: TestClient,
    db_session: Session,
    retrieve_on: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The evidence router must not invoke the ranking_engine."""
    import app.routers.evidence as evidence_router

    sentinel_called = False

    def _fail(*args, **kwargs):  # noqa: ANN202
        nonlocal sentinel_called
        sentinel_called = True
        raise AssertionError("ranking_engine must not be called from evidence router")

    # Patch common ranking_engine entry points if they exist.
    for module_path, attr in [
        ("app.services.ranking_engine", "rank_prospects"),
        ("app.services.ranking_engine", "RankingEngine"),
    ]:
        try:
            monkeypatch.setattr(module_path, attr, _fail, raising=True)
        except (AttributeError, ModuleNotFoundError):
            continue

    pick, _, _ = _build_context(db_session)
    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    assert sentinel_called is False


def test_router_does_not_call_simulation_service(
    client: TestClient,
    db_session: Session,
    retrieve_on: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The evidence router must not invoke simulation_service."""
    import app.services.simulation_service as sim_svc

    def _fail(*args, **kwargs):  # noqa: ANN202
        raise AssertionError(
            "simulation_service must not be called from evidence router"
        )

    for attr in dir(sim_svc):
        if attr.startswith("_"):
            continue
        if callable(getattr(sim_svc, attr, None)) and not isinstance(
            getattr(sim_svc, attr), type
        ):
            try:
                monkeypatch.setattr(sim_svc, attr, _fail, raising=True)
            except (AttributeError, TypeError):
                continue

    pick, _, _ = _build_context(db_session)
    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200


def test_router_does_not_call_prediction_calibration(
    client: TestClient,
    db_session: Session,
    retrieve_on: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The evidence router must not invoke prediction_calibration."""
    try:
        import app.services.prediction_calibration as pred_calib
    except ModuleNotFoundError:
        return  # module doesn't exist — boundary trivially satisfied

    def _fail(*args, **kwargs):  # noqa: ANN202
        raise AssertionError(
            "prediction_calibration must not be called from evidence router"
        )

    for attr in dir(pred_calib):
        if attr.startswith("_"):
            continue
        if callable(getattr(pred_calib, attr, None)) and not isinstance(
            getattr(pred_calib, attr), type
        ):
            try:
                monkeypatch.setattr(pred_calib, attr, _fail, raising=True)
            except (AttributeError, TypeError):
                continue

    pick, _, _ = _build_context(db_session)
    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 9. DB failure isolation: flag=True but DB error → evidence still builds
# ---------------------------------------------------------------------------


def test_flag_true_db_error_still_returns_evidence(
    client: TestClient,
    db_session: Session,
    retrieve_on: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When retrieval raises, the router must still return a valid evidence
    package (silent fallback in _append_persisted_manual_notes)."""
    from app.services import evidence_service

    def _boom(*args, **kwargs):  # noqa: ANN202
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(
        evidence_service, "retrieve_manual_note_documents", _boom
    )

    pick, _, prospect_id = _build_context(db_session)
    _make_manual_note_record(db_session, prospect_id=prospect_id)

    response = client.post("/api/evidence/pick", json=_payload(pick))

    assert response.status_code == 200
    body = response.json()
    # Retrieval failed silently — no manual_note in retrieved_evidence
    manual_in_retrieved = [
        e for e in body["retrieved_evidence"] if e.get("source_type") == "manual_note"
    ]
    assert manual_in_retrieved == []
    # Decision fields still intact
    assert body["selected_player_id"] == pick.selected_player.prospect.id
    assert body["decision_locked"] is True
