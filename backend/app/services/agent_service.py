from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.prospect import Prospect
from app.schemas.agent import AgentAskRequest, AgentAskResponse
from app.schemas.recommendation import RecommendRequest
from app.services.llm_service import LLMService
from app.services.rag_service import build_prospect_context_block
from app.services.recommendation_service import build_recommendation


class AgentService:
    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service or LLMService()

    def ask(self, db: Session, request: AgentAskRequest) -> AgentAskResponse:
        recommendation_request = RecommendRequest(
            year=request.year,
            team_id=request.team_id,
            team=request.team,
            pick=request.pick,
            mode=request.mode,
        )
        recommendation = build_recommendation(db=db, request=recommendation_request)

        # Re-fetch the recommended prospect with scouting_reports eager-loaded so
        # the RAG helper can read them in a single round-trip.
        prospect = db.scalar(
            select(Prospect)
            .where(Prospect.id == recommendation.recommended_player.prospect.id)
            .options(selectinload(Prospect.scouting_reports))
        )
        rag_context = ""
        if prospect is not None:
            rag_context = build_prospect_context_block(
                db,
                prospect=prospect,
                team_abbr=recommendation.team.abbr,
            )

        explanation = self.llm_service.explain_recommendation(
            recommendation=recommendation,
            question=request.question,
            rag_context=rag_context,
        )

        return AgentAskResponse(
            recommendation=recommendation,
            explanation=explanation,
            provider=self.llm_service.provider,
            model=self.llm_service.model,
            is_mock=self.llm_service.is_mock,
            rag_context=rag_context,
        )
