from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.simulation import SimulateRequest, SimulateResponse
from app.services.simulation_service import simulate_draft


router = APIRouter(tags=["simulations"])


@router.post("/simulate", response_model=SimulateResponse)
def simulate(
    request: SimulateRequest,
    db: Session = Depends(get_db),
) -> SimulateResponse:
    return simulate_draft(db=db, request=request)
