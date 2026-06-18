"""RAG-v1-C1: ManualNote field-level retrieval service.

This module provides a read-only retrieval function that queries the
``manual_notes`` table by structured fields (year / prospect_id / team_id /
pick_no / entity_type) and returns ``EvidenceDocumentRead`` instances via
the B3 adapter.  The output is ready to be fed into the B1 mapper
(``evidence_document_mapper``) to produce ``RetrievedEvidence`` /
``EvidenceCitation`` for the evidence panel.

Safety boundary:

1. **Read-only**: the service only issues ``SELECT`` queries.  It never
   ``INSERT`` / ``UPDATE`` / ``DELETE`` / ``commit`` / ``flush``.  The
   caller's session transaction state is never mutated.
2. **Evidence-only**: the base filter always includes
   ``ManualNoteRecord.evidence_only == True``.  Non-evidence rows are
   invisible to this service.
3. **No selection system**: the service does not import or call
   ``ranking_engine`` / ``simulation_service`` / ``prediction_calibration``.
   It does not modify ``selected_player`` / ``final_score`` /
   ``prediction_sort_score``.
4. **No LLM**: the service does not call any LLM provider.
5. **No retrieval metadata fabrication**: ``retrieval_score`` and
   ``freshness_days`` are left as ``None`` on the output documents; a
   future scoring/relevance layer may populate them.

The service is intentionally not wired into ``build_pick_evidence``.  Wiring
is left to a later milestone (RAG-v1-D).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.manual_note import ManualNoteRecord
from app.schemas.evidence import EvidenceDocumentRead
from app.services.manual_note_evidence_adapter import (
    manual_note_record_to_evidence_document,
)

# Clamp bounds for the ``limit`` parameter.
MIN_LIMIT = 1
MAX_LIMIT = 50
DEFAULT_LIMIT = 10


def _clamp_limit(limit: int) -> int:
    """Clamp ``limit`` to ``[MIN_LIMIT, MAX_LIMIT]``."""
    if limit < MIN_LIMIT:
        return MIN_LIMIT
    if limit > MAX_LIMIT:
        return MAX_LIMIT
    return limit


def retrieve_manual_note_documents(
    db: Session,
    *,
    year: int,
    prospect_id: int | None = None,
    team_id: int | None = None,
    pick_no: int | None = None,
    entity_type: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[EvidenceDocumentRead]:
    """Retrieve manual-note knowledge source documents as ``EvidenceDocumentRead``.

    Parameters:
        db: SQLAlchemy session (read-only — never committed/flushed).
        year: Required. Filters ``ManualNoteRecord.year == year``.
        prospect_id: Optional. Filters ``ManualNoteRecord.prospect_id``.
        team_id: Optional. Filters ``ManualNoteRecord.team_id``.
        pick_no: Optional. Filters ``ManualNoteRecord.pick_no``.
        entity_type: Optional. Filters ``ManualNoteRecord.entity_type``.
        limit: Max number of results. Clamped to ``[1, 50]``. Default ``10``.

    Returns:
        ``list[EvidenceDocumentRead]`` sorted by ``updated_at`` desc,
        then ``created_at`` desc, then ``id`` desc.  Empty list if no
        rows match.
    """
    clamped_limit = _clamp_limit(limit)

    stmt = (
        select(ManualNoteRecord)
        .where(
            ManualNoteRecord.year == year,
            ManualNoteRecord.evidence_only.is_(True),
        )
        .order_by(
            ManualNoteRecord.updated_at.desc(),
            ManualNoteRecord.created_at.desc(),
            ManualNoteRecord.id.desc(),
        )
        .limit(clamped_limit)
    )

    if prospect_id is not None:
        stmt = stmt.where(ManualNoteRecord.prospect_id == prospect_id)
    if team_id is not None:
        stmt = stmt.where(ManualNoteRecord.team_id == team_id)
    if pick_no is not None:
        stmt = stmt.where(ManualNoteRecord.pick_no == pick_no)
    if entity_type is not None:
        stmt = stmt.where(ManualNoteRecord.entity_type == entity_type)

    result = db.execute(stmt)
    records = result.scalars().all()

    return [
        manual_note_record_to_evidence_document(record) for record in records
    ]
