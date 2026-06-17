"""ManualNote -> RetrievedEvidence / EvidenceCitation mapper.

This module is a schema-to-schema converter. It does not call the
ranking_engine, does not query the database, does not call any LLM, and does
not touch any vector store. It only re-shapes a :class:`ManualNote` into the
evidence-layer schemas so that future retrieval services can feed manual notes
into ``PickEvidencePackage.retrieved_evidence`` and ``citations``.

The mapper is intentionally not wired into ``build_pick_evidence``. Wiring is
left to a later milestone.
"""

from __future__ import annotations

from app.schemas.evidence import (
    EvidenceCitation,
    ManualNote,
    RetrievedEvidence,
)

MANUAL_NOTE_EVIDENCE_SOURCE_TYPE = "manual_note"


def _excerpt_from_manual_note(note: ManualNote, *, max_length: int = 1000) -> str:
    """Build a short excerpt for evidence payloads.

    Rules:
        1. Prefer ``note.summary`` when present.
        2. Otherwise fall back to ``note.body``.
        3. Truncate to ``max_length`` characters.
        4. Never return an empty string (ManualNote guarantees non-empty body).
    """
    if note.summary:
        base = note.summary
    else:
        base = note.body

    if len(base) > max_length:
        return base[:max_length]
    return base


def _source_id_from_note(note: ManualNote) -> str | None:
    if note.note_id is None:
        return None
    return str(note.note_id)


def manual_note_to_citation(note: ManualNote) -> EvidenceCitation:
    """Convert a :class:`ManualNote` into an :class:`EvidenceCitation`."""
    return EvidenceCitation(
        source_type=note.source,
        source_id=_source_id_from_note(note),
        title=note.title,
        url=note.source_url,
        date=note.source_date,
        excerpt=_excerpt_from_manual_note(note),
        confidence=note.confidence,
        evidence_source_type=MANUAL_NOTE_EVIDENCE_SOURCE_TYPE,
        entity_type=note.entity_type,
        entity_id=note.entity_id,
        author=note.author,
        retrieved_at=None,
        relevance_reason=note.relevance_reason,
        evidence_only=True,
    )


def manual_note_to_retrieved_evidence(note: ManualNote) -> RetrievedEvidence:
    """Convert a :class:`ManualNote` into a :class:`RetrievedEvidence`."""
    return RetrievedEvidence(
        source_type=MANUAL_NOTE_EVIDENCE_SOURCE_TYPE,
        source_id=_source_id_from_note(note),
        citation=manual_note_to_citation(note),
        entity_type=note.entity_type,
        entity_id=note.entity_id,
        title=note.title,
        excerpt=_excerpt_from_manual_note(note),
        url=note.source_url,
        date=note.source_date,
        confidence=note.confidence,
        retrieval_score=None,
        freshness_days=None,
        relevance_reason=note.relevance_reason,
        conflict_note=None,
        evidence_only=True,
    )


def manual_note_to_evidence_pair(
    note: ManualNote,
) -> tuple[RetrievedEvidence, EvidenceCitation]:
    """Convert a :class:`ManualNote` into a (RetrievedEvidence, EvidenceCitation) pair.

    The citation returned is the same object referenced by
    ``RetrievedEvidence.citation``.
    """
    retrieved = manual_note_to_retrieved_evidence(note)
    citation = retrieved.citation
    assert citation is not None  # invariant: mapper always sets citation
    return retrieved, citation
