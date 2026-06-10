from pydantic import BaseModel, Field

from app.schemas.prospect import ProspectRead
from app.schemas.team import TeamRead


class RecommendRequest(BaseModel):
    year: int = Field(default=2026, ge=2000, le=2100)
    team_id: int | None = Field(default=None, ge=1)
    team: str | None = Field(
        default=None,
        description="Team id, abbreviation, or full name. team_id wins if both are set.",
    )
    pick: int = Field(ge=1, le=60)
    mode: str = "gm_decision"


class ScoreBreakdown(BaseModel):
    talent_score: float
    fit_score: float
    pick_value_score: float
    risk_penalty: float
    final_score: float


class RankedProspectRead(BaseModel):
    prospect: ProspectRead
    scores: ScoreBreakdown
    reasons: list[str]
    risks: list[str]


class RecommendResponse(BaseModel):
    year: int
    pick: int
    mode: str
    team: TeamRead
    recommended_player: RankedProspectRead
    alternatives: list[RankedProspectRead]
