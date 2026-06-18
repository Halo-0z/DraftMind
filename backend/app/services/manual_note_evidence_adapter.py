"""RAG-v1-B3: ManualNoteRecord -> EvidenceDocumentRead adapter.

This module is a pure model-to-schema converter that bridges the persistent
:class:`ManualNoteRecord` (DB row) into the unified read-only
:class:`EvidenceDocumentRead` contract.  Once converted, the existing
``evidence_document_mapper`` (B1) can take over and produce
``RetrievedEvidence`` / ``EvidenceCitation`` for the evidence panel.

Design rules (mirrors ``evidence_document_mapper`` and ``manual_note_mapper``):

1. Pure functions only — no DB session, no LLM, no network, no
   ranking_engine / simulation_service / prediction_calibration calls.
2. The adapter only re-shapes data; it never mutates the input record.
3. Output ``evidence_only`` is always ``True`` (Literal-locked by
   ``EvidenceDocumentRead``).
4. If the source ``ManualNoteRecord.evidence_only`` is not ``True``, the
   adapter raises ``ValueError`` — this adapter only handles evidence-only
   rows and must silently refuse to participate in any non-evidence flow.
5. ``excerpt`` prefers ``summary``; falls back to ``body`` (truncated to
   ``MAX_EXCERPT_LENGTH`` chars) when ``summary`` is empty/None.  The
   adapter never returns an empty excerpt.
6. ``tags`` is split from the comma-separated DB string into ``list[str]``,
   with whitespace trimmed and empty entries dropped.

The adapter is intentionally not wired into ``build_pick_evidence`` or any
retrieval service.  Wiring is left to a later milestone (RAG-v1-C / RAG-v1-D).
"""

from __future__ import annotations

from app.models.manual_note import ManualNoteRecord
from app.schemas.evidence import EvidenceDocumentRead

# Truncation guard for body-derived excerpts.  Keeps the evidence panel
# readable without losing the signal in the first paragraph.
MAX_EXCERPT_LENGTH = 1200


def _split_tags(tags: str | None) -> list[str]:
    """Split a comma-separated tag string into a cleaned ``list[str]``.

    ``""`` / ``None`` -> ``[]``.
    ``"shooting,defense"`` -> ``["shooting", "defense"]``.
    ``" shooting , defense "`` -> ``["shooting", "defense"]``.
    """
    if not tags:
        return []
    return [token.strip() for token in tags.split(",") if token.strip()]


def _build_excerpt(summary: str | None, body: str) -> str:
    """Return a non-empty excerpt.

    Prefers ``summary`` when it is a non-empty string; otherwise falls back
    to ``body`` truncated to :data:`MAX_EXCERPT_LENGTH` characters.
    """
    if summary and summary.strip():
        return summary
    if not body:
        # Defensive: ManualNoteRecord.body is NOT NULL, but guard anyway so
        # the adapter never returns an empty excerpt.
        return ""
    if len(body) > MAX_EXCERPT_LENGTH:
        return body[:MAX_EXCERPT_LENGTH]
    return body


def manual_note_record_to_evidence_document(
    record: ManualNoteRecord,
) -> EvidenceDocumentRead:
    """Convert a :class:`ManualNoteRecord` into an :class:`EvidenceDocumentRead`.

    Raises:
        ValueError: if ``record.evidence_only`` is not ``True``.  This
            adapter only handles evidence-only rows.
    """
    if record.evidence_only is not True:
        raise ValueError(
            "ManualNoteRecord.evidence_only must be True to convert to "
            "EvidenceDocumentRead; non-evidence rows are rejected."
        )

    return EvidenceDocumentRead(
        source_type="manual_note",
        source_id=str(record.id),
        entity_type=record.entity_type,
        entity_id=record.entity_id,
        prospect_id=record.prospect_id,
        prospect_name=None,  # not stored on ManualNoteRecord; retrieval layer can enrich
        team_id=record.team_id,
        team_abbr=None,  # not stored on ManualNoteRecord; retrieval layer can enrich
        year=record.year,
        title=record.title,
        excerpt=_build_excerpt(record.summary, record.body),
        url=record.source_url,
        source_name=record.source,
        publisher=None,  # ManualNoteRecord has no publisher column
        author=record.author,
        published_at=record.source_date,
        confidence=record.confidence,
        retrieval_score=None,  # set by the retrieval service, not the adapter
        freshness_days=None,  # set by the retrieval service, not the adapter
        relevance_reason=record.relevance_reason,
        conflict_note=None,  # ManualNoteRecord has no conflict_note column
        tags=_split_tags(record.tags),
        evidence_only=True,
    )
