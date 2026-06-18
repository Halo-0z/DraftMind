"""RAG-v2-M1-D: ManualNoteRecord -> EvidenceChunk adapter.

This module is a pure model-to-schema converter that bridges the persistent
:class:`ManualNoteRecord` (DB row) into the RAG-v2 :class:`EvidenceChunk`
contract.  Once converted, the existing ``evidence_chunk_mapper`` (M1-B) can
take over and produce an ``EvidenceDocumentRead``, which then flows through
``map_evidence_document`` to produce ``RetrievedEvidence`` /
``EvidenceCitation``.

Design rules (mirrors ``manual_note_evidence_adapter`` and
``evidence_chunk_mapper``):

1. Pure functions only — no DB session, no LLM, no network, no
   ranking_engine / simulation_service / prediction_calibration /
   recommendation_service calls.
2. The adapter only re-shapes data; it never mutates the input record.
3. Output ``evidence_only`` is always ``True`` (Literal-locked by
   ``EvidenceChunk``).
4. If the source ``ManualNoteRecord.evidence_only`` is not ``True``, the
   adapter raises ``ValueError`` — this adapter only handles evidence-only
   rows.
5. ``content`` is set to ``record.body`` (NOT NULL column, always present).
6. ``excerpt`` prefers ``record.summary``; if summary is empty/None, excerpt
   is left as ``None`` so the downstream ``evidence_chunk_mapper`` can
   generate one from ``content`` (truncated to ``EXCERPT_MAX_CHARS``).
7. ``tags`` is split from the comma-separated DB string into ``list[str]``,
   with whitespace trimmed and empty entries dropped.
8. ``retrieval_score`` is never set — it is left as ``None``; only a
   retrieval service may populate it.
9. ``published_at`` uses ``record.updated_at`` (falling back to
   ``record.created_at``) as a ``datetime``.  ``record.source_date`` is a
   plain string and is not used here; it remains available on the
   ``EvidenceDocumentRead`` layer via the existing
   ``manual_note_evidence_adapter``.

The adapter is intentionally not wired into ``build_pick_evidence`` or any
retrieval service.  Wiring is left to a later milestone (RAG-v2-M2 / M3).
"""

from __future__ import annotations

from datetime import datetime

from app.models.manual_note import ManualNoteRecord
from app.schemas.evidence import EvidenceChunk


def _split_tags(tags: str | None) -> list[str]:
    """Split a comma-separated tag string into a cleaned ``list[str]``.

    ``""`` / ``None`` -> ``[]``.
    ``"shooting,defense"`` -> ``["shooting", "defense"]``.
    ``" shooting , defense "`` -> ``["shooting", "defense"]``.
    """
    if not tags:
        return []
    return [token.strip() for token in tags.split(",") if token.strip()]


def _pick_published_at(record: ManualNoteRecord) -> datetime | None:
    """Return ``updated_at`` if set, otherwise ``created_at``.

    Both columns have DB defaults but may be ``None`` on unpersisted
    instances constructed in tests.
    """
    if record.updated_at is not None:
        return record.updated_at
    return record.created_at


def _build_excerpt(summary: str | None) -> str | None:
    """Return ``summary`` if it is a non-empty string, otherwise ``None``.

    When ``None`` is returned, the downstream ``evidence_chunk_mapper`` will
    generate an excerpt from ``content`` (truncated to
    ``EXCERPT_MAX_CHARS``).
    """
    if summary and summary.strip():
        return summary
    return None


def manual_note_record_to_evidence_chunk(
    note: ManualNoteRecord,
) -> EvidenceChunk:
    """Convert a :class:`ManualNoteRecord` into an :class:`EvidenceChunk`.

    Raises:
        ValueError: if ``note.evidence_only`` is not ``True``.  This
            adapter only handles evidence-only rows.
    """
    if note.evidence_only is not True:
        raise ValueError(
            "ManualNoteRecord.evidence_only must be True to convert to "
            "EvidenceChunk; non-evidence rows are rejected."
        )

    return EvidenceChunk(
        chunk_id=f"manual_note:{note.id}:0",
        source_type="manual_note",
        source_id=str(note.id),
        chunk_index=0,
        chunk_count=1,
        title=note.title,
        content=note.body,
        excerpt=_build_excerpt(note.summary),
        entity_type=note.entity_type,
        entity_id=note.entity_id,
        prospect_id=note.prospect_id,
        prospect_name=None,  # not stored on ManualNoteRecord
        team_id=note.team_id,
        team_abbr=None,  # not stored on ManualNoteRecord
        pick_no=note.pick_no,
        year=note.year,
        url=note.source_url,
        source_name=note.source,
        publisher=None,  # ManualNoteRecord has no publisher column
        author=note.author,
        published_at=_pick_published_at(note),
        confidence=note.confidence,
        retrieval_score=None,  # set by the retrieval service, not the adapter
        relevance_reason=note.relevance_reason,
        conflict_note=None,  # ManualNoteRecord has no conflict_note column
        tags=_split_tags(note.tags),
        evidence_only=True,
    )
