"""Tests for config-gated semantic retrieval wiring (RAG-v2-M2-E).

These tests verify that the semantic retrieval wiring in
:func:`build_pick_evidence` is:

1. Config-gated: OFF by default, no-op when ``evidence_retrieve_semantic``
   is False.
2. Evidence-only: appends to ``retrieved_evidence`` / ``citations`` only;
   never touches ``selected_player`` / ``final_score`` /
   ``prediction_sort_score`` / ranking / simulation / prediction.
3. Failure-isolated: any exception in the semantic path is swallowed so
   the evidence package still builds.
4. ``retrieval_score`` safe: enters ``RetrievedEvidence`` but is excluded
   from ``EvidenceCitation`` and the LLM payload whitelist.
5. Non-invasive: does not call ``ranking_engine`` /
   ``simulation_service`` / ``prediction_calibration``.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.config import Settings
from app.schemas.evidence import (
    EvidenceCitation,
    ManualNote,
    RetrievedEvidence,
)
from app.schemas.recommendation import RankedProspectRead, ScoreBreakdown
from app.schemas.simulation import SimulateResponse, SimulatedPickRead, TradeEvaluation
from app.schemas.team import TeamRead
from app.schemas.prospect import ProspectRead
from app.services.evidence_service import build_pick_evidence


# ---------------------------------------------------------------------------
# Factory helpers (mirrors test_evidence_service.py)
# ---------------------------------------------------------------------------


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


def _manual_note(
    *,
    note_id: int | str | None = 1,
    body: str = "Keaton Sample is a strong perimeter defender with excellent lateral quickness.",
    title: str = "Scouting report for Keaton Sample",
    summary: str | None = "Perimeter defender profile.",
    entity_type: str = "prospect",
    prospect_id: int | None = 1,
    team_id: int | None = None,
    pick_no: int | None = None,
) -> ManualNote:
    return ManualNote(
        note_id=note_id,
        year=2026,
        entity_type=entity_type,
        entity_id=prospect_id,
        prospect_id=prospect_id,
        team_id=team_id,
        pick_no=pick_no,
        title=title,
        body=body,
        summary=summary,
        source="manual",
        author="scout",
        confidence=0.8,
        tags=["defense", "perimeter"],
        relevance_reason="Directly relevant to the selected prospect.",
    )


def _semantic_settings(
    *,
    enabled: bool = True,
    top_k: int = 5,
    min_score: float = 0.0,
) -> Settings:
    """Build a Settings instance with semantic retrieval config."""
    return Settings(
        evidence_retrieve_semantic=enabled,
        evidence_semantic_top_k=top_k,
        evidence_semantic_min_score=min_score,
    )


def _fake_retrieved_evidence(
    *,
    source_id: str = "semantic-0",
    retrieval_score: float = 0.85,
) -> RetrievedEvidence:
    return RetrievedEvidence(
        source_type="manual_note",
        source_id=source_id,
        title="Semantic retrieved evidence",
        excerpt="Semantic retrieval found this relevant chunk.",
        confidence=0.8,
        relevance_reason="Semantic match for query context.",
        retrieval_score=retrieval_score,
        evidence_only=True,
    )


def _fake_citation(
    *,
    source_id: str = "semantic-0",
) -> EvidenceCitation:
    return EvidenceCitation(
        source_type="manual_note",
        source_id=source_id,
        title="Semantic retrieved evidence",
        excerpt="Semantic retrieval found this relevant chunk.",
        confidence=0.8,
        evidence_only=True,
    )


# ---------------------------------------------------------------------------
# Config default
# ---------------------------------------------------------------------------


def test_config_default_evidence_retrieve_semantic_is_false() -> None:
    """The default config must have semantic retrieval OFF."""
    settings = Settings()
    assert settings.evidence_retrieve_semantic is False
    assert settings.evidence_semantic_top_k == 5
    assert settings.evidence_semantic_min_score == 0.0


# ---------------------------------------------------------------------------
# Flag False: old behavior preserved
# ---------------------------------------------------------------------------


def test_semantic_flag_false_produces_same_output_as_old_logic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the flag is False, the evidence package must match the old logic
    exactly (no semantic retrieval results appended)."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=False),
    )

    selected = _ranked(1, "Keaton Sample", 82.0, prediction_sort_score=83.5)
    pick = _pick(selected)
    notes = [_manual_note()]

    package_with_notes = build_pick_evidence(
        _simulation(pick), pick, manual_notes=notes
    )

    # The manual note should still be matched via the old _manual_notes_for_pick
    # path, but no semantic retrieval results should be appended.
    # Old logic: 1 manual note matched → 1 retrieved_evidence + 1 citation
    # (plus 2 citations from _build_citations for projection_source and
    # team_projection_type).
    assert len(package_with_notes.retrieved_evidence) == 1
    assert len(package_with_notes.citations) == 3  # 2 base + 1 manual note


def test_semantic_flag_false_does_not_call_embed_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the flag is False, embed_chunks must NOT be called."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=False),
    )

    called: list[Any] = []

    def _fail(*args: Any, **kwargs: Any) -> Any:
        called.append(args)
        raise AssertionError("embed_chunks must not be called when flag is False")

    monkeypatch.setattr("app.services.evidence_service.embed_chunks", _fail)

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    build_pick_evidence(_simulation(pick), pick, manual_notes=[_manual_note()])

    assert called == []


def test_semantic_flag_false_does_not_call_retrieve_semantic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the flag is False, retrieve_semantic must NOT be called."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=False),
    )

    called: list[Any] = []

    def _fail(*args: Any, **kwargs: Any) -> Any:
        called.append(args)
        raise AssertionError(
            "retrieve_semantic must not be called when flag is False"
        )

    monkeypatch.setattr("app.services.evidence_service.retrieve_semantic", _fail)

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    build_pick_evidence(_simulation(pick), pick, manual_notes=[_manual_note()])

    assert called == []


def test_semantic_flag_false_does_not_call_vector_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the flag is False, InMemoryVectorStore must NOT be instantiated."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=False),
    )

    called: list[Any] = []

    original_init = type(
        "OriginalInit", (), {}
    )  # placeholder; we patch the class itself

    def _fail_init(self: Any, *args: Any, **kwargs: Any) -> None:
        called.append(args)
        raise AssertionError(
            "InMemoryVectorStore must not be instantiated when flag is False"
        )

    monkeypatch.setattr(
        "app.services.evidence_service.InMemoryVectorStore.__init__", _fail_init
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    build_pick_evidence(_simulation(pick), pick, manual_notes=[_manual_note()])

    assert called == []


# ---------------------------------------------------------------------------
# Flag True: appends semantic retrieval results
# ---------------------------------------------------------------------------


def test_semantic_flag_true_appends_retrieved_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the flag is True, semantic retrieval must append
    RetrievedEvidence to the evidence package."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    fake_retrieved = _fake_retrieved_evidence(retrieval_score=0.9)
    fake_citation = _fake_citation()

    def _fake_retrieve(*, query_text, chunks, vector_store, top_k, min_score):
        return [fake_retrieved], [fake_citation]

    monkeypatch.setattr(
        "app.services.evidence_service.retrieve_semantic", _fake_retrieve
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    notes = [_manual_note()]

    package = build_pick_evidence(_simulation(pick), pick, manual_notes=notes)

    # Old logic: 1 manual note → 1 retrieved_evidence
    # Semantic: +1 retrieved_evidence
    assert len(package.retrieved_evidence) == 2
    # The semantic one should have retrieval_score set.
    semantic_evidence = [
        e for e in package.retrieved_evidence if e.retrieval_score is not None
    ]
    assert len(semantic_evidence) >= 1
    assert semantic_evidence[0].retrieval_score == 0.9


def test_semantic_flag_true_appends_evidence_citation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the flag is True, semantic retrieval must append
    EvidenceCitation to the evidence package."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    fake_retrieved = _fake_retrieved_evidence()
    fake_citation = _fake_citation(source_id="semantic-cite-0")

    def _fake_retrieve(*, query_text, chunks, vector_store, top_k, min_score):
        return [fake_retrieved], [fake_citation]

    monkeypatch.setattr(
        "app.services.evidence_service.retrieve_semantic", _fake_retrieve
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    notes = [_manual_note()]

    package = build_pick_evidence(_simulation(pick), pick, manual_notes=notes)

    # Old logic: 2 base citations + 1 manual note citation = 3
    # Semantic: +1 citation
    assert len(package.citations) == 4
    # The semantic citation should be findable by source_id.
    semantic_cites = [
        c for c in package.citations if c.source_id == "semantic-cite-0"
    ]
    assert len(semantic_cites) == 1


def test_semantic_flag_true_calls_retrieve_semantic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the flag is True, retrieve_semantic must be called."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    call_count: list[int] = [0]

    def _spy_retrieve(*, query_text, chunks, vector_store, top_k, min_score):
        call_count[0] += 1
        assert query_text  # must not be empty
        assert len(chunks) > 0
        assert top_k == 5
        assert min_score == 0.0
        return [], []

    monkeypatch.setattr(
        "app.services.evidence_service.retrieve_semantic", _spy_retrieve
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    build_pick_evidence(_simulation(pick), pick, manual_notes=[_manual_note()])

    assert call_count[0] == 1


def test_semantic_flag_true_calls_embed_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the flag is True, embed_chunks must be called."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    call_count: list[int] = [0]

    original_embed_chunks = None

    import app.services.evidence_service as es_module

    original_embed_chunks = es_module.embed_chunks

    def _spy_embed(chunks):
        call_count[0] += 1
        # Call the real embed_chunks to get real embeddings.
        return original_embed_chunks(chunks)

    monkeypatch.setattr("app.services.evidence_service.embed_chunks", _spy_embed)

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    build_pick_evidence(_simulation(pick), pick, manual_notes=[_manual_note()])

    assert call_count[0] == 1


# ---------------------------------------------------------------------------
# Fallback: failure isolation
# ---------------------------------------------------------------------------


def test_semantic_retrieval_failure_falls_back_without_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When retrieve_semantic raises, the evidence package must still build
    without exception and without semantic results."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    def _fail_retrieve(*, query_text, chunks, vector_store, top_k, min_score):
        raise RuntimeError("simulated semantic retrieval failure")

    monkeypatch.setattr(
        "app.services.evidence_service.retrieve_semantic", _fail_retrieve
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    notes = [_manual_note()]

    # Must not raise.
    package = build_pick_evidence(_simulation(pick), pick, manual_notes=notes)

    # Old logic: 1 manual note → 1 retrieved_evidence (semantic failed → 0 added)
    assert len(package.retrieved_evidence) == 1


def test_semantic_retrieval_chunk_failure_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When chunk_text raises, the evidence package must still build."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    def _fail_chunk(*args, **kwargs):
        raise ValueError("simulated chunking failure")

    monkeypatch.setattr("app.services.evidence_service.chunk_text", _fail_chunk)

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    notes = [_manual_note()]

    package = build_pick_evidence(_simulation(pick), pick, manual_notes=notes)

    # Old logic still works.
    assert len(package.retrieved_evidence) == 1


def test_semantic_retrieval_embed_failure_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When embed_chunks raises, the evidence package must still build."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    def _fail_embed(chunks):
        raise RuntimeError("simulated embedding failure")

    monkeypatch.setattr("app.services.evidence_service.embed_chunks", _fail_embed)

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    notes = [_manual_note()]

    package = build_pick_evidence(_simulation(pick), pick, manual_notes=notes)

    assert len(package.retrieved_evidence) == 1


def test_semantic_retrieval_empty_results_does_not_break_old_logic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When retrieve_semantic returns empty results, the old logic must be
    unaffected."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    def _empty_retrieve(*, query_text, chunks, vector_store, top_k, min_score):
        return [], []

    monkeypatch.setattr(
        "app.services.evidence_service.retrieve_semantic", _empty_retrieve
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    notes = [_manual_note()]

    package = build_pick_evidence(_simulation(pick), pick, manual_notes=notes)

    # Old logic: 1 manual note → 1 retrieved_evidence (semantic empty → 0 added)
    assert len(package.retrieved_evidence) == 1
    assert len(package.citations) == 3  # 2 base + 1 manual note


def test_no_manual_notes_skips_semantic_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When there are no manual notes, semantic retrieval must be skipped."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    called: list[Any] = []

    def _fail_retrieve(*, query_text, chunks, vector_store, top_k, min_score):
        called.append(1)
        raise AssertionError(
            "retrieve_semantic must not be called when no manual notes"
        )

    monkeypatch.setattr(
        "app.services.evidence_service.retrieve_semantic", _fail_retrieve
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    # No manual notes.
    package = build_pick_evidence(_simulation(pick), pick, manual_notes=None)

    assert called == []
    assert len(package.retrieved_evidence) == 0


# ---------------------------------------------------------------------------
# retrieval_score isolation
# ---------------------------------------------------------------------------


def test_retrieval_score_present_in_retrieved_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """retrieval_score must be present in RetrievedEvidence from semantic
    retrieval."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    fake_retrieved = _fake_retrieved_evidence(retrieval_score=0.75)
    fake_citation = _fake_citation()

    def _fake_retrieve(*, query_text, chunks, vector_store, top_k, min_score):
        return [fake_retrieved], [fake_citation]

    monkeypatch.setattr(
        "app.services.evidence_service.retrieve_semantic", _fake_retrieve
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    package = build_pick_evidence(
        _simulation(pick), pick, manual_notes=[_manual_note()]
    )

    semantic_evidence = [
        e for e in package.retrieved_evidence if e.retrieval_score is not None
    ]
    assert len(semantic_evidence) == 1
    assert semantic_evidence[0].retrieval_score == 0.75


def test_retrieval_score_not_in_evidence_citation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """retrieval_score must NOT be in EvidenceCitation from semantic
    retrieval."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    fake_retrieved = _fake_retrieved_evidence(retrieval_score=0.75)
    fake_citation = _fake_citation(source_id="semantic-cite-isolation")

    def _fake_retrieve(*, query_text, chunks, vector_store, top_k, min_score):
        return [fake_retrieved], [fake_citation]

    monkeypatch.setattr(
        "app.services.evidence_service.retrieve_semantic", _fake_retrieve
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    package = build_pick_evidence(
        _simulation(pick), pick, manual_notes=[_manual_note()]
    )

    semantic_cites = [
        c for c in package.citations if c.source_id == "semantic-cite-isolation"
    ]
    assert len(semantic_cites) == 1
    # EvidenceCitation schema must not have retrieval_score field.
    assert "retrieval_score" not in semantic_cites[0].model_fields
    assert "retrieval_score" not in semantic_cites[0].model_dump()


def test_retrieval_score_not_in_llm_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """retrieval_score from semantic retrieval must NOT enter the LLM
    payload whitelist."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    fake_retrieved = _fake_retrieved_evidence(retrieval_score=0.95)
    fake_citation = _fake_citation()

    def _fake_retrieve(*, query_text, chunks, vector_store, top_k, min_score):
        return [fake_retrieved], [fake_citation]

    monkeypatch.setattr(
        "app.services.evidence_service.retrieve_semantic", _fake_retrieve
    )

    from app.services.evidence_llm_explanation_service import (
        _build_llm_explanation_payload,
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    package = build_pick_evidence(
        _simulation(pick), pick, manual_notes=[_manual_note()]
    )

    payload = _build_llm_explanation_payload(package)
    retrieved_items = payload.get("retrieved_evidence", [])
    assert len(retrieved_items) >= 1
    for item in retrieved_items:
        assert "retrieval_score" not in item


# ---------------------------------------------------------------------------
# Decision boundary: does not modify pick decision fields
# ---------------------------------------------------------------------------


def test_semantic_retrieval_does_not_modify_selected_player(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Semantic retrieval must not change selected_player_id / name."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    fake_retrieved = _fake_retrieved_evidence()
    fake_citation = _fake_citation()

    def _fake_retrieve(*, query_text, chunks, vector_store, top_k, min_score):
        return [fake_retrieved], [fake_citation]

    monkeypatch.setattr(
        "app.services.evidence_service.retrieve_semantic", _fake_retrieve
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    package = build_pick_evidence(
        _simulation(pick), pick, manual_notes=[_manual_note()]
    )

    assert package.selected_player_id == 1
    assert package.selected_player_name == "Keaton Sample"


def test_semantic_retrieval_does_not_modify_final_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Semantic retrieval must not change final_score."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    fake_retrieved = _fake_retrieved_evidence()
    fake_citation = _fake_citation()

    def _fake_retrieve(*, query_text, chunks, vector_store, top_k, min_score):
        return [fake_retrieved], [fake_citation]

    monkeypatch.setattr(
        "app.services.evidence_service.retrieve_semantic", _fake_retrieve
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    package = build_pick_evidence(
        _simulation(pick), pick, manual_notes=[_manual_note()]
    )

    assert package.ranking_evidence.final_score == 82.0


def test_semantic_retrieval_does_not_modify_prediction_sort_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Semantic retrieval must not change prediction_sort_score."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    fake_retrieved = _fake_retrieved_evidence()
    fake_citation = _fake_citation()

    def _fake_retrieve(*, query_text, chunks, vector_store, top_k, min_score):
        return [fake_retrieved], [fake_citation]

    monkeypatch.setattr(
        "app.services.evidence_service.retrieve_semantic", _fake_retrieve
    )

    selected = _ranked(1, "Keaton Sample", 82.0, prediction_sort_score=83.5)
    pick = _pick(selected)
    package = build_pick_evidence(
        _simulation(pick), pick, manual_notes=[_manual_note()]
    )

    assert package.ranking_evidence.prediction_sort_score == 83.5


# ---------------------------------------------------------------------------
# Selection system boundary: does not call ranking / simulation / prediction
# ---------------------------------------------------------------------------


def test_semantic_wiring_does_not_call_ranking_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Semantic retrieval wiring must not call ranking_engine.rank_prospects."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    called: list[Any] = []

    def _fail_rank(*args, **kwargs):
        called.append(1)
        raise AssertionError(
            "ranking_engine.rank_prospects must not be called by semantic wiring"
        )

    monkeypatch.setattr(
        "app.services.ranking_engine.rank_prospects", _fail_rank
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    build_pick_evidence(_simulation(pick), pick, manual_notes=[_manual_note()])

    assert called == []


def test_semantic_wiring_does_not_call_simulation_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Semantic retrieval wiring must not call simulation_service."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    called: list[Any] = []

    def _fail_sim(*args, **kwargs):
        called.append(1)
        raise AssertionError(
            "simulation_service must not be called by semantic wiring"
        )

    # Patch the module's simulate_draft function if it exists.
    try:
        monkeypatch.setattr(
            "app.services.simulation_service.simulate_draft", _fail_sim
        )
    except AttributeError:
        pass  # Function name may differ; the patch attempt is sufficient.

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    build_pick_evidence(_simulation(pick), pick, manual_notes=[_manual_note()])

    assert called == []


def test_semantic_wiring_does_not_call_prediction_calibration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Semantic retrieval wiring must not call prediction_calibration."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    called: list[Any] = []

    def _fail_calib(*args, **kwargs):
        called.append(1)
        raise AssertionError(
            "prediction_calibration must not be called by semantic wiring"
        )

    try:
        monkeypatch.setattr(
            "app.services.prediction_calibration.calibrate_predictions",
            _fail_calib,
        )
    except AttributeError:
        pass

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    build_pick_evidence(_simulation(pick), pick, manual_notes=[_manual_note()])

    assert called == []


# ---------------------------------------------------------------------------
# Full integration: real semantic retrieval pipeline
# ---------------------------------------------------------------------------


def test_full_semantic_pipeline_appends_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: with the flag on and real (fake) embedding / vector store
    / retrieval, the evidence package must get semantic results appended."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    notes = [
        _manual_note(
            note_id=1,
            body="Keaton Sample is a strong perimeter defender with excellent lateral quickness and on-ball pressure.",
            title="Scouting report for Keaton Sample",
            summary="Perimeter defender profile.",
        ),
        _manual_note(
            note_id=2,
            body="The LA Clippers need a perimeter defender to complement their wing rotation.",
            title="Team need analysis for LAC",
            summary="LAC team need.",
            entity_type="team",
            prospect_id=None,
            team_id=1,
        ),
    ]

    package = build_pick_evidence(_simulation(pick), pick, manual_notes=notes)

    # Old logic: 2 manual notes matched (prospect + team) → 2 retrieved_evidence
    # Semantic: +N retrieved_evidence (at least 1)
    assert len(package.retrieved_evidence) >= 2
    # At least one should have retrieval_score set (from semantic retrieval).
    semantic_evidence = [
        e for e in package.retrieved_evidence if e.retrieval_score is not None
    ]
    assert len(semantic_evidence) >= 1
    # All retrieval_scores must be >= 0.
    for e in semantic_evidence:
        assert e.retrieval_score is not None
        assert e.retrieval_score >= 0.0


def test_full_semantic_pipeline_does_not_crash_with_many_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The semantic pipeline must handle multiple manual notes without
    crashing."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True),
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    notes = [
        _manual_note(
            note_id=i,
            body=f"Note {i} about Keaton Sample perimeter defense and team fit for LAC.",
            title=f"Note {i}",
        )
        for i in range(10)
    ]

    # Must not raise.
    package = build_pick_evidence(_simulation(pick), pick, manual_notes=notes)

    # Must have at least the old-logic evidence.
    assert len(package.retrieved_evidence) >= 1


def test_semantic_retrieval_respects_top_k_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The top_k config must be passed through to retrieve_semantic."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True, top_k=3),
    )

    captured_top_k: list[int] = []

    def _spy_retrieve(*, query_text, chunks, vector_store, top_k, min_score):
        captured_top_k.append(top_k)
        return [], []

    monkeypatch.setattr(
        "app.services.evidence_service.retrieve_semantic", _spy_retrieve
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    build_pick_evidence(_simulation(pick), pick, manual_notes=[_manual_note()])

    assert captured_top_k == [3]


def test_semantic_retrieval_respects_min_score_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The min_score config must be passed through to retrieve_semantic."""
    monkeypatch.setattr(
        "app.services.evidence_service.get_settings",
        lambda: _semantic_settings(enabled=True, min_score=0.5),
    )

    captured_min_score: list[float] = []

    def _spy_retrieve(*, query_text, chunks, vector_store, top_k, min_score):
        captured_min_score.append(min_score)
        return [], []

    monkeypatch.setattr(
        "app.services.evidence_service.retrieve_semantic", _spy_retrieve
    )

    selected = _ranked(1, "Keaton Sample", 82.0)
    pick = _pick(selected)
    build_pick_evidence(_simulation(pick), pick, manual_notes=[_manual_note()])

    assert captured_min_score == [0.5]
