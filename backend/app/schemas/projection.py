from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ProjectionSource = Literal[
    "seed_projection",
    "manual_projection",
    "consensus_reference",
]
TeamProjectionType = Literal[
    "consensus_mock",
    "team_report",
    "workout_signal",
    "manual_prediction",
]


class ProspectDraftProjectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    prospect_id: int
    year: int
    consensus_rank: int | None = Field(default=None, ge=1, le=60)
    big_board_rank: int | None = Field(default=None, ge=1, le=60)
    expected_pick: int | None = Field(default=None, ge=1, le=60)
    draft_range_min: int | None = Field(default=None, ge=1, le=60)
    draft_range_max: int | None = Field(default=None, ge=1, le=60)
    tier: int = Field(ge=1, le=10)
    source: ProjectionSource
    source_count: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    last_updated: datetime | None = None
    notes: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProspectDraftProjectionUpsert(BaseModel):
    prospect_id: int
    year: int = Field(ge=2000, le=2100)
    consensus_rank: int | None = Field(default=None, ge=1, le=60)
    big_board_rank: int | None = Field(default=None, ge=1, le=60)
    expected_pick: int | None = Field(default=None, ge=1, le=60)
    draft_range_min: int | None = Field(default=None, ge=1, le=60)
    draft_range_max: int | None = Field(default=None, ge=1, le=60)
    tier: int | None = Field(default=None, ge=1, le=10)
    source: ProjectionSource = "manual_projection"
    source_count: int | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    notes: str | None = None

    @model_validator(mode="after")
    def _range_order(self) -> "ProspectDraftProjectionUpsert":
        if (
            self.draft_range_min is not None
            and self.draft_range_max is not None
            and self.draft_range_min > self.draft_range_max
        ):
            raise ValueError("draft_range_min must be <= draft_range_max")
        return self


class TeamPickProjectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    year: int
    pick_no: int = Field(ge=1, le=60)
    team_id: int
    prospect_id: int
    projection_type: TeamProjectionType
    source: ProjectionSource
    confidence: float = Field(ge=0, le=1)
    notes: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TeamPickProjectionUpsert(BaseModel):
    year: int = Field(ge=2000, le=2100)
    pick_no: int = Field(ge=1, le=60)
    team_id: int
    prospect_id: int
    projection_type: TeamProjectionType = "manual_prediction"
    source: ProjectionSource = "manual_projection"
    confidence: float | None = Field(default=None, ge=0, le=1)
    notes: str | None = None
