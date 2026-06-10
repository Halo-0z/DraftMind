from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.agent import AgentAskRequest, AgentAskResponse
from app.services.agent_service import AgentService


router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/ask", response_model=AgentAskResponse)
def ask_agent(
    request: AgentAskRequest,
    db: Session = Depends(get_db),
) -> AgentAskResponse:
    return AgentService().ask(db=db, request=request)
