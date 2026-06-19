"""Tests for the read-only draft accuracy evaluation script.

Covers:
  1. Script does not write DB.
  2. Pick error calculation is correct.
  3. Projected range hit calculation is correct.
  4. Top-N overlap calculation is correct.
  5. Exact match calculation is correct.
  6. Missing consensus / missing projection -> unavailable / warning (no fabrication).
  7. Calibration on/off comparison does not change underlying data.
  8. locked_picks default off / marked as non-prediction mode.
  9. retrieval_score / evidence / semantic similarity / LLM output not in accuracy score.
 10. Script runs stably on test fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models import (
    DraftOrder,
    Prospect,
    ProspectDraftProjection,
    Team,
    TeamNeed,
    TeamPickProjection,
)

# Import from the script module
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from evaluate_draft_accuracy import (  # noqa: E402
    AccuracyReport,
    build_calibration_pick_diff_summary,
    build_calibration_pick_diffs,
    calculate_pick_error,
    calculate_projected_range_hit,
    calculate_top_n_overlap,
    classify_pick_diff_impact,
    evaluate_simulation,
    format_human_report,
    load_prospect_projections,
    load_team_projections,
    run_evaluation,
    run_simulation,
)


# ---------------------------------------------------------------------------
# Pure function tests (no DB needed)
# ---------------------------------------------------------------------------


class TestCalculatePickError:
    def test_basic_error(self) -> None:
        assert calculate_pick_error(5, 3) == 2

    def test_zero_error(self) -> None:
        assert calculate_pick_error(7, 7) == 0

    def test_none_expected_pick(self) -> None:
        assert calculate_pick_error(5, None) is None

    def test_reverse_error(self) -> None:
        assert calculate_pick_error(3, 10) == 7


class TestCalculateProjectedRangeHit:
    def test_within_range(self) -> None:
        assert calculate_projected_range_hit(5, 3, 8) is True

    def test_at_min_boundary(self) -> None:
        assert calculate_projected_range_hit(3, 3, 8) is True

    def test_at_max_boundary(self) -> None:
        assert calculate_projected_range_hit(8, 3, 8) is True

    def test_below_range(self) -> None:
        assert calculate_projected_range_hit(1, 3, 8) is False

    def test_above_range(self) -> None:
        assert calculate_projected_range_hit(15, 3, 8) is False

    def test_both_none(self) -> None:
        assert calculate_projected_range_hit(5, None, None) is None

    def test_only_min(self) -> None:
        assert calculate_projected_range_hit(5, 3, None) is True
        assert calculate_projected_range_hit(1, 3, None) is False

    def test_only_max(self) -> None:
        assert calculate_projected_range_hit(5, None, 10) is True
        assert calculate_projected_range_hit(15, None, 10) is False


class TestCalculateTopNOverlap:
    def test_full_overlap(self) -> None:
        sim = [1, 2, 3, 4, 5]
        consensus = [1, 2, 3, 4, 5]
        result = calculate_top_n_overlap(sim, consensus, 5)
        assert result["overlap_count"] == 5
        assert result["overlap_rate"] == 1.0
        assert result["status"] == "available"

    def test_no_overlap(self) -> None:
        sim = [1, 2, 3, 4, 5]
        consensus = [6, 7, 8, 9, 10]
        result = calculate_top_n_overlap(sim, consensus, 5)
        assert result["overlap_count"] == 0
        assert result["overlap_rate"] == 0.0

    def test_partial_overlap(self) -> None:
        sim = [1, 2, 3, 4, 5]
        consensus = [1, 2, 6, 7, 8]
        result = calculate_top_n_overlap(sim, consensus, 5)
        assert result["overlap_count"] == 2
        assert result["overlap_rate"] == 0.4

    def test_empty_consensus(self) -> None:
        sim = [1, 2, 3]
        result = calculate_top_n_overlap(sim, [], 5)
        assert result["status"] == "unavailable"
        assert result["reason"] == "missing_consensus_data"

    def test_empty_sim(self) -> None:
        result = calculate_top_n_overlap([], [1, 2, 3], 5)
        assert result["status"] == "unavailable"
        assert result["reason"] == "missing_simulation_data"

    def test_n_larger_than_lists(self) -> None:
        sim = [1, 2]
        consensus = [1, 2]
        result = calculate_top_n_overlap(sim, consensus, 10)
        assert result["overlap_count"] == 2
        assert result["overlap_rate"] == 1.0


# ---------------------------------------------------------------------------
# evaluate_simulation tests (pure function, no DB)
# ---------------------------------------------------------------------------


def _make_sim_pick(
    pick_no: int,
    prospect_id: int,
    prospect_name: str = "Test Player",
    team_id: int = 1,
    decision_log: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "pick": pick_no,
        "team": {"id": team_id, "abbr": "TST"},
        "selected_player": {"id": prospect_id, "name": prospect_name},
        "decision_log": decision_log or [],
    }


def _make_projection(
    expected_pick: int | None = 5,
    draft_range_min: int | None = 3,
    draft_range_max: int | None = 8,
    consensus_rank: int | None = 5,
    big_board_rank: int | None = 5,
    source: str = "consensus_reference",
    confidence: float = 0.7,
) -> dict[str, Any]:
    return {
        "expected_pick": expected_pick,
        "draft_range_min": draft_range_min,
        "draft_range_max": draft_range_max,
        "consensus_rank": consensus_rank,
        "big_board_rank": big_board_rank,
        "tier": 3,
        "source": source,
        "source_count": 2,
        "confidence": confidence,
        "last_updated": "2026-06-14T00:00:00+00:00",
        "notes": "test projection",
    }


class TestEvaluateSimulationExactMatch:
    def test_exact_match_count_and_rate(self) -> None:
        sim_picks = [
            _make_sim_pick(1, prospect_id=101),
            _make_sim_pick(2, prospect_id=102),
            _make_sim_pick(3, prospect_id=103),
        ]
        projections = {
            101: _make_projection(expected_pick=1, consensus_rank=1),
            102: _make_projection(expected_pick=2, consensus_rank=2),
            103: _make_projection(expected_pick=5, consensus_rank=3),
        }
        report = evaluate_simulation(
            sim_picks=sim_picks,
            prospect_projections=projections,
            team_projections={},
            year=2026,
            rounds=1,
            limit=60,
        )
        assert report.exact_pick_match_count == 2
        assert report.exact_pick_match_rate == round(2 / 3, 4)
        assert report.total_evaluated_picks == 3


class TestEvaluateSimulationPickError:
    def test_average_and_median_pick_error(self) -> None:
        sim_picks = [
            _make_sim_pick(1, prospect_id=101),
            _make_sim_pick(5, prospect_id=102),
            _make_sim_pick(10, prospect_id=103),
        ]
        projections = {
            101: _make_projection(expected_pick=3, consensus_rank=1),
            102: _make_projection(expected_pick=2, consensus_rank=2),
            103: _make_projection(expected_pick=7, consensus_rank=3),
        }
        report = evaluate_simulation(
            sim_picks=sim_picks,
            prospect_projections=projections,
            team_projections={},
            year=2026,
            rounds=1,
            limit=60,
        )
        # errors: |1-3|=2, |5-2|=3, |10-7|=3
        assert report.average_pick_error == round((2 + 3 + 3) / 3, 4)
        assert report.median_pick_error == 3


class TestEvaluateSimulationProjectedRange:
    def test_range_hit_count_and_rate(self) -> None:
        sim_picks = [
            _make_sim_pick(5, prospect_id=101),   # in [3,8] -> hit
            _make_sim_pick(10, prospect_id=102),  # outside [3,8] -> miss
            _make_sim_pick(3, prospect_id=103),   # at min [3,8] -> hit
        ]
        projections = {
            101: _make_projection(draft_range_min=3, draft_range_max=8),
            102: _make_projection(draft_range_min=3, draft_range_max=8),
            103: _make_projection(draft_range_min=3, draft_range_max=8),
        }
        report = evaluate_simulation(
            sim_picks=sim_picks,
            prospect_projections=projections,
            team_projections={},
            year=2026,
            rounds=1,
            limit=60,
        )
        assert report.projected_range_hit_count == 2
        assert report.projected_range_hit_rate == round(2 / 3, 4)
        assert len(report.selected_player_outside_projected_range) == 1
        assert report.selected_player_outside_projected_range[0]["pick_no"] == 10


class TestEvaluateSimulationTopNOverlap:
    def test_top_5_overlap(self) -> None:
        sim_picks = [
            _make_sim_pick(i, prospect_id=100 + i) for i in range(1, 11)
        ]
        projections = {
            101: _make_projection(consensus_rank=1),
            102: _make_projection(consensus_rank=2),
            103: _make_projection(consensus_rank=3),
            104: _make_projection(consensus_rank=4),
            105: _make_projection(consensus_rank=5),
            106: _make_projection(consensus_rank=6),
            107: _make_projection(consensus_rank=7),
            108: _make_projection(consensus_rank=8),
            109: _make_projection(consensus_rank=9),
            110: _make_projection(consensus_rank=10),
        }
        report = evaluate_simulation(
            sim_picks=sim_picks,
            prospect_projections=projections,
            team_projections={},
            year=2026,
            rounds=1,
            limit=60,
        )
        # sim top 5 = {101,102,103,104,105}, consensus top 5 = {101,102,103,104,105}
        assert report.top_5_overlap["overlap_count"] == 5
        assert report.top_5_overlap["overlap_rate"] == 1.0


class TestEvaluateSimulationMissingData:
    def test_missing_projection_does_not_fabricate(self) -> None:
        """When a prospect has no projection, it should be reported as
        missing, not fabricated."""
        sim_picks = [
            _make_sim_pick(1, prospect_id=101),
            _make_sim_pick(2, prospect_id=999),  # no projection
        ]
        projections = {
            101: _make_projection(expected_pick=1, consensus_rank=1),
        }
        report = evaluate_simulation(
            sim_picks=sim_picks,
            prospect_projections=projections,
            team_projections={},
            year=2026,
            rounds=1,
            limit=60,
        )
        assert report.total_evaluated_picks == 1
        assert len(report.missing_projection) == 1
        assert report.missing_projection[0]["prospect_id"] == 999
        # The missing prospect should NOT appear in pick error stats
        assert report.exact_pick_match_count == 1
        assert report.exact_pick_match_rate == 1.0

    def test_all_missing_projections_reports_unavailable(self) -> None:
        sim_picks = [_make_sim_pick(1, prospect_id=101)]
        report = evaluate_simulation(
            sim_picks=sim_picks,
            prospect_projections={},
            team_projections={},
            year=2026,
            rounds=1,
            limit=60,
        )
        assert report.status == "unavailable"
        assert "missing_projection_data" in report.unavailable_reasons
        assert "missing_consensus_data" in report.unavailable_reasons
        assert report.total_evaluated_picks == 0
        assert report.average_pick_error is None
        assert report.exact_pick_match_rate is None

    def test_missing_team_projection_does_not_crash(self) -> None:
        sim_picks = [_make_sim_pick(1, prospect_id=101, team_id=1)]
        projections = {101: _make_projection()}
        report = evaluate_simulation(
            sim_picks=sim_picks,
            prospect_projections=projections,
            team_projections={},  # no team projections
            year=2026,
            rounds=1,
            limit=60,
        )
        assert report.team_player_exact_match_count == 0
        assert report.team_player_exact_match_rate is None


class TestEvaluateSimulationLockedPicks:
    def test_locked_pick_marked_as_non_prediction(self) -> None:
        """A pick with the locked-pick log marker should set
        locked_picks_active=True and prediction_mode=False."""
        sim_picks = [
            _make_sim_pick(
                1,
                prospect_id=101,
                decision_log=["This pick was locked by user override."],
            ),
        ]
        projections = {101: _make_projection()}
        report = evaluate_simulation(
            sim_picks=sim_picks,
            prospect_projections=projections,
            team_projections={},
            year=2026,
            rounds=1,
            limit=60,
        )
        assert report.locked_picks_active is True
        assert report.prediction_mode is False
        assert report.picks[0]["is_locked_pick"] is True

    def test_no_locked_picks_defaults_to_prediction_mode(self) -> None:
        sim_picks = [_make_sim_pick(1, prospect_id=101)]
        projections = {101: _make_projection()}
        report = evaluate_simulation(
            sim_picks=sim_picks,
            prospect_projections=projections,
            team_projections={},
            year=2026,
            rounds=1,
            limit=60,
        )
        assert report.locked_picks_active is False
        assert report.prediction_mode is True
        assert report.picks[0]["is_locked_pick"] is False


class TestEvaluateSimulationStaleSeedProjection:
    def test_seed_projection_flagged_as_stale(self) -> None:
        sim_picks = [_make_sim_pick(1, prospect_id=101)]
        projections = {
            101: _make_projection(source="seed_projection"),
        }
        report = evaluate_simulation(
            sim_picks=sim_picks,
            prospect_projections=projections,
            team_projections={},
            year=2026,
            rounds=1,
            limit=60,
        )
        assert len(report.stale_seed_projection) == 1
        assert report.stale_seed_projection[0]["prospect_id"] == 101


class TestEvaluateSimulationNoRetrievalScore:
    """Verify that retrieval_score / evidence / LLM fields never enter the
    accuracy score."""

    def test_accuracy_report_has_no_retrieval_score_field(self) -> None:
        report = evaluate_simulation(
            sim_picks=[],
            prospect_projections={},
            team_projections={},
            year=2026,
            rounds=1,
            limit=60,
        )
        report_dict = report.__dict__
        # No retrieval_score / evidence / semantic / llm fields in the report
        forbidden_keys = [
            "retrieval_score",
            "evidence",
            "semantic_similarity",
            "llm_output",
            "llm_explanation",
        ]
        for key in forbidden_keys:
            assert key not in report_dict, f"AccuracyReport should not have '{key}'"

    def test_pick_evaluation_has_no_retrieval_score_field(self) -> None:
        from evaluate_draft_accuracy import PickEvaluation

        pe = PickEvaluation(
            pick_no=1,
            prospect_id=101,
            prospect_name="Test",
            selected_pick=1,
            expected_pick=1,
            pick_error=0,
            draft_range_min=1,
            draft_range_max=5,
            projected_range_hit=True,
            consensus_rank=1,
            big_board_rank=1,
            projection_source="consensus_reference",
            projection_confidence=0.7,
            team_projection_match=None,
            is_locked_pick=False,
        )
        pe_dict = pe.__dict__
        forbidden_keys = [
            "retrieval_score",
            "evidence",
            "semantic_similarity",
            "llm_output",
        ]
        for key in forbidden_keys:
            assert key not in pe_dict, f"PickEvaluation should not have '{key}'"


# ---------------------------------------------------------------------------
# DB integration tests (using db_session fixture)
# ---------------------------------------------------------------------------


def _seed_minimal_fixture(db: Session) -> None:
    """Add projections and pick_no=1 to the conftest-seeded DB.

    The base ``db_session`` fixture already seeds:
      * Teams: SAS (Spurs), HOU (Rockets)
      * TeamNeeds for both teams
      * Prospects: Mikel Brown Jr. (PG), Braylon Mullins (SG)
      * DraftOrder: pick_no 2, 5, 10, 20 for year 2026

    This fixture adds:
      * DraftOrder pick_no=1 (so simulation has a first pick)
      * ProspectDraftProjection for both prospects
      * TeamPickProjection for pick_no=1
    """
    # Get conftest-seeded teams and prospects
    spurs = db.query(Team).filter(Team.abbr == "SAS").first()
    assert spurs is not None, "conftest should seed SAS"
    prospects = db.query(Prospect).filter(Prospect.year == 2026).all()
    assert len(prospects) >= 2, "conftest should seed at least 2 prospects"
    p1 = prospects[0]  # Mikel Brown Jr.
    p2 = prospects[1]  # Braylon Mullins

    # Add pick_no=1 (conftest only seeds 2, 5, 10, 20)
    db.add(DraftOrder(year=2026, pick_no=1, team_id=spurs.id))

    # Add ProspectDraftProjection for both prospects
    db.add_all([
        ProspectDraftProjection(
            prospect_id=p1.id, year=2026,
            consensus_rank=1, big_board_rank=1, expected_pick=1,
            draft_range_min=1, draft_range_max=3, tier=1,
            source="consensus_reference", source_count=3, confidence=0.8,
        ),
        ProspectDraftProjection(
            prospect_id=p2.id, year=2026,
            consensus_rank=2, big_board_rank=2, expected_pick=2,
            draft_range_min=1, draft_range_max=4, tier=1,
            source="consensus_reference", source_count=3, confidence=0.75,
        ),
    ])

    # Add TeamPickProjection for pick_no=1
    db.add(TeamPickProjection(
        year=2026, pick_no=1, team_id=spurs.id, prospect_id=p1.id,
        projection_type="consensus_mock", source="consensus_reference",
        confidence=0.7,
    ))

    db.commit()


class TestRunEvaluationNoDBWrite:
    """Verify that run_evaluation never writes to the DB."""

    def test_run_evaluation_does_not_write_db(self, db_session: Session) -> None:
        _seed_minimal_fixture(db_session)

        # Snapshot all table row counts before
        inspector = inspect(db_session.bind)
        before_counts: dict[str, int] = {}
        for table_name in inspector.get_table_names():
            from sqlalchemy import text
            result = db_session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            before_counts[table_name] = result.scalar()

        # Run evaluation
        report = run_evaluation(
            db_session,
            year=2026,
            rounds=1,
            limit=2,
            compare_calibration=False,
        )

        # Snapshot all table row counts after
        after_counts: dict[str, int] = {}
        for table_name in inspector.get_table_names():
            from sqlalchemy import text
            result = db_session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            after_counts[table_name] = result.scalar()

        # No table should have grown
        for table_name in before_counts:
            assert before_counts[table_name] == after_counts[table_name], (
                f"Table '{table_name}' grew from {before_counts[table_name]} "
                f"to {after_counts[table_name]} -- eval script must not write DB"
            )

    def test_run_evaluation_does_not_commit(self, db_session: Session) -> None:
        """Verify no pending writes after evaluation (no dirty session)."""
        _seed_minimal_fixture(db_session)
        run_evaluation(
            db_session,
            year=2026,
            rounds=1,
            limit=2,
            compare_calibration=False,
        )
        # Session should have no pending changes (dirty/new are IdentitySet, not set)
        assert len(db_session.dirty) == 0, "Session has dirty objects after eval"
        assert len(db_session.new) == 0, "Session has new objects after eval"
        assert len(db_session.deleted) == 0, "Session has deleted objects after eval"


class TestRunEvaluationStability:
    def test_run_evaluation_runs_without_error(self, db_session: Session) -> None:
        _seed_minimal_fixture(db_session)
        report = run_evaluation(
            db_session,
            year=2026,
            rounds=1,
            limit=2,
            compare_calibration=False,
        )
        assert isinstance(report, dict)
        assert report["year"] == 2026
        assert report["total_simulation_picks"] > 0

    def test_run_evaluation_with_calibration_comparison(self, db_session: Session) -> None:
        _seed_minimal_fixture(db_session)
        report = run_evaluation(
            db_session,
            year=2026,
            rounds=1,
            limit=2,
            compare_calibration=True,
        )
        assert "calibration_off_vs_on" in report
        cal = report["calibration_off_vs_on"]
        # Should have either a valid diff or an unavailable status
        assert "calibration_off" in cal or "status" in cal

    def test_run_evaluation_does_not_change_underlying_data(
        self, db_session: Session
    ) -> None:
        """Calibration on/off comparison should not change DB data."""
        _seed_minimal_fixture(db_session)

        # Get prospect names before
        before_names = [
            p.name for p in db_session.query(Prospect).order_by(Prospect.id)
        ]

        run_evaluation(
            db_session,
            year=2026,
            rounds=1,
            limit=2,
            compare_calibration=True,
        )

        # Get prospect names after
        after_names = [
            p.name for p in db_session.query(Prospect).order_by(Prospect.id)
        ]
        assert before_names == after_names

    def test_format_human_report_produces_text(self, db_session: Session) -> None:
        _seed_minimal_fixture(db_session)
        report = run_evaluation(
            db_session,
            year=2026,
            rounds=1,
            limit=2,
            compare_calibration=False,
        )
        text = format_human_report(report)
        assert isinstance(text, str)
        assert "DraftMind Draft Accuracy Evaluation Report" in text
        assert "Year:" in text


class TestLoadProjectionsReadOnly:
    def test_load_prospect_projections_returns_dict(self, db_session: Session) -> None:
        _seed_minimal_fixture(db_session)
        projections = load_prospect_projections(db_session, year=2026)
        assert isinstance(projections, dict)
        assert len(projections) >= 1
        for pid, proj in projections.items():
            assert isinstance(pid, int)
            assert "expected_pick" in proj
            assert "draft_range_min" in proj
            assert "source" in proj

    def test_load_team_projections_returns_dict(self, db_session: Session) -> None:
        _seed_minimal_fixture(db_session)
        projections = load_team_projections(db_session, year=2026)
        assert isinstance(projections, dict)
        # Should have at least the 1 team projection we seeded
        assert len(projections) >= 1


class TestRunSimulationNoLockedPicks:
    def test_run_simulation_defaults_to_no_locked_picks(
        self, db_session: Session
    ) -> None:
        """Verify run_simulation uses locked_picks=None by default."""
        _seed_minimal_fixture(db_session)
        picks = run_simulation(
            db_session, year=2026, rounds=1, limit=2, use_calibration=False
        )
        assert isinstance(picks, list)
        # No pick should have the locked-pick marker
        for pick in picks:
            assert not any(
                "locked by user override" in entry
                for entry in pick.get("decision_log", [])
            ), "run_simulation should not use locked picks by default"


class TestRunEvaluationMissingDataHandling:
    def test_run_evaluation_with_no_projections_reports_unavailable(
        self, db_session: Session
    ) -> None:
        """When there are no projections at all, the report should say unavailable."""
        # The conftest already seeds teams, prospects, and draft order.
        # We just don't add any projections.
        # Add pick_no=1 so simulation has at least 1 pick.
        spurs = db_session.query(Team).filter(Team.abbr == "SAS").first()
        assert spurs is not None
        db_session.add(DraftOrder(year=2026, pick_no=1, team_id=spurs.id))
        db_session.commit()

        report = run_evaluation(
            db_session,
            year=2026,
            rounds=1,
            limit=1,
            compare_calibration=False,
        )
        assert report["status"] == "unavailable"
        assert "missing_projection_data" in report["unavailable_reasons"]
        assert "missing_consensus_data" in report["unavailable_reasons"]
        assert report["total_evaluated_picks"] == 0


# ---------------------------------------------------------------------------
# M3-C: Per-pick calibration diff tests
# ---------------------------------------------------------------------------


def _make_pick_eval_dict(
    pick_no: int,
    prospect_id: int = 101,
    prospect_name: str = "Test Player",
    expected_pick: int | None = 5,
    pick_error: int | None = 0,
    draft_range_min: int | None = 3,
    draft_range_max: int | None = 8,
    projected_range_hit: bool | None = True,
    team_abbr: str = "TST",
) -> dict[str, Any]:
    """Build a pick-eval dict matching the PickEvaluation asdict shape."""
    return {
        "pick_no": pick_no,
        "prospect_id": prospect_id,
        "prospect_name": prospect_name,
        "selected_pick": pick_no,
        "expected_pick": expected_pick,
        "pick_error": pick_error,
        "draft_range_min": draft_range_min,
        "draft_range_max": draft_range_max,
        "projected_range_hit": projected_range_hit,
        "consensus_rank": expected_pick,
        "big_board_rank": expected_pick,
        "projection_source": "consensus_reference",
        "projection_confidence": 0.7,
        "team_projection_match": None,
        "is_locked_pick": False,
        "round": 1 if pick_no <= 30 else 2,
        "team_abbr": team_abbr,
        "missing_projection": expected_pick is None,
        "selected_outside_projected_range": projected_range_hit is False,
    }


class TestClassifyPickDiffImpact:
    """Tests for the conservative impact classifier."""

    def test_unchanged_same_prospect(self) -> None:
        off = _make_pick_eval_dict(1, prospect_id=101, pick_error=2)
        on = _make_pick_eval_dict(1, prospect_id=101, pick_error=2)
        assert classify_pick_diff_impact(off, on) == "unchanged"

    def test_clearly_improved(self) -> None:
        off = _make_pick_eval_dict(1, prospect_id=101, pick_error=10)
        on = _make_pick_eval_dict(1, prospect_id=102, pick_error=5)
        # delta = 5 - 10 = -5 <= -3 -> clearly_improved
        assert classify_pick_diff_impact(off, on) == "clearly_improved"

    def test_likely_improved_small_delta(self) -> None:
        off = _make_pick_eval_dict(1, prospect_id=101, pick_error=5)
        on = _make_pick_eval_dict(1, prospect_id=102, pick_error=3)
        # delta = 3 - 5 = -2 -> likely_improved
        assert classify_pick_diff_impact(off, on) == "likely_improved"

    def test_likely_improved_off_missing_projection(self) -> None:
        off = _make_pick_eval_dict(
            1, prospect_id=101, expected_pick=None, pick_error=None,
            draft_range_min=None, draft_range_max=None, projected_range_hit=None,
        )
        on = _make_pick_eval_dict(1, prospect_id=102, pick_error=4)
        assert classify_pick_diff_impact(off, on) == "likely_improved"

    def test_neutral_or_unclear_same_error(self) -> None:
        off = _make_pick_eval_dict(1, prospect_id=101, pick_error=3)
        on = _make_pick_eval_dict(1, prospect_id=102, pick_error=3)
        assert classify_pick_diff_impact(off, on) == "neutral_or_unclear"

    def test_likely_worse(self) -> None:
        off = _make_pick_eval_dict(1, prospect_id=101, pick_error=3)
        on = _make_pick_eval_dict(1, prospect_id=102, pick_error=5)
        # delta = 5 - 3 = 2 -> likely_worse
        assert classify_pick_diff_impact(off, on) == "likely_worse"

    def test_risky_change_large_error(self) -> None:
        off = _make_pick_eval_dict(1, prospect_id=101, pick_error=2)
        on = _make_pick_eval_dict(1, prospect_id=102, pick_error=8)
        # delta = 8 - 2 = 6 >= 3 -> risky_change
        assert classify_pick_diff_impact(off, on) == "risky_change"

    def test_risky_change_range_worsened_same_error(self) -> None:
        off = _make_pick_eval_dict(1, prospect_id=101, pick_error=3, projected_range_hit=True)
        on = _make_pick_eval_dict(1, prospect_id=102, pick_error=3, projected_range_hit=False)
        assert classify_pick_diff_impact(off, on) == "risky_change"

    def test_unavailable_both_missing(self) -> None:
        off = _make_pick_eval_dict(
            1, prospect_id=101, expected_pick=None, pick_error=None,
            draft_range_min=None, draft_range_max=None, projected_range_hit=None,
        )
        on = _make_pick_eval_dict(
            1, prospect_id=102, expected_pick=None, pick_error=None,
            draft_range_min=None, draft_range_max=None, projected_range_hit=None,
        )
        assert classify_pick_diff_impact(off, on) == "unavailable"

    def test_unavailable_on_missing(self) -> None:
        off = _make_pick_eval_dict(1, prospect_id=101, pick_error=3)
        on = _make_pick_eval_dict(
            1, prospect_id=102, expected_pick=None, pick_error=None,
            draft_range_min=None, draft_range_max=None, projected_range_hit=None,
        )
        assert classify_pick_diff_impact(off, on) == "unavailable"

    def test_mixed_improved_error_worsened_range(self) -> None:
        """Error improved by >=3 but range_hit went True -> False: neutral_or_unclear."""
        off = _make_pick_eval_dict(1, prospect_id=101, pick_error=10, projected_range_hit=True)
        on = _make_pick_eval_dict(1, prospect_id=102, pick_error=5, projected_range_hit=False)
        assert classify_pick_diff_impact(off, on) == "neutral_or_unclear"


class TestBuildCalibrationPickDiffs:
    def test_diffs_identify_unchanged(self) -> None:
        off = [_make_pick_eval_dict(1, prospect_id=101)]
        on = [_make_pick_eval_dict(1, prospect_id=101)]
        diffs = build_calibration_pick_diffs(off, on)
        assert len(diffs) == 1
        assert diffs[0]["changed"] is False
        assert diffs[0]["impact"] == "unchanged"

    def test_diffs_identify_changed(self) -> None:
        off = [_make_pick_eval_dict(1, prospect_id=101, pick_error=10)]
        on = [_make_pick_eval_dict(1, prospect_id=102, pick_error=5)]
        diffs = build_calibration_pick_diffs(off, on)
        assert diffs[0]["changed"] is True
        assert diffs[0]["impact"] == "clearly_improved"
        assert diffs[0]["pick_error_delta"] == -5

    def test_diffs_round_field_round1(self) -> None:
        off = [_make_pick_eval_dict(5, prospect_id=101)]
        on = [_make_pick_eval_dict(5, prospect_id=101)]
        diffs = build_calibration_pick_diffs(off, on)
        assert diffs[0]["round"] == 1

    def test_diffs_round_field_round2(self) -> None:
        off = [_make_pick_eval_dict(35, prospect_id=101)]
        on = [_make_pick_eval_dict(35, prospect_id=101)]
        diffs = build_calibration_pick_diffs(off, on)
        assert diffs[0]["round"] == 2

    def test_diffs_no_retrieval_score(self) -> None:
        off = [_make_pick_eval_dict(1, prospect_id=101)]
        on = [_make_pick_eval_dict(1, prospect_id=102)]
        diffs = build_calibration_pick_diffs(off, on)
        forbidden = {"retrieval_score", "evidence", "semantic_similarity", "llm_output"}
        for d in diffs:
            assert not (forbidden & set(d.keys())), (
                f"diff entry must not contain forbidden keys: {forbidden & set(d.keys())}"
            )

    def test_diffs_pick_error_delta_none_when_unavailable(self) -> None:
        off = [_make_pick_eval_dict(
            1, prospect_id=101, expected_pick=None, pick_error=None,
            draft_range_min=None, draft_range_max=None, projected_range_hit=None,
        )]
        on = [_make_pick_eval_dict(1, prospect_id=102, pick_error=4)]
        diffs = build_calibration_pick_diffs(off, on)
        assert diffs[0]["pick_error_delta"] is None
        assert diffs[0]["impact"] == "likely_improved"


class TestBuildCalibrationPickDiffSummary:
    def test_summary_has_required_keys(self) -> None:
        diffs = [
            {"impact": "unchanged", "changed": False, "round": 1},
            {"impact": "clearly_improved", "changed": True, "round": 1},
            {"impact": "risky_change", "changed": True, "round": 2},
        ]
        s = build_calibration_pick_diff_summary(diffs)
        assert s["total_picks"] == 3
        assert s["changed_picks"] == 2
        assert s["unchanged_picks"] == 1
        assert s["clearly_improved"] == 1
        assert s["risky_change"] == 1
        assert "round_1" in s
        assert "round_2" in s

    def test_summary_round_grouping(self) -> None:
        diffs = [
            {"impact": "unchanged", "changed": False, "round": 1},
            {"impact": "risky_change", "changed": True, "round": 2},
            {"impact": "likely_worse", "changed": True, "round": 2},
        ]
        s = build_calibration_pick_diff_summary(diffs)
        assert s["round_1"]["total_picks"] == 1
        assert s["round_1"]["unchanged_picks"] == 1
        assert s["round_2"]["total_picks"] == 2
        assert s["round_2"]["changed_picks"] == 2
        assert s["round_2"]["risky_change"] == 1
        assert s["round_2"]["likely_worse"] == 1

    def test_summary_empty_diffs(self) -> None:
        s = build_calibration_pick_diff_summary([])
        assert s["total_picks"] == 0
        assert s["changed_picks"] == 0
        assert s["round_1"]["total_picks"] == 0
        assert s["round_2"]["total_picks"] == 0


class TestPickEvaluationNewFields:
    def test_pick_evaluation_has_round_and_team_abbr(self) -> None:
        from evaluate_draft_accuracy import PickEvaluation

        pe = PickEvaluation(
            pick_no=1, prospect_id=101, prospect_name="Test",
            selected_pick=1, expected_pick=1, pick_error=0,
            draft_range_min=1, draft_range_max=5, projected_range_hit=True,
            consensus_rank=1, big_board_rank=1,
            projection_source="consensus_reference", projection_confidence=0.7,
            team_projection_match=None, is_locked_pick=False,
            round=1, team_abbr="TST",
            missing_projection=False, selected_outside_projected_range=False,
        )
        assert pe.round == 1
        assert pe.team_abbr == "TST"
        assert pe.missing_projection is False
        assert pe.selected_outside_projected_range is False

    def test_new_fields_not_retrieval_score(self) -> None:
        from evaluate_draft_accuracy import PickEvaluation

        pe = PickEvaluation(
            pick_no=1, prospect_id=101, prospect_name="Test",
            selected_pick=1, expected_pick=1, pick_error=0,
            draft_range_min=1, draft_range_max=5, projected_range_hit=True,
            consensus_rank=1, big_board_rank=1,
            projection_source="consensus_reference", projection_confidence=0.7,
            team_projection_match=None, is_locked_pick=False,
        )
        forbidden = {"retrieval_score", "evidence", "semantic_similarity", "llm_output"}
        assert not (forbidden & set(pe.__dict__.keys()))


class TestRunEvaluationCalibrationDiffFields:
    """DB integration tests for the new M3-C JSON fields."""

    def test_run_evaluation_includes_new_diff_fields(self, db_session: Session) -> None:
        _seed_minimal_fixture(db_session)
        report = run_evaluation(
            db_session,
            year=2026,
            rounds=1,
            limit=2,
            compare_calibration=True,
        )
        assert "calibration_on_picks" in report
        assert "calibration_pick_diffs" in report
        assert "calibration_pick_diff_summary" in report
        # calibration_on_picks should be a list of per-pick dicts
        on_picks = report["calibration_on_picks"]
        assert isinstance(on_picks, list)
        # calibration_pick_diffs should match number of picks
        diffs = report["calibration_pick_diffs"]
        assert isinstance(diffs, list)
        assert len(diffs) == len(on_picks)
        # summary should have round_1 / round_2
        summary = report["calibration_pick_diff_summary"]
        assert "round_1" in summary
        assert "round_2" in summary
        assert summary["total_picks"] == len(diffs)

    def test_run_evaluation_diff_no_retrieval_score(self, db_session: Session) -> None:
        _seed_minimal_fixture(db_session)
        report = run_evaluation(
            db_session,
            year=2026,
            rounds=1,
            limit=2,
            compare_calibration=True,
        )
        forbidden = {"retrieval_score", "evidence", "semantic_similarity", "llm_output"}
        for d in report.get("calibration_pick_diffs", []):
            assert not (forbidden & set(d.keys()))

    def test_run_evaluation_diff_read_only(self, db_session: Session) -> None:
        """Calibration diff computation must not write to DB."""
        _seed_minimal_fixture(db_session)
        inspector = inspect(db_session.bind)
        before_counts: dict[str, int] = {}
        for table_name in inspector.get_table_names():
            from sqlalchemy import text
            result = db_session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            before_counts[table_name] = result.scalar()

        run_evaluation(
            db_session,
            year=2026,
            rounds=1,
            limit=2,
            compare_calibration=True,
        )

        after_counts: dict[str, int] = {}
        for table_name in inspector.get_table_names():
            from sqlalchemy import text
            result = db_session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            after_counts[table_name] = result.scalar()

        for table_name in before_counts:
            assert before_counts[table_name] == after_counts[table_name], (
                f"Table '{table_name}' grew from {before_counts[table_name]} "
                f"to {after_counts[table_name]} -- eval diff must not write DB"
            )

    def test_run_evaluation_backward_compat_off_vs_on(self, db_session: Session) -> None:
        """The original calibration_off_vs_on field must still be present."""
        _seed_minimal_fixture(db_session)
        report = run_evaluation(
            db_session,
            year=2026,
            rounds=1,
            limit=2,
            compare_calibration=True,
        )
        assert "calibration_off_vs_on" in report
        cal = report["calibration_off_vs_on"]
        assert "calibration_off" in cal or "status" in cal


# ---------------------------------------------------------------------------
# M4-D: eval must handle expected_pick > 60 (second-round / UDFA-bubble)
# ---------------------------------------------------------------------------


class TestM4DLateBoardProjection:
    """M4-D: Verify that evaluate_draft_accuracy can calculate pick_error
    for prospects with expected_pick > 60 (second-round / UDFA-bubble
    projections).  These values must NOT become unavailable."""

    def test_calculate_pick_error_works_for_expected_pick_65(self) -> None:
        """calculate_pick_error must return a numeric error for
        expected_pick=65, not None (which would mean unavailable)."""
        error = calculate_pick_error(selected_pick=40, expected_pick=65)
        assert error is not None
        assert error == 25

    def test_calculate_pick_error_works_for_expected_pick_84(self) -> None:
        """calculate_pick_error must work for expected_pick=84."""
        error = calculate_pick_error(selected_pick=60, expected_pick=84)
        assert error is not None
        assert error == 24

    def test_calculate_pick_error_returns_none_for_none_expected(self) -> None:
        """Sanity: None expected_pick still returns None (unavailable)."""
        error = calculate_pick_error(selected_pick=40, expected_pick=None)
        assert error is None
