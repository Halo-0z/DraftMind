"""RAG-v1-B1: EvidenceDocumentRead -> RetrievedEvidence / EvidenceCitation mapper.

This module is a pure schema-to-schema converter, parallel to
``manual_note_mapper.py``.  It converts a read-only
:class:`EvidenceDocumentRead` (the unified knowledge source contract) into the
evidence-layer schemas so that future retrieval services can feed knowledge
source rows into ``PickEvidencePackage.retrieved_evidence`` and ``citations``.

Design rules (mirrors ``manual_note_mapper``):

1. Pure functions only — no DB, no LLM, no network, no ranking_engine /
   simulation_service / prediction_calibration calls.
2. The mapper only re-shapes data; it never mutates the input document.
3. Output ``evidence_only`` is always ``True`` (Literal-locked by the
   destination schemas).
4. No dangerous override / rerank / replacement field is ever emitted.
5. The citation returned by ``map_evidence_document`` is the same object
   referenced by ``RetrievedEvidence.citation``.
6. ``retrieved_at`` is always ``None`` — the mapper does not know the
   current time and should not fabricate it.  Callers that need a timestamp
   can set it after mapping.

The mapper is intentionally not wired into ``build_pick_evidence``.  Wiring
is left to a later milestone (RAG-v1-D).
"""

from __future__ import annotations

from app.schemas.evidence import (
    EvidenceCitation,
    EvidenceDocumentRead,
    RetrievedEvidence,
)


def evidence_document_to_citation(
    document: EvidenceDocumentRead,
) -> EvidenceCitation:
    """Convert an :class:`EvidenceDocumentRead` into an :class:`EvidenceCitation`."""
    return EvidenceCitation(
        source_type=document.source_type,
        source_id=document.source_id,
        title=document.title,
        url=document.url,
        date=document.published_at,
        excerpt=document.excerpt,
        confidence=document.confidence,
        evidence_source_type=document.source_type,
        entity_type=document.entity_type,
        entity_id=document.entity_id,
        publisher=document.publisher,
        author=document.author,
        retrieved_at=None,
        freshness_days=document.freshness_days,
        relevance_reason=document.relevance_reason,
        evidence_only=True,
    )


def evidence_document_to_retrieved_evidence(
    document: EvidenceDocumentRead,
) -> RetrievedEvidence:
    """Convert an :class:`EvidenceDocumentRead` into a :class:`RetrievedEvidence`."""
    return RetrievedEvidence(
        source_type=document.source_type,
        source_id=document.source_id,
        citation=evidence_document_to_citation(document),
        entity_type=document.entity_type,
        entity_id=document.entity_id,
        title=document.title,
        excerpt=document.excerpt,
        url=document.url,
        date=document.published_at,
        confidence=document.confidence,
        retrieval_score=document.retrieval_score,
        freshness_days=document.freshness_days,
        relevance_reason=document.relevance_reason,
        conflict_note=document.conflict_note,
        evidence_only=True,
    )


def map_evidence_document(
    document: EvidenceDocumentRead,
) -> tuple[RetrievedEvidence, EvidenceCitation]:
    """Convert an :class:`EvidenceDocumentRead` into a
    ``(RetrievedEvidence, EvidenceCitation)`` pair.

    The citation returned is the same object referenced by
    ``RetrievedEvidence.citation``.
    """
    retrieved = evidence_document_to_retrieved_evidence(document)
    citation = retrieved.citation
    assert citation is not None  # invariant: mapper always sets citation
    return retrieved, citation
