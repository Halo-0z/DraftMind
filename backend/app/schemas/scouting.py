from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ProfileSource = Literal[
    "manual",
    "seed",
    "api_inferred",
    "scouting_inferred",
    "news_display_only",
]
NeedHorizon = Literal["now", "next_season", "two_year"]
TeamTimeline = Literal["contend", "retool", "rebuild", "unknown"]


class TeamNeedProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    team_id: int
    year: int

    need_guard_depth: int = Field(ge=1, le=10)
    need_wing_depth: int = Field(ge=1, le=10)
    need_big_depth: int = Field(ge=1, le=10)
    need_center: int = Field(ge=1, le=10)
    need_size: int = Field(ge=1, le=10)
    need_youth: int = Field(ge=1, le=10)
    need_nba_ready: int = Field(ge=1, le=10)
    need_upside: int = Field(ge=1, le=10)

    need_spacing: int = Field(ge=1, le=10)
    need_shooting_volume: int = Field(ge=1, le=10)
    need_movement_shooting: int = Field(ge=1, le=10)
    need_self_creation: int = Field(ge=1, le=10)
    need_secondary_creation: int = Field(ge=1, le=10)
    need_playmaking: int = Field(ge=1, le=10)
    need_rim_pressure: int = Field(ge=1, le=10)
    need_finishing: int = Field(ge=1, le=10)

    need_rim_protection: int = Field(ge=1, le=10)
    need_defensive_rebounding: int = Field(ge=1, le=10)
    need_offensive_rebounding: int = Field(ge=1, le=10)
    need_point_of_attack_defense: int = Field(ge=1, le=10)
    need_switchability: int = Field(ge=1, le=10)
    need_team_defense: int = Field(ge=1, le=10)
    need_foul_discipline: int = Field(ge=1, le=10)
    need_physicality: int = Field(ge=1, le=10)

    team_timeline: TeamTimeline
    core_age_curve: float | None = None
    contract_pressure: int = Field(ge=1, le=10)
    pending_free_agents: str
    development_bandwidth: int = Field(ge=1, le=10)
    scheme_tags: str

    source: ProfileSource
    horizon: NeedHorizon
    need_confidence: float = Field(ge=0, le=1)
    manual_override_reason: str | None = None


class TeamNeedProfileUpsert(BaseModel):
    team_id: int
    year: int = Field(ge=2000, le=2100)
    horizon: NeedHorizon = "next_season"

    need_guard_depth: int | None = Field(default=None, ge=1, le=10)
    need_wing_depth: int | None = Field(default=None, ge=1, le=10)
    need_big_depth: int | None = Field(default=None, ge=1, le=10)
    need_center: int | None = Field(default=None, ge=1, le=10)
    need_size: int | None = Field(default=None, ge=1, le=10)
    need_youth: int | None = Field(default=None, ge=1, le=10)
    need_nba_ready: int | None = Field(default=None, ge=1, le=10)
    need_upside: int | None = Field(default=None, ge=1, le=10)

    need_spacing: int | None = Field(default=None, ge=1, le=10)
    need_shooting_volume: int | None = Field(default=None, ge=1, le=10)
    need_movement_shooting: int | None = Field(default=None, ge=1, le=10)
    need_self_creation: int | None = Field(default=None, ge=1, le=10)
    need_secondary_creation: int | None = Field(default=None, ge=1, le=10)
    need_playmaking: int | None = Field(default=None, ge=1, le=10)
    need_rim_pressure: int | None = Field(default=None, ge=1, le=10)
    need_finishing: int | None = Field(default=None, ge=1, le=10)

    need_rim_protection: int | None = Field(default=None, ge=1, le=10)
    need_defensive_rebounding: int | None = Field(default=None, ge=1, le=10)
    need_offensive_rebounding: int | None = Field(default=None, ge=1, le=10)
    need_point_of_attack_defense: int | None = Field(default=None, ge=1, le=10)
    need_switchability: int | None = Field(default=None, ge=1, le=10)
    need_team_defense: int | None = Field(default=None, ge=1, le=10)
    need_foul_discipline: int | None = Field(default=None, ge=1, le=10)
    need_physicality: int | None = Field(default=None, ge=1, le=10)

    team_timeline: TeamTimeline | None = None
    core_age_curve: float | None = None
    contract_pressure: int | None = Field(default=None, ge=1, le=10)
    pending_free_agents: str | None = None
    development_bandwidth: int | None = Field(default=None, ge=1, le=10)
    scheme_tags: str | None = None

    source: Literal["manual"] | None = None
    need_confidence: float | None = Field(default=None, ge=0, le=1)
    manual_override_reason: str | None = None


class ProspectScoutingProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    prospect_id: int
    year: int

    shooting_volume: int = Field(ge=1, le=10)
    shooting_versatility: int = Field(ge=1, le=10)
    spacing_value: int = Field(ge=1, le=10)
    rim_pressure: int = Field(ge=1, le=10)
    self_creation: int = Field(ge=1, le=10)
    secondary_creation: int = Field(ge=1, le=10)
    passing_feel: int = Field(ge=1, le=10)
    finishing: int = Field(ge=1, le=10)

    rim_protection: int = Field(ge=1, le=10)
    defensive_rebounding: int = Field(ge=1, le=10)
    offensive_rebounding: int = Field(ge=1, le=10)
    point_of_attack_defense: int = Field(ge=1, le=10)
    switchability: int = Field(ge=1, le=10)
    team_defense: int = Field(ge=1, le=10)
    foul_discipline: int = Field(ge=1, le=10)
    physicality: int = Field(ge=1, le=10)

    height: str | None = None
    wingspan: str | None = None
    age: float | None = None
    nba_readiness: int = Field(ge=1, le=10)
    upside: int = Field(ge=1, le=10)
    medical_risk: int = Field(ge=1, le=10)
    role_projection: str
    scheme_fit_tags: str

    source: ProfileSource
    profile_confidence: float = Field(ge=0, le=1)
    manual_override_reason: str | None = None


class ProspectScoutingProfileUpsert(BaseModel):
    prospect_id: int
    year: int = Field(ge=2000, le=2100)

    shooting_volume: int | None = Field(default=None, ge=1, le=10)
    shooting_versatility: int | None = Field(default=None, ge=1, le=10)
    spacing_value: int | None = Field(default=None, ge=1, le=10)
    rim_pressure: int | None = Field(default=None, ge=1, le=10)
    self_creation: int | None = Field(default=None, ge=1, le=10)
    secondary_creation: int | None = Field(default=None, ge=1, le=10)
    passing_feel: int | None = Field(default=None, ge=1, le=10)
    finishing: int | None = Field(default=None, ge=1, le=10)

    rim_protection: int | None = Field(default=None, ge=1, le=10)
    defensive_rebounding: int | None = Field(default=None, ge=1, le=10)
    offensive_rebounding: int | None = Field(default=None, ge=1, le=10)
    point_of_attack_defense: int | None = Field(default=None, ge=1, le=10)
    switchability: int | None = Field(default=None, ge=1, le=10)
    team_defense: int | None = Field(default=None, ge=1, le=10)
    foul_discipline: int | None = Field(default=None, ge=1, le=10)
    physicality: int | None = Field(default=None, ge=1, le=10)

    height: str | None = None
    wingspan: str | None = None
    age: float | None = None
    nba_readiness: int | None = Field(default=None, ge=1, le=10)
    upside: int | None = Field(default=None, ge=1, le=10)
    medical_risk: int | None = Field(default=None, ge=1, le=10)
    role_projection: str | None = None
    scheme_fit_tags: str | None = None

    source: Literal["manual"] | None = None
    profile_confidence: float | None = Field(default=None, ge=0, le=1)
    manual_override_reason: str | None = None
