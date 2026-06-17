from fastapi import APIRouter

from app.config import get_settings
from app.schemas.evidence import (
    PickEvidencePackage,
    PickEvidenceRequest,
    PickExplanation,
)
from app.services.evidence_explanation_service import build_mock_pick_explanation
from app.services.evidence_llm_explanation_service import build_llm_pick_explanation
from app.services.evidence_llm_provider import build_evidence_llm_client
from app.services.evidence_service import build_pick_evidence


router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.post("/pick", response_model=PickEvidencePackage)
def build_pick_evidence_api(request: PickEvidenceRequest) -> PickEvidencePackage:
    return build_pick_evidence(
        request.simulation,
        request.pick,
        manual_notes=request.manual_notes,
    )


@router.post("/pick/explanation", response_model=PickExplanation)
def explain_pick(evidence: PickEvidencePackage) -> PickExplanation:
    """RAG-v0-M3.1-E: Guarded real explanation endpoint.

    Thin wiring only — delegates all safety to the upstream shell:

        PickEvidencePackage
        -> build_evidence_llm_client(settings)
        -> build_llm_pick_explanation(evidence, llm_client=client)
        -> PickExplanation

    When the provider is disabled (default), has no API key, errors, times out,
    or produces invalid/dangerous output, ``build_llm_pick_explanation`` falls
    back to the deterministic mock explanation.  This endpoint does NOT call
    ``build_pick_evidence``, does NOT query the DB, does NOT call
    ranking/prediction/simulation, and does NOT parse LLM JSON or do schema
    validation — all of that lives in the shell and provider adapter.
    """
    settings = get_settings()
    client = build_evidence_llm_client(settings)
    return build_llm_pick_explanation(evidence, llm_client=client)


@router.post("/pick/explanation/mock", response_model=PickExplanation)
def explain_pick_mock(evidence: PickEvidencePackage) -> PickExplanation:
    """RAG-v0-M3.0-C: Deterministic mock explanation endpoint.

    Accepts an already-built ``PickEvidencePackage`` and returns a read-only
    ``PickExplanation``.  This endpoint does NOT call any LLM, does NOT query
    the DB, does NOT call ``ranking_engine`` / ``prediction_calibration`` /
    ``simulation_service``, and does NOT call ``build_pick_evidence`` — it only
    forwards the input to ``build_mock_pick_explanation``.
    """
    return build_mock_pick_explanation(evidence)
