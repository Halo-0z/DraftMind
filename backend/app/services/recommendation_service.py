from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.draft import DraftOrder
from app.models.prospect import Prospect
from app.models.team import Team, TeamNeed
from app.schemas.recommendation import (
    RankedProspectRead,
    RecommendRequest,
    RecommendResponse,
    ScoreBreakdown,
)
from app.services.ranking_engine import ProspectRanking, rank_prospects
from app.services.team_need_adjustment import (
    TeamNeedSnapshot,
    adjust_team_need_after_pick,
)
from app.services.team_need_service import get_or_infer_team_need


def _snapshot_from_orm(orm: TeamNeed) -> TeamNeedSnapshot:
    """In-memory copy of a ``TeamNeed`` ORM row.

    Mirrors ``simulation_service._snapshot_from_orm`` so the board-aware
    helper stays DB-pollution-free (Phase 6B-M1 contract): we only
    ever read ``TeamNeed`` from the DB once per (year, team) and
    subsequent state changes are written to the in-memory snapshot
    via ``adjust_team_need_after_pick``.
    """
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


def _compute_available_prospects_for_pick(
    db: Session,
    year: int,
    pick_no: int,
) -> list[Prospect]:
    """Return the prospects still on the draft board by ``pick_no``.

    Phase 6B-M1: walk every prior draft pick (``1..pick_no - 1``) for
    the same year, run ``rank_prospects`` against the *dynamic*
    in-memory team-need state, and consume the top-ranked prospect
    for that pick.  This mirrors the deterministic board semantics
    of ``simulation_service.simulate_draft`` (no locked picks, no
    market context, no trade evaluation — those are decoration
    specific to the full simulation endpoint and intentionally
    omitted here).

    Returns the prospects NOT taken in that walk, preserving the
    order of the input prospect list.

    Behavior contract (Phase 6B-M1 §7.4-equivalent guarantees):
      - Never touches ``ranking_engine.py`` (formula is unchanged).
      - Never writes back to ORM ``TeamNeed`` rows — uses
        ``TeamNeedSnapshot`` + ``adjust_team_need_after_pick``,
        same as ``simulate_draft``.
      - Does NOT call ``evaluate_trade_market``.
      - Does NOT load news / market context.
      - ``build_recommendation`` calls ``rank_prospects`` *once*
        on the returned available list, with the user's team_need
        for the requested pick.
    """
    earlier_picks = list(
        db.scalars(
            select(DraftOrder)
            .where(
                DraftOrder.year == year,
                DraftOrder.pick_no < pick_no,
            )
            .options(selectinload(DraftOrder.team))
            .order_by(DraftOrder.pick_no)
        )
    )

    all_prospects = list(
        db.scalars(
            select(Prospect)
            .where(Prospect.year == year)
            .order_by(Prospect.upside_score.desc())
        )
    )

    selected_prospect_ids: set[int] = set()
    # Dynamic in-memory team-need state, same contract as
    # simulate_draft's ``team_need_state``.  We never write back
    # to the ORM ``TeamNeed`` rows.
    team_need_state: dict[int, TeamNeedSnapshot] = {}

    for draft_pick in earlier_picks:
        if draft_pick.team_id not in team_need_state:
            orm_need = get_or_infer_team_need(
                db=db,
                team_id=draft_pick.team_id,
                year=year,
            )
            team_need_state[draft_pick.team_id] = _snapshot_from_orm(orm_need)

        team_need = team_need_state[draft_pick.team_id]
        available = [
            prospect for prospect in all_prospects
            if prospect.id not in selected_prospect_ids
        ]
        if not available:
            break

        rankings = rank_prospects(
            team_need=team_need,
            pick_no=draft_pick.pick_no,
            prospects=available,
        )
        top_prospect = rankings[0].prospect
        selected_prospect_ids.add(top_prospect.id)
        adjust_team_need_after_pick(team_need, top_prospect)

    return [
        prospect for prospect in all_prospects
        if prospect.id not in selected_prospect_ids
    ]


def build_recommendation(
    db: Session,
    request: RecommendRequest,
) -> RecommendResponse:
    team = resolve_team(db, request)
    team_need = get_or_infer_team_need(db=db, team_id=team.id, year=request.year)

    # Phase 6B-M1: walk the prior draft picks to derive an
    # *available board* (no locked picks, no market context, no
    # trade evaluation).  The user's own ``team_need`` is only
    # used to rank the FINAL pick's available board.
    prospects = _compute_available_prospects_for_pick(
        db=db, year=request.year, pick_no=request.pick,
    )
    if not prospects:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No available prospects for pick #{request.pick} of {request.year}"
            ),
        )

    rankings = rank_prospects(
        team_need=team_need,
        pick_no=request.pick,
        prospects=prospects,
    )
    recommended, alternatives = rankings[0], rankings[1:4]

    return RecommendResponse(
        year=request.year,
        pick=request.pick,
        mode=request.mode,
        team=team,
        recommended_player=to_ranked_read(recommended),
        alternatives=[to_ranked_read(ranking) for ranking in alternatives],
    )


def resolve_team(db: Session, request: RecommendRequest) -> Team:
    if request.team_id is not None:
        team = db.get(Team, request.team_id)
    elif request.team:
        normalized_team = request.team.strip().lower()
        team = db.scalar(
            select(Team).where(
                or_(
                    func.lower(Team.abbr) == normalized_team,
                    func.lower(Team.name) == normalized_team,
                )
            )
        )
    else:
        raise HTTPException(status_code=422, detail="team_id or team is required")

    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def to_ranked_read(ranking: ProspectRanking) -> RankedProspectRead:
    return RankedProspectRead(
        prospect=ranking.prospect,
        scores=ScoreBreakdown(
            talent_score=ranking.talent_score,
            fit_score=ranking.fit_score,
            pick_value_score=ranking.pick_value_score,
            risk_penalty=ranking.risk_penalty,
            final_score=ranking.final_score,
        ),
        reasons=ranking.reasons,
        risks=ranking.risks,
    )
