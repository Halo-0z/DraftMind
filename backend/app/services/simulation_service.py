from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.draft import DraftOrder
from app.models.prospect import Prospect
from app.models.team import TeamNeed
from app.schemas.simulation import (
    LockedPickRequest,
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

        # Rank the live board regardless of whether this is a locked pick.
        # Locked picks still want alternatives + candidate_board populated
        # so the frontend can render a side-by-side comparison.
        rankings = rank_prospects(
            team_need=team_need,
            pick_no=draft_pick.pick_no,
            prospects=available_prospects,
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
            )
            selected_prospect_ids.add(chosen.id)
            adjust_team_need_after_pick(team_need, chosen)

            picks.append(
                SimulatedPickRead(
                    pick=draft_pick.pick_no,
                    team=draft_pick.team,
                    original_team=draft_pick.original_team,
                    draft_order_note=draft_pick.notes,
                    selected_player=to_ranked_read(chosen_ranking),
                    alternatives=[to_ranked_read(r) for r in alternatives],
                    candidate_board=[
                        to_ranked_read(r) for r in override_rankings[:5]
                    ],
                    trade_evaluation=trade_evaluation,
                    decision_log=decision_log,
                )
            )
        else:
            # ---- AUTO PICK BRANCH (v1) ----
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
            adjust_team_need_after_pick(team_need, selected.prospect)

            picks.append(
                SimulatedPickRead(
                    pick=draft_pick.pick_no,
                    team=draft_pick.team,
                    original_team=draft_pick.original_team,
                    draft_order_note=draft_pick.notes,
                    selected_player=to_ranked_read(selected),
                    alternatives=[to_ranked_read(ranking) for ranking in alternatives],
                    candidate_board=[
                        to_ranked_read(ranking) for ranking in rankings[:5]
                    ],
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
    locked: bool = False,
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
    if locked:
        log.append("This pick was locked by user override.")
    log.append("Team needs are updated after the pick for later selections.")
    return log
