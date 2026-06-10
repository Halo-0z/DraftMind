from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.prospect import Prospect
from app.models.team import Team
from app.schemas.recommendation import (
    RankedProspectRead,
    RecommendRequest,
    RecommendResponse,
    ScoreBreakdown,
)
from app.services.ranking_engine import ProspectRanking, rank_prospects
from app.services.team_need_service import get_or_infer_team_need


def build_recommendation(
    db: Session,
    request: RecommendRequest,
) -> RecommendResponse:
    team = resolve_team(db, request)
    team_need = get_or_infer_team_need(db=db, team_id=team.id, year=request.year)

    prospects = list(
        db.scalars(
            select(Prospect)
            .where(Prospect.year == request.year)
            .order_by(Prospect.upside_score.desc())
        )
    )
    if not prospects:
        raise HTTPException(status_code=404, detail="No prospects found for year")

    rankings = rank_prospects(team_need=team_need, pick_no=request.pick, prospects=prospects)
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
