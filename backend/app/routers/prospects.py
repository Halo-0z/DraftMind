from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.prospect import Prospect
from app.schemas.prospect import ProspectRead


router = APIRouter(prefix="/prospects", tags=["prospects"])


@router.get("", response_model=list[ProspectRead])
def list_prospects(
    year: int = Query(default=2026, ge=2000, le=2100),
    db: Session = Depends(get_db),
) -> list[Prospect]:
    return list(
        db.scalars(
            select(Prospect)
            .where(Prospect.year == year)
            .order_by(Prospect.upside_score.desc(), Prospect.name)
        )
    )
