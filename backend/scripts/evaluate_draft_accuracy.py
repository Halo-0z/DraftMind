"""Read-only draft accuracy evaluation script.

Evaluates DraftMind simulation results against project-internal projection /
consensus data to establish an accuracy baseline.  This script is **read-only**:

  * It never writes to the database.
  * It never modifies ranking_engine / prediction_calibration /
    simulation_service behavior.
  * It never touches RAG / Evidence / LLM logic.
  * It never fetches live mock-draft data from the network.

The script runs ``simulate_draft()`` in-process (calibration off and on),
loads ``ProspectDraftProjection`` / ``TeamPickProjection`` from the DB, and
computes pick-error / range-hit / top-N overlap / team-match metrics.

If projection data is missing, the script reports ``status: unavailable`` with
a reason -- it never fabricates consensus data.

JSON output fields (additive over versions):
  * ``picks`` -- per-pick detail for calibration OFF (always present).
  * ``calibration_off_vs_on`` -- aggregate OFF/ON metric comparison.
  * ``calibration_on_picks`` -- per-pick detail for calibration ON (M3-C,
    only when ``compare_calibration=True``).
  * ``calibration_pick_diffs`` -- per-pick OFF vs ON diff entries with
    ``impact`` classification (M3-C, only when ``compare_calibration=True``).
  * ``calibration_pick_diff_summary`` -- aggregate diff counts with
    ``round_1`` / ``round_2`` breakdowns (M3-C, only when
    ``compare_calibration=True``).

Usage::

    cd D:\\DraftMind\\backend
    D:\\anaconda\\python.exe scripts\\evaluate_draft_accuracy.py
    D:\\anaconda\\python.exe scripts\\evaluate_draft_accuracy.py --json
    D:\\anaconda\\python.exe scripts\\evaluate_draft_accuracy.py --year 2026 --rounds 2 --limit 60

Options:
    --year INT       draft year (default 2026)
    --rounds INT     simulation rounds 1 or 2 (default 1)
    --limit INT      max picks (default 60)
    --json           emit machine-readable JSON instead of human text
    --no-calibration-comparison
                     skip the calibration on/off comparison (only run off)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    DraftOrder,
    Prospect,
    ProspectDraftProjection,
    TeamPickProjection,
)
from app.schemas.simulation import SimulateRequest  # noqa: E402
from app.services.simulation_service import simulate_draft  # noqa: E402


# ---------------------------------------------------------------------------
# Pure metric functions (testable without DB)
# ---------------------------------------------------------------------------


def calculate_pick_error(selected_pick: int, expected_pick: int | None) -> int | None:
    """Return ``abs(selected_pick - expected_pick)`` or ``None`` if no projection."""
    if expected_pick is None:
        return None
    return abs(selected_pick - expected_pick)


def calculate_projected_range_hit(
    selected_pick: int,
    range_min: int | None,
    range_max: int | None,
) -> bool | None:
    """Return True if ``selected_pick`` is within ``[range_min, range_max]``.

    Returns ``None`` if both bounds are missing (cannot evaluate).
    """
    if range_min is None and range_max is None:
        return None
    lo = range_min or 1
    hi = range_max or 60
    return lo <= selected_pick <= hi


def calculate_top_n_overlap(
    sim_prospect_ids: list[int],
    consensus_prospect_ids: list[int],
    n: int,
) -> dict[str, Any]:
    """Compute top-N overlap between simulation and consensus rankings.

    Returns a dict with ``sim_top_n``, ``consensus_top_n``, ``overlap_count``,
    ``overlap_rate`` (relative to the smaller of the two sets), and
    ``status``.
    """
    sim_set = set(sim_prospect_ids[:n])
    cons_set = set(consensus_prospect_ids[:n])
    if not sim_set or not cons_set:
        return {
            "sim_top_n": len(sim_set),
            "consensus_top_n": len(cons_set),
            "overlap_count": 0,
            "overlap_rate": 0.0,
            "status": "unavailable",
            "reason": "missing_consensus_data" if not cons_set else "missing_simulation_data",
        }
    overlap = sim_set & cons_set
    denom = min(len(sim_set), len(cons_set))
    return {
        "sim_top_n": len(sim_set),
        "consensus_top_n": len(cons_set),
        "overlap_count": len(overlap),
        "overlap_rate": round(len(overlap) / denom, 4) if denom else 0.0,
        "status": "available",
    }


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PickEvaluation:
    """Per-pick evaluation result."""

    pick_no: int
    prospect_id: int | None
    prospect_name: str | None
    selected_pick: int
    expected_pick: int | None
    pick_error: int | None
    draft_range_min: int | None
    draft_range_max: int | None
    projected_range_hit: bool | None
    consensus_rank: int | None
    big_board_rank: int | None
    projection_source: str | None
    projection_confidence: float | None
    team_projection_match: bool | None
    is_locked_pick: bool
    # --- M3-C additive fields (per-pick calibration diff support) ---
    round: int = 1
    team_abbr: str | None = None
    missing_projection: bool = False
    selected_outside_projected_range: bool = False


@dataclass
class AccuracyReport:
    """Full accuracy evaluation report."""

    # --- metadata ---
    year: int
    rounds: int
    limit: int
    locked_picks_active: bool
    prediction_mode: bool  # False if locked_picks active or no calibration

    # --- counts ---
    total_simulation_picks: int
    total_evaluated_picks: int  # picks with projection data

    # --- pick error ---
    average_pick_error: float | None
    median_pick_error: float | None
    exact_pick_match_count: int
    exact_pick_match_rate: float | None

    # --- top-N overlap ---
    top_5_overlap: dict[str, Any] = field(default_factory=dict)
    top_10_overlap: dict[str, Any] = field(default_factory=dict)
    lottery_overlap: dict[str, Any] = field(default_factory=dict)
    first_round_overlap: dict[str, Any] = field(default_factory=dict)

    # --- projected range ---
    projected_range_hit_count: int = 0
    projected_range_hit_rate: float | None = None

    # --- team projection ---
    team_player_exact_match_count: int = 0
    team_player_exact_match_rate: float | None = None

    # --- warnings ---
    selected_player_outside_projected_range: list[dict[str, Any]] = field(default_factory=list)
    high_upside_no_projection: list[dict[str, Any]] = field(default_factory=list)
    missing_projection: list[dict[str, Any]] = field(default_factory=list)
    stale_seed_projection: list[dict[str, Any]] = field(default_factory=list)

    # --- per-pick detail ---
    picks: list[dict[str, Any]] = field(default_factory=list)

    # --- calibration comparison ---
    calibration_off_vs_on: dict[str, Any] | None = None

    # --- overall status ---
    status: str = "available"
    unavailable_reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core evaluation logic
# ---------------------------------------------------------------------------

LOCKED_PICK_LOG_MARKER = "This pick was locked by user override."


def _is_locked_pick(decision_log: list[str]) -> bool:
    """Check if a pick was locked by user override (not a prediction)."""
    return any(LOCKED_PICK_LOG_MARKER in entry for entry in decision_log)


def _pick_round(pick_no: int) -> int:
    """Return the draft round for a pick number.

    Picks 1-30 are round 1, picks 31-60 are round 2.
    """
    if pick_no <= 30:
        return 1
    return 2


# ---------------------------------------------------------------------------
# Per-pick calibration diff helpers (M3-C)
# ---------------------------------------------------------------------------

IMPACT_LABELS = (
    "unchanged",
    "clearly_improved",
    "likely_improved",
    "neutral_or_unclear",
    "likely_worse",
    "risky_change",
    "unavailable",
)


def classify_pick_diff_impact(
    off_pick: dict[str, Any],
    on_pick: dict[str, Any],
) -> str:
    """Classify the impact of calibration on a single pick (conservative).

    Rules (in priority order):
      * ``unchanged`` -- same prospect selected at this pick.
      * ``unavailable`` -- both OFF/ON lack a computable pick_error, or ON
        lacks a projection while OFF has one (cannot compare).
      * ``likely_improved`` -- OFF has no projection but ON does (ON error
        computable), or ON error is 1-2 smaller than OFF error.
      * ``clearly_improved`` -- ON error is >= 3 smaller than OFF error and
        range_hit did not worsen.
      * ``neutral_or_unclear`` -- ON error equals OFF error and range_hit
        did not worsen, or error improved but range_hit worsened (mixed).
      * ``likely_worse`` -- ON error is 1-2 larger than OFF error.
      * ``risky_change`` -- ON error is >= 3 larger than OFF error, or
        range_hit went True -> False while error is unchanged.

    The function never fabricates errors. When projection data is missing
    on either side and a comparison is impossible, it returns
    ``unavailable``.
    """
    off_id = off_pick.get("prospect_id")
    on_id = on_pick.get("prospect_id")

    # Same prospect selected -> unchanged (errors would be identical)
    if off_id is not None and off_id == on_id:
        return "unchanged"

    off_error = off_pick.get("pick_error")
    on_error = on_pick.get("pick_error")
    off_range_hit = off_pick.get("projected_range_hit")
    on_range_hit = on_pick.get("projected_range_hit")

    # Both errors missing -> cannot compare
    if off_error is None and on_error is None:
        return "unavailable"

    # OFF missing projection, ON has computable error -> likely_improved
    if off_error is None and on_error is not None:
        return "likely_improved"

    # ON missing projection, OFF has error -> cannot compare ON side
    if off_error is not None and on_error is None:
        return "unavailable"

    # Both errors available -- compute delta (negative = ON better)
    delta = on_error - off_error
    range_worsened = (off_range_hit is True and on_range_hit is False)

    if delta <= -3:
        # Meaningful improvement; if range worsened it's a mixed signal
        return "neutral_or_unclear" if range_worsened else "clearly_improved"

    if delta in (-2, -1):
        # Slight improvement; mixed if range worsened
        return "neutral_or_unclear" if range_worsened else "likely_improved"

    if delta == 0:
        # Error unchanged; risky if range_hit went True -> False
        return "risky_change" if range_worsened else "neutral_or_unclear"

    if delta in (1, 2):
        # Slight worsening
        return "likely_worse"

    # delta >= 3 -- meaningful worsening
    return "risky_change"


def _range_hit_delta_label(
    off_hit: bool | None, on_hit: bool | None
) -> str:
    """Label the change in projected_range_hit between OFF and ON."""
    if off_hit is None or on_hit is None:
        return "unavailable"
    if off_hit == on_hit:
        return "unchanged"
    if on_hit is True and off_hit is False:
        return "improved"
    return "worsened"


def build_calibration_pick_diffs(
    off_picks: list[dict[str, Any]],
    on_picks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build per-pick OFF vs ON diff entries.

    Only picks present in both lists are compared (matched by index, which
    corresponds to pick order). Each entry includes the impact
    classification from :func:`classify_pick_diff_impact`.
    """
    diffs: list[dict[str, Any]] = []
    n = min(len(off_picks), len(on_picks))
    for i in range(n):
        off = off_picks[i]
        on = on_picks[i]
        off_error = off.get("pick_error")
        on_error = on.get("pick_error")
        pick_error_delta: int | None
        if off_error is not None and on_error is not None:
            pick_error_delta = on_error - off_error
        else:
            pick_error_delta = None

        diffs.append({
            "pick_no": off.get("pick_no"),
            "round": off.get("round"),
            "team_abbr": off.get("team_abbr"),
            "off_prospect_name": off.get("prospect_name"),
            "on_prospect_name": on.get("prospect_name"),
            "changed": off.get("prospect_id") != on.get("prospect_id"),
            "off_expected_pick": off.get("expected_pick"),
            "on_expected_pick": on.get("expected_pick"),
            "off_pick_error": off_error,
            "on_pick_error": on_error,
            "pick_error_delta": pick_error_delta,
            "off_projected_range_hit": off.get("projected_range_hit"),
            "on_projected_range_hit": on.get("projected_range_hit"),
            "range_hit_delta": _range_hit_delta_label(
                off.get("projected_range_hit"), on.get("projected_range_hit")
            ),
            "impact": classify_pick_diff_impact(off, on),
        })
    return diffs


