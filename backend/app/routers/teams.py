from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.draft import DraftOrder
from app.models.roster import Roster
from app.models.team import Team
from app.schemas.team import RosterPlayerRead, TeamDetailRead, TeamPickRead, TeamRead


router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=list[TeamRead])
def list_teams(db: Session = Depends(get_db)) -> list[Team]:
    return list(db.scalars(select(Team).order_by(Team.name)))


@router.get("/{team_id}", response_model=TeamDetailRead)
def get_team(team_id: int, db: Session = Depends(get_db)) -> Team:
    team = db.scalar(
        select(Team)
        .where(Team.id == team_id)
        .options(selectinload(Team.needs))
    )
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


@router.get("/{team_id}/roster", response_model=list[RosterPlayerRead])
def get_team_roster(
    team_id: int,
    season: str = Query(default="2025-26", min_length=7, max_length=7),
    db: Session = Depends(get_db),
) -> list[Roster]:
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    return list(
        db.scalars(
            select(Roster)
            .where(Roster.team_id == team_id, Roster.season == season)
            .order_by(Roster.player_name)
        )
    )


@router.get("/{team_id}/picks", response_model=list[TeamPickRead])
def get_team_picks(
    team_id: int,
    year: int = Query(default=2026, ge=1947, le=2100),
    db: Session = Depends(get_db),
) -> list[DraftOrder]:
    """Return the picks a team owns in `year`, ordered earliest first.

    Used by the draft page to auto-fill the real pick slot when a GM
    selects their team, and to surface whether a pick originated from
    a trade (e.g. ATL's #8 came from NOP).
    """
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    return list(
        db.scalars(
            select(DraftOrder)
            .where(DraftOrder.team_id == team_id, DraftOrder.year == year)
            .order_by(DraftOrder.pick_no)
        )
    )
