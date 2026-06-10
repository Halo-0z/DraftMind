from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.recommendation import RecommendRequest, RecommendResponse
from app.services.recommendation_service import build_recommendation


router = APIRouter(tags=["recommendations"])


@router.post("/recommend", response_model=RecommendResponse)
def recommend_pick(
    request: RecommendRequest,
    db: Session = Depends(get_db),
) -> RecommendResponse:
    return build_recommendation(db=db, request=request)
