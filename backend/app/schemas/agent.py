from pydantic import BaseModel, Field

from app.schemas.recommendation import RecommendRequest, RecommendResponse


class AgentAskRequest(RecommendRequest):
    question: str = Field(
        default="请解释这次选秀推荐。",
        min_length=1,
        max_length=500,
    )


class AgentExplanation(BaseModel):
    recommendation_reasons: list[str]
    risks: list[str]
    alternatives: list[str]
    gm_summary: str
    follow_up_answer: str


class AgentAskResponse(BaseModel):
    recommendation: RecommendResponse
    explanation: AgentExplanation
    provider: str
    model: str
    is_mock: bool
    rag_context: str = ""
