from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Prospect, ProspectScoutingProfile, Team, TeamNeedProfile
from app.schemas.scouting import (
    NeedHorizon,
    ProspectScoutingProfileRead,
    ProspectScoutingProfileUpsert,
    TeamNeedProfileRead,
    TeamNeedProfileUpsert,
)


router = APIRouter(prefix="/scouting", tags=["scouting"])

_TEAM_PROFILE_KEYS = {"team_id", "year", "horizon", "source", "need_confidence"}
_PROSPECT_PROFILE_KEYS = {"prospect_id", "year", "source", "profile_confidence"}


@router.get("/team-profiles", response_model=TeamNeedProfileRead)
def get_team_profile(
    team_id: int = Query(ge=1),
    year: int = Query(ge=2000, le=2100),
    horizon: NeedHorizon = "next_season",
    db: Session = Depends(get_db),
) -> TeamNeedProfile:
    profile = db.scalar(
        select(TeamNeedProfile).where(
            TeamNeedProfile.team_id == team_id,
            TeamNeedProfile.year == year,
            TeamNeedProfile.horizon == horizon,
        )
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Team scouting profile not found")
    return profile


@router.post("/team-profiles", response_model=TeamNeedProfileRead)
def upsert_team_profile(
    payload: TeamNeedProfileUpsert,
    db: Session = Depends(get_db),
) -> TeamNeedProfile:
    team = db.get(Team, payload.team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    profile = db.scalar(
        select(TeamNeedProfile).where(
            TeamNeedProfile.team_id == payload.team_id,
            TeamNeedProfile.year == payload.year,
            TeamNeedProfile.horizon == payload.horizon,
        )
    )
    if profile is None:
        profile = TeamNeedProfile(
            team_id=payload.team_id,
            year=payload.year,
            horizon=payload.horizon,
        )
        db.add(profile)

    values = payload.model_dump(exclude_unset=True)
    for field, value in values.items():
        if field in _TEAM_PROFILE_KEYS:
            continue
        setattr(profile, field, value)

    profile.source = "manual"
    profile.need_confidence = (
        payload.need_confidence if payload.need_confidence is not None else 1.0
    )
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/prospect-profiles", response_model=ProspectScoutingProfileRead)
def get_prospect_profile(
    prospect_id: int = Query(ge=1),
    year: int = Query(ge=2000, le=2100),
    db: Session = Depends(get_db),
) -> ProspectScoutingProfile:
    profile = db.scalar(
        select(ProspectScoutingProfile).where(
            ProspectScoutingProfile.prospect_id == prospect_id,
            ProspectScoutingProfile.year == year,
        )
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Prospect scouting profile not found")
    return profile


@router.post("/prospect-profiles", response_model=ProspectScoutingProfileRead)
def upsert_prospect_profile(
    payload: ProspectScoutingProfileUpsert,
    db: Session = Depends(get_db),
) -> ProspectScoutingProfile:
    prospect = db.get(Prospect, payload.prospect_id)
    if prospect is None:
        raise HTTPException(status_code=404, detail="Prospect not found")

    profile = db.scalar(
        select(ProspectScoutingProfile).where(
            ProspectScoutingProfile.prospect_id == payload.prospect_id,
            ProspectScoutingProfile.year == payload.year,
        )
    )
    if profile is None:
        profile = ProspectScoutingProfile(
            prospect_id=payload.prospect_id,
            year=payload.year,
        )
        db.add(profile)

    values = payload.model_dump(exclude_unset=True)
    for field, value in values.items():
        if field in _PROSPECT_PROFILE_KEYS:
            continue
        setattr(profile, field, value)

    profile.source = "manual"
    profile.profile_confidence = (
        payload.profile_confidence if payload.profile_confidence is not None else 1.0
    )
    db.commit()
    db.refresh(profile)
    return profile