def _empty_impact_counts() -> dict[str, int]:
    return {label: 0 for label in IMPACT_LABELS}


def build_calibration_pick_diff_summary(
    diffs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build aggregate summary of per-pick calibration diffs.

    Includes overall counts plus per-round breakdowns (round 1 = picks
    1-30, round 2 = picks 31-60).
    """
    overall = _empty_impact_counts()
    overall["total_picks"] = len(diffs)
    overall["changed_picks"] = 0
    overall["unchanged_picks"] = 0

    round_buckets: dict[int, dict[str, Any]] = {1: _empty_impact_counts(), 2: _empty_impact_counts()}
    for r in (1, 2):
        round_buckets[r]["total_picks"] = 0
        round_buckets[r]["changed_picks"] = 0
        round_buckets[r]["unchanged_picks"] = 0

    for d in diffs:
        impact = d.get("impact", "unavailable")
        changed = d.get("changed", False)
        r = d.get("round") or 1
        if r not in round_buckets:
            round_buckets[r] = _empty_impact_counts()
            round_buckets[r]["total_picks"] = 0
            round_buckets[r]["changed_picks"] = 0
            round_buckets[r]["unchanged_picks"] = 0

        overall[impact] = overall.get(impact, 0) + 1
        overall["total_picks"] += 0  # already set
        if changed:
            overall["changed_picks"] += 1
        else:
            overall["unchanged_picks"] += 1

        round_buckets[r][impact] = round_buckets[r].get(impact, 0) + 1
        round_buckets[r]["total_picks"] += 1
        if changed:
            round_buckets[r]["changed_picks"] += 1
        else:
            round_buckets[r]["unchanged_picks"] += 1

    overall["round_1"] = round_buckets.get(1, _empty_impact_counts())
    overall["round_2"] = round_buckets.get(2, _empty_impact_counts())
    return overall


def evaluate_simulation(
    *,
    sim_picks: list[dict[str, Any]],
    prospect_projections: dict[int, dict[str, Any]],
    team_projections: dict[tuple[int, int], dict[str, Any]],
    year: int,
    rounds: int,
    limit: int,
) -> AccuracyReport:
    """Evaluate simulation picks against projection data.

    This is a pure function -- it does not touch the DB or call any service.
    All inputs are plain dicts/dataclasses.

    Args:
        sim_picks: list of pick dicts, each with at least ``pick``,
            ``selected_player`` (with ``id``, ``name``), ``team`` (with
            ``id``), and ``decision_log``.
        prospect_projections: ``{prospect_id: projection_dict}`` where
            projection_dict has ``expected_pick``, ``draft_range_min``,
            ``draft_range_max``, ``consensus_rank``, ``big_board_rank``,
            ``source``, ``confidence``.
        team_projections: ``{(pick_no, team_id): projection_dict}`` where
            projection_dict has ``prospect_id``.
        year: draft year.
        rounds: simulation rounds.
        limit: max picks.

    Returns:
        AccuracyReport with all metrics populated.
    """
    report = AccuracyReport(
        year=year,
        rounds=rounds,
        limit=limit,
        locked_picks_active=False,
        prediction_mode=True,
        total_simulation_picks=len(sim_picks),
        total_evaluated_picks=0,
        average_pick_error=None,
        median_pick_error=None,
        exact_pick_match_count=0,
        exact_pick_match_rate=None,
    )

    pick_errors: list[int] = []
    range_hits = 0
    range_evaluable = 0
    team_matches = 0
    team_evaluable = 0
    sim_prospect_ids_ordered: list[int] = []
    consensus_prospect_ids_ordered: list[int] = []

    # Build consensus ordering from projections (sorted by consensus_rank)
    consensus_sorted = sorted(
        (
            (pid, proj)
            for pid, proj in prospect_projections.items()
            if proj.get("consensus_rank") is not None
        ),
        key=lambda x: x[1]["consensus_rank"],
    )
    consensus_prospect_ids_ordered = [pid for pid, _ in consensus_sorted]

    for pick_data in sim_picks:
        pick_no = pick_data["pick"]
        selected = pick_data["selected_player"]
        prospect_id = selected.get("id")
        prospect_name = selected.get("name")
        team_data = pick_data.get("team", {})
        team_id = team_data.get("id")
        team_abbr = team_data.get("abbr")
        decision_log = pick_data.get("decision_log", [])

        is_locked = _is_locked_pick(decision_log)
        if is_locked:
            report.locked_picks_active = True
            report.prediction_mode = False

        sim_prospect_ids_ordered.append(prospect_id)

        proj = prospect_projections.get(prospect_id) if prospect_id else None

        if proj is None:
            report.missing_projection.append({
                "pick_no": pick_no,
                "prospect_id": prospect_id,
                "prospect_name": prospect_name,
                "reason": "no ProspectDraftProjection for this prospect",
            })
            pick_eval = PickEvaluation(
                pick_no=pick_no,
                prospect_id=prospect_id,
                prospect_name=prospect_name,
                selected_pick=pick_no,
                expected_pick=None,
                pick_error=None,
                draft_range_min=None,
                draft_range_max=None,
                projected_range_hit=None,
                consensus_rank=None,
                big_board_rank=None,
                projection_source=None,
                projection_confidence=None,
                team_projection_match=None,
                is_locked_pick=is_locked,
                round=_pick_round(pick_no),
                team_abbr=team_abbr,
                missing_projection=True,
                selected_outside_projected_range=False,
            )
            report.picks.append(asdict(pick_eval))
            continue

        report.total_evaluated_picks += 1

        expected_pick = proj.get("expected_pick")
        range_min = proj.get("draft_range_min")
        range_max = proj.get("draft_range_max")
        consensus_rank = proj.get("consensus_rank")
        big_board_rank = proj.get("big_board_rank")
        source = proj.get("source")
        confidence = proj.get("confidence")

        # Stale seed_projection warning
        if source == "seed_projection":
            report.stale_seed_projection.append({
                "pick_no": pick_no,
                "prospect_id": prospect_id,
                "prospect_name": prospect_name,
                "reason": "projection source is seed_projection (demo data, not real consensus)",
            })

        pick_error = calculate_pick_error(pick_no, expected_pick)
        if pick_error is not None:
            pick_errors.append(pick_error)
            if pick_error == 0:
                report.exact_pick_match_count += 1

        range_hit = calculate_projected_range_hit(pick_no, range_min, range_max)
        if range_hit is not None:
            range_evaluable += 1
            if range_hit:
                range_hits += 1
            else:
                report.selected_player_outside_projected_range.append({
                    "pick_no": pick_no,
                    "prospect_id": prospect_id,
                    "prospect_name": prospect_name,
                    "selected_pick": pick_no,
                    "draft_range_min": range_min,
                    "draft_range_max": range_max,
                })

        # Team projection match
        team_proj = team_projections.get((pick_no, team_id)) if team_id else None
        if team_proj is not None:
            team_evaluable += 1
            if team_proj.get("prospect_id") == prospect_id:
                team_matches += 1

        pick_eval = PickEvaluation(
            pick_no=pick_no,
            prospect_id=prospect_id,
            prospect_name=prospect_name,
            selected_pick=pick_no,
            expected_pick=expected_pick,
            pick_error=pick_error,
            draft_range_min=range_min,
            draft_range_max=range_max,
            projected_range_hit=range_hit,
            consensus_rank=consensus_rank,
            big_board_rank=big_board_rank,
            projection_source=source,
            projection_confidence=confidence,
            team_projection_match=(
                team_proj.get("prospect_id") == prospect_id
                if team_proj is not None
                else None
            ),
            is_locked_pick=is_locked,
            round=_pick_round(pick_no),
            team_abbr=team_abbr,
            missing_projection=False,
            selected_outside_projected_range=(range_hit is False),
        )
        report.picks.append(asdict(pick_eval))

    # Aggregate metrics
    if pick_errors:
        report.average_pick_error = round(statistics.mean(pick_errors), 4)
        report.median_pick_error = round(statistics.median(pick_errors), 4)
        report.exact_pick_match_rate = round(
            report.exact_pick_match_count / len(pick_errors), 4
        )

    if range_evaluable > 0:
        report.projected_range_hit_count = range_hits
        report.projected_range_hit_rate = round(range_hits / range_evaluable, 4)

    if team_evaluable > 0:
        report.team_player_exact_match_count = team_matches
        report.team_player_exact_match_rate = round(team_matches / team_evaluable, 4)

    # Top-N overlap
    report.top_5_overlap = calculate_top_n_overlap(
        sim_prospect_ids_ordered, consensus_prospect_ids_ordered, 5
    )
    report.top_10_overlap = calculate_top_n_overlap(
        sim_prospect_ids_ordered, consensus_prospect_ids_ordered, 10
    )
    report.lottery_overlap = calculate_top_n_overlap(
        sim_prospect_ids_ordered, consensus_prospect_ids_ordered, 14
    )
    report.first_round_overlap = calculate_top_n_overlap(
        sim_prospect_ids_ordered, consensus_prospect_ids_ordered, 30
    )

    # High-upside no projection: prospects selected in top 30 without projection
    for pick_data in sim_picks[:30]:
        selected = pick_data["selected_player"]
        prospect_id = selected.get("id")
        if prospect_id and prospect_id not in prospect_projections:
            report.high_upside_no_projection.append({
                "pick_no": pick_data["pick"],
                "prospect_id": prospect_id,
                "prospect_name": selected.get("name"),
                "reason": "selected in top 30 but has no ProspectDraftProjection",
            })

    # Overall status
    if report.total_evaluated_picks == 0:
        report.status = "unavailable"
        report.unavailable_reasons.append("missing_projection_data")
    if not consensus_prospect_ids_ordered:
        report.unavailable_reasons.append("missing_consensus_data")

    return report


# ---------------------------------------------------------------------------
# DB loading helpers (read-only)
# ---------------------------------------------------------------------------


def load_prospect_projections(
    db: Session, year: int
) -> dict[int, dict[str, Any]]:
    """Load ProspectDraftProjection for the given year, keyed by prospect_id.

    When multiple sources exist for the same prospect, priority is:
    manual_projection > seed_projection > consensus_reference.
    """
    priority = {"manual_projection": 0, "seed_projection": 1, "consensus_reference": 2}
    stmt = select(ProspectDraftProjection).where(
        ProspectDraftProjection.year == year
    )
    rows = db.execute(stmt).scalars().all()

    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        existing = result.get(row.prospect_id)
        if existing is None or priority.get(row.source, 99) < priority.get(
            existing["source"], 99
        ):
            result[row.prospect_id] = {
                "expected_pick": row.expected_pick,
                "draft_range_min": row.draft_range_min,
                "draft_range_max": row.draft_range_max,
                "consensus_rank": row.consensus_rank,
                "big_board_rank": row.big_board_rank,
                "tier": row.tier,
                "source": row.source,
                "source_count": row.source_count,
                "confidence": row.confidence,
                "last_updated": row.last_updated.isoformat() if row.last_updated else None,
                "notes": row.notes,
            }
    return result


def load_team_projections(
    db: Session, year: int
) -> dict[tuple[int, int], dict[str, Any]]:
    """Load TeamPickProjection for the given year, keyed by (pick_no, team_id).

    When multiple types exist for the same (pick_no, team_id), priority is:
    manual_prediction > team_report > workout_signal > consensus_mock.
    """
    priority = {
        "manual_prediction": 0,
        "team_report": 1,
        "workout_signal": 2,
        "consensus_mock": 3,
    }
    stmt = select(TeamPickProjection).where(TeamPickProjection.year == year)
    rows = db.execute(stmt).scalars().all()

    result: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        key = (row.pick_no, row.team_id)
        existing = result.get(key)
        if existing is None or priority.get(row.projection_type, 99) < priority.get(
            existing["projection_type"], 99
        ):
            result[key] = {
                "prospect_id": row.prospect_id,
                "projection_type": row.projection_type,
                "source": row.source,
                "confidence": row.confidence,
                "notes": row.notes,
            }
    return result


def load_consensus_prospect_ids(
    db: Session, year: int
) -> list[int]:
    """Load prospect IDs ordered by consensus_rank (ascending)."""
    stmt = (
        select(ProspectDraftProjection)
        .where(
            ProspectDraftProjection.year == year,
            ProspectDraftProjection.consensus_rank.is_not(None),
        )
        .order_by(ProspectDraftProjection.consensus_rank)
    )
    rows = db.execute(stmt).scalars().all()
    return [row.prospect_id for row in rows]


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------


def _sim_pick_to_dict(pick: Any) -> dict[str, Any]:
    """Convert a SimulatedPickRead pydantic model to a plain dict for evaluation.

    RankedProspectRead wraps a ProspectRead (which has id/name), so we drill
    through ``selected_player.prospect`` to get the prospect identity.
    """
    return {
        "pick": pick.pick,
        "team": {"id": pick.team.id, "abbr": pick.team.abbr},
        "selected_player": {
            "id": pick.selected_player.prospect.id,
            "name": pick.selected_player.prospect.name,
        },
        "decision_log": pick.decision_log,
    }


def run_simulation(
    db: Session,
    *,
    year: int,
    rounds: int,
    limit: int,
    use_calibration: bool = False,
) -> list[dict[str, Any]]:
    """Run simulate_draft() and return picks as plain dicts.

    This function is read-only with respect to the DB -- simulate_draft()
    itself does not persist results.
    """
    request = SimulateRequest(
        year=year,
        rounds=rounds,
        limit=limit,
        evaluate_trades=True,
        include_projection_diagnostics=True,
        include_prediction_shadow=True,
        use_prediction_calibration=use_calibration,
        locked_picks=None,  # No locked picks -- pure prediction mode
    )
    response = simulate_draft(db, request)
    return [_sim_pick_to_dict(p) for p in response.picks]


# ---------------------------------------------------------------------------
# Full evaluation pipeline
# ---------------------------------------------------------------------------


def run_evaluation(
    db: Session,
    *,
    year: int = 2026,
    rounds: int = 1,
    limit: int = 60,
    compare_calibration: bool = True,
) -> dict[str, Any]:
    """Run the full accuracy evaluation pipeline.

    Returns a JSON-serializable dict with the full report.
    """
    # 1. Load projection data (read-only)
    prospect_projections = load_prospect_projections(db, year)
    team_projections = load_team_projections(db, year)

    # 2. Run simulation with calibration OFF
    sim_picks_off = run_simulation(
        db, year=year, rounds=rounds, limit=limit, use_calibration=False
    )

    # 3. Evaluate calibration OFF
    report_off = evaluate_simulation(
        sim_picks=sim_picks_off,
        prospect_projections=prospect_projections,
        team_projections=team_projections,
        year=year,
        rounds=rounds,
        limit=limit,
    )

    result = asdict(report_off)

    # 4. Calibration on/off comparison
    if compare_calibration:
        try:
            sim_picks_on = run_simulation(
                db, year=year, rounds=rounds, limit=limit, use_calibration=True
            )
            report_on = evaluate_simulation(
                sim_picks=sim_picks_on,
                prospect_projections=prospect_projections,
                team_projections=team_projections,
                year=year,
                rounds=rounds,
                limit=limit,
            )

            # Per-pick ON detail (M3-C)
            # report_on.picks is already a list of dicts (asdict applied in
            # evaluate_simulation), so we use it directly.
            on_picks_detail = list(report_on.picks)
            result["calibration_on_picks"] = on_picks_detail

            # Per-pick OFF vs ON diff (M3-C)
            off_picks_detail = result.get("picks", [])
            pick_diffs = build_calibration_pick_diffs(
                off_picks_detail, on_picks_detail
            )
            result["calibration_pick_diffs"] = pick_diffs

            # Aggregate diff summary with round grouping (M3-C)
            result["calibration_pick_diff_summary"] = (
                build_calibration_pick_diff_summary(pick_diffs)
            )

            # Compute diff (aggregate metrics, kept for backward compat)
            diff = {
                "calibration_off": {
                    "average_pick_error": report_off.average_pick_error,
                    "exact_pick_match_rate": report_off.exact_pick_match_rate,
                    "projected_range_hit_rate": report_off.projected_range_hit_rate,
                    "top_5_overlap_rate": report_off.top_5_overlap.get("overlap_rate"),
                    "top_10_overlap_rate": report_off.top_10_overlap.get("overlap_rate"),
                },
                "calibration_on": {
                    "average_pick_error": report_on.average_pick_error,
                    "exact_pick_match_rate": report_on.exact_pick_match_rate,
                    "projected_range_hit_rate": report_on.projected_range_hit_rate,
                    "top_5_overlap_rate": report_on.top_5_overlap.get("overlap_rate"),
                    "top_10_overlap_rate": report_on.top_10_overlap.get("overlap_rate"),
                },
                "selected_player_changes": sum(
                    1
                    for i in range(min(len(sim_picks_off), len(sim_picks_on)))
                    if sim_picks_off[i]["selected_player"]["id"]
                    != sim_picks_on[i]["selected_player"]["id"]
                ),
            }
            result["calibration_off_vs_on"] = diff
        except Exception as exc:
            result["calibration_off_vs_on"] = {
                "status": "unavailable",
                "reason": f"calibration_comparison_failed: {type(exc).__name__}: {exc}",
            }

    return result


# ---------------------------------------------------------------------------
# Human-readable report
# ---------------------------------------------------------------------------


def format_human_report(report: dict[str, Any]) -> str:
    """Format the evaluation report as human-readable text."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("DraftMind Draft Accuracy Evaluation Report")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"Year:                  {report['year']}")
    lines.append(f"Rounds:                {report['rounds']}")
    lines.append(f"Limit:                 {report['limit']}")
    lines.append(f"Locked picks active:   {report['locked_picks_active']}")
    lines.append(f"Prediction mode:       {report['prediction_mode']}")
    lines.append(f"Overall status:        {report['status']}")
    if report.get("unavailable_reasons"):
        lines.append(f"Unavailable reasons:   {', '.join(report['unavailable_reasons'])}")
    lines.append("")

    lines.append("-" * 72)
    lines.append("Pick Counts")
    lines.append("-" * 72)
    lines.append(f"  Total simulation picks:    {report['total_simulation_picks']}")
    lines.append(f"  Total evaluated picks:     {report['total_evaluated_picks']}")
    lines.append("")

    lines.append("-" * 72)
    lines.append("Pick Error")
    lines.append("-" * 72)
    avg = report.get("average_pick_error")
    med = report.get("median_pick_error")
    lines.append(f"  Average pick error:        {avg if avg is not None else 'unavailable'}")
    lines.append(f"  Median pick error:         {med if med is not None else 'unavailable'}")
    lines.append(f"  Exact pick match count:    {report['exact_pick_match_count']}")
    rate = report.get("exact_pick_match_rate")
    lines.append(f"  Exact pick match rate:     {rate if rate is not None else 'unavailable'}")
    lines.append("")

    lines.append("-" * 72)
    lines.append("Top-N Overlap (simulation vs consensus)")
    lines.append("-" * 72)
    for label, key in [
        ("Top 5", "top_5_overlap"),
        ("Top 10", "top_10_overlap"),
        ("Lottery (14)", "lottery_overlap"),
        ("First Round (30)", "first_round_overlap"),
    ]:
        ov = report.get(key, {})
        status = ov.get("status", "unavailable")
        if status == "available":
            lines.append(
                f"  {label:20s}  overlap={ov['overlap_count']}  "
                f"rate={ov['overlap_rate']:.2%}  "
                f"(sim={ov['sim_top_n']}, consensus={ov['consensus_top_n']})"
            )
        else:
            reason = ov.get("reason", "unknown")
            lines.append(f"  {label:20s}  unavailable ({reason})")
    lines.append("")

    lines.append("-" * 72)
    lines.append("Projected Range")
    lines.append("-" * 72)
    lines.append(f"  Projected range hit count: {report['projected_range_hit_count']}")
    rrate = report.get("projected_range_hit_rate")
    lines.append(
        f"  Projected range hit rate:  {rrate if rrate is not None else 'unavailable'}"
    )
    lines.append("")

    lines.append("-" * 72)
    lines.append("Team Projection Match")
    lines.append("-" * 72)
    lines.append(f"  Team-player exact match count: {report['team_player_exact_match_count']}")
    trate = report.get("team_player_exact_match_rate")
    lines.append(
        f"  Team-player exact match rate:  {trate if trate is not None else 'unavailable'}"
    )
    lines.append("")

    # Warnings
    lines.append("-" * 72)
    lines.append("Warnings")
    lines.append("-" * 72)
    lines.append(f"  Selected outside projected range: {len(report['selected_player_outside_projected_range'])}")
    lines.append(f"  High upside no projection:        {len(report['high_upside_no_projection'])}")
    lines.append(f"  Missing projection:               {len(report['missing_projection'])}")
    lines.append(f"  Stale seed projection:            {len(report['stale_seed_projection'])}")
    lines.append("")

    # Calibration comparison
    cal = report.get("calibration_off_vs_on")
    if cal:
        lines.append("-" * 72)
        lines.append("Calibration Off vs On")
        lines.append("-" * 72)
        if "status" in cal and cal.get("status") == "unavailable":
            lines.append(f"  {cal.get('reason', 'unavailable')}")
        else:
            off = cal.get("calibration_off", {})
            on = cal.get("calibration_on", {})
            lines.append(f"  {'Metric':30s} {'OFF':>12s} {'ON':>12s}")
            lines.append(f"  {'-'*30} {'-'*12} {'-'*12}")
            for metric in [
                "average_pick_error",
                "exact_pick_match_rate",
                "projected_range_hit_rate",
                "top_5_overlap_rate",
                "top_10_overlap_rate",
            ]:
                off_val = off.get(metric)
                on_val = on.get(metric)
                lines.append(
                    f"  {metric:30s} "
                    f"{str(off_val):>12s} {str(on_val):>12s}"
                )
            lines.append(f"  Selected player changes:         {cal.get('selected_player_changes', 'N/A')}")
            # M3-C: per-pick diff summary (if available)
            summary = report.get("calibration_pick_diff_summary")
            if summary:
                lines.append("")
                lines.append("  Per-pick diff summary:")
                lines.append(
                    f"    changed={summary.get('changed_picks', 0)}  "
                    f"unchanged={summary.get('unchanged_picks', 0)}"
                )
                for label in [
                    "clearly_improved",
                    "likely_improved",
                    "neutral_or_unclear",
                    "likely_worse",
                    "risky_change",
                    "unavailable",
                ]:
                    lines.append(f"    {label:22s} {summary.get(label, 0)}")
                for rnd_key, rnd_label in [("round_1", "Round 1"), ("round_2", "Round 2")]:
                    rnd = summary.get(rnd_key, {})
                    lines.append(
                        f"    {rnd_label:22s} "
                        f"total={rnd.get('total_picks', 0)}  "
                        f"changed={rnd.get('changed_picks', 0)}  "
                        f"risky={rnd.get('risky_change', 0)}  "
                        f"likely_worse={rnd.get('likely_worse', 0)}"
                    )
        lines.append("")

    lines.append("=" * 72)
    lines.append("End of Report")
    lines.append("=" * 72)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only draft accuracy evaluation script."
    )
    parser.add_argument("--year", type=int, default=2026, help="draft year (default 2026)")
    parser.add_argument("--rounds", type=int, default=1, choices=[1, 2], help="simulation rounds (default 1)")
    parser.add_argument("--limit", type=int, default=60, help="max picks (default 60)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of human text")
    parser.add_argument(
        "--no-calibration-comparison",
        action="store_true",
        help="skip calibration on/off comparison",
    )
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        report = run_evaluation(
            db,
            year=args.year,
            rounds=args.rounds,
            limit=args.limit,
            compare_calibration=not args.no_calibration_comparison,
        )

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_human_report(report))

    return 0


if __name__ == "__main__":
    sys.exit(main())
