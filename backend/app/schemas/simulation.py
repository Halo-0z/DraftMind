from pydantic import BaseModel, Field

from app.schemas.recommendation import RankedProspectRead
from app.schemas.team import TeamRead


class SimulateRequest(BaseModel):
    year: int = Field(default=2026, ge=2000, le=2100)
    rounds: int = Field(default=1, ge=1, le=2)
    limit: int = Field(default=60, ge=1, le=60)
    evaluate_trades: bool = True


class TradeEvaluation(BaseModel):
    action: str
    probability: float
    rationale: str
    executed: bool = False


class SimulatedPickRead(BaseModel):
    pick: int
    team: TeamRead
    original_team: str | None = None
    draft_order_note: str | None = None
    selected_player: RankedProspectRead
    alternatives: list[RankedProspectRead]
    candidate_board: list[RankedProspectRead]
    trade_evaluation: TradeEvaluation
    decision_log: list[str]


class SimulateResponse(BaseModel):
    year: int
    rounds: int
    total_picks: int
    source: str | None = None
    picks: list[SimulatedPickRead]
