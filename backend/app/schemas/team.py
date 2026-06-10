from pydantic import BaseModel, ConfigDict


class TeamNeedRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    year: int
    need_pg: int
    need_sg: int
    need_sf: int
    need_pf: int
    need_c: int
    need_shooting: int
    need_defense: int
    need_creation: int


class TeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    abbr: str
    nba_team_id: int | None = None
    city: str | None = None
    conference: str
    division: str


class TeamDetailRead(TeamRead):
    needs: list[TeamNeedRead] = []


class RosterPlayerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    season: str
    nba_player_id: int | None = None
    player_name: str
    position: str | None = None
    age: float | None = None
    height: str | None = None
    weight: int | None = None
    jersey: str | None = None
    experience: str | None = None
    school: str | None = None


class TeamPickRead(BaseModel):
    """A draft pick owned by a team in a given year.

    `original_team` is the abbreviation of the team that originally held
    the pick before any trades (None for the team's own pick).
    """

    model_config = ConfigDict(from_attributes=True)

    pick_no: int
    original_team: str | None = None
    notes: str | None = None
