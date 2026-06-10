from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.draft import DraftOrder
from app.models.prospect import Prospect
from app.models.team import TeamNeed
from app.schemas.simulation import (
    SimulateRequest,
    SimulateResponse,
    SimulatedPickRead,
    TradeEvaluation,
)
from app.services.ranking_engine import rank_prospects
from app.services.recommendation_service import to_ranked_read
from app.services.team_need_service import get_or_infer_team_need


# ---------------------------------------------------------------------------
# Duck-typed contract for any object carrying the prospect attributes that
# adjust_team_need_after_pick cares about.  Both the SQLAlchemy Prospect model
# and the unit-test ProspectStub satisfy this Protocol structurally.
# ---------------------------------------------------------------------------


class ProspectLike(Protocol):
    position: Optional[str]
    three_pct: Optional[float]
    apg: Optional[float]
    stocks: Optional[float]


# ---------------------------------------------------------------------------
# Lightweight copy of TeamNeed so we never mutate ORM objects in the session
# ---------------------------------------------------------------------------

@dataclass
class TeamNeedSnapshot:
    """In-memory copy of team needs for a single simulation run."""

    team_id: int
    year: int
    need_pg: int = 5
    need_sg: int = 5
    need_sf: int = 5
    need_pf: int = 5
    need_c: int = 5
    need_shooting: int = 6
    need_defense: int = 6
    need_creation: int = 6


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clamp_need(value: float | int) -> int:
    """Clamp a need score to the valid range [1, 10]."""
    return max(1, min(10, int(round(value))))


def adjust_team_need_after_pick(team_need: TeamNeedSnapshot, prospect: object) -> None:
    """Decrease position and skill needs after a team selects a prospect.

    Position rules (decrease by 2 each):
      - PG / G  -> need_pg
      - SG / G  -> need_sg
      - SF / F  -> need_sf
      - PF / F  -> need_pf
      - C       -> need_c

    Skill rules (decrease by 1 each):
      - three_pct >= 36  -> need_shooting
      - apg >= 4         -> need_creation
      - stocks >= 1.8    -> need_defense

    All values are clamped to [1, 10].
    """
    pos = (prospect.position or "").upper()

    # Position needs — decrease by 2
    if "PG" in pos or pos == "G":
        team_need.need_pg = clamp_need(team_need.need_pg - 2)
    if "SG" in pos or pos == "G":
        team_need.need_sg = clamp_need(team_need.need_sg - 2)
    if "SF" in pos or pos == "F":
        team_need.need_sf = clamp_need(team_need.need_sf - 2)
    if "PF" in pos or pos == "F":
        team_need.need_pf = clamp_need(team_need.need_pf - 2)
    if "C" in pos:
        team_need.need_c = clamp_need(team_need.need_c - 2)

    # Skill needs — decrease by 1
    if (prospect.three_pct or 0) >= 36:
        team_need.need_shooting = clamp_need(team_need.need_shooting - 1)
    if (prospect.apg or 0) >= 4:
        team_need.need_creation = clamp_need(team_need.need_creation - 1)
    if (prospect.stocks or 0) >= 1.8:
        team_need.need_defense = clamp_need(team_need.need_defense - 1)


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------

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

    prospects = list(
        db.scalars(
            select(Prospect)
            .where(Prospect.year == request.year)
            .order_by(Prospect.upside_score.desc())
        )
    )
    if not prospects:
        raise HTTPException(status_code=404, detail="No prospects found for year")

    selected_prospect_ids: set[int] = set()
    picks: list[SimulatedPickRead] = []

    # Dynamic team-need state: updated after each pick so that later picks
    # by the same team reflect already-addressed needs.
    team_need_state: dict[int, TeamNeedSnapshot] = {}

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

        rankings = rank_prospects(
            team_need=team_need,
            pick_no=draft_pick.pick_no,
            prospects=available_prospects,
        )
        selected = rankings[0]
        alternatives = rankings[1:4]
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
        )
        selected_prospect_ids.add(selected.prospect.id)

        # Update team need state so later picks by this team reflect the selection
        adjust_team_need_after_pick(team_need, selected.prospect)

        picks.append(
            SimulatedPickRead(
                pick=draft_pick.pick_no,
                team=draft_pick.team,
                original_team=draft_pick.original_team,
                draft_order_note=draft_pick.notes,
                selected_player=to_ranked_read(selected),
                alternatives=[to_ranked_read(ranking) for ranking in alternatives],
                candidate_board=[to_ranked_read(ranking) for ranking in rankings[:5]],
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
            "Team needs are updated after the pick for later selections.",
        ]
    )
    return log
