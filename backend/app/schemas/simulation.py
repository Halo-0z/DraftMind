from pydantic import BaseModel, Field

from app.schemas.recommendation import RankedProspectRead
from app.schemas.team import TeamRead


class LockedPickRequest(BaseModel):
    """User override for a specific pick.

    Either `prospect_id` or `prospect_name` must be provided. Validation of
    the chosen identifier (year match, duplicates, ambiguous names) is
    intentionally performed in the service layer so that the API can return
    HTTP 400 with a structured detail instead of Pydantic's default 422.
    """

    pick_no: int = Field(ge=1, le=60)
    prospect_id: int | None = None
    prospect_name: str | None = None


class SimulateRequest(BaseModel):
    year: int = Field(default=2026, ge=2000, le=2100)
    rounds: int = Field(default=1, ge=1, le=2)
    limit: int = Field(default=60, ge=1, le=60)
    evaluate_trades: bool = True
    include_scouting_diagnostics: bool = False
    use_scouting_tiebreaker: bool = False
    include_projection_diagnostics: bool = False
    include_prediction_shadow: bool = False
    use_prediction_calibration: bool = False
    locked_picks: list[LockedPickRequest] | None = None


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
