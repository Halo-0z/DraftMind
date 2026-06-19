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
    calculate_pick_error,
    calculate_projected_range_hit,
    calculate_top_n_overlap,
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
        assert report["average_pick_error"] is None
