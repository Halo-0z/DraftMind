from fastapi import APIRouter

from app.schemas.evidence import PickEvidencePackage, PickEvidenceRequest
from app.services.evidence_service import build_pick_evidence


router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.post("/pick", response_model=PickEvidencePackage)
def build_pick_evidence_api(request: PickEvidenceRequest) -> PickEvidencePackage:
    return build_pick_evidence(
        request.simulation,
        request.pick,
        manual_notes=request.manual_notes,
    )
