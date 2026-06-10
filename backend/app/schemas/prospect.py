from pydantic import BaseModel, ConfigDict


class ProspectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    year: int
    name: str
    position: str
    age: float
    height: str
    weight: int
    school_or_league: str
    ppg: float
    rpg: float
    apg: float
    fg_pct: float
    three_pct: float
    ft_pct: float
    stocks: float
    archetype: str
    upside_score: float
    risk_score: float
