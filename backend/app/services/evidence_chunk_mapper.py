"""RAG-v2-M1-B: EvidenceChunk -> EvidenceDocumentRead mapper.

This module is a pure schema-to-schema converter, parallel to
``manual_note_evidence_adapter.py``.  It converts an
:class:`EvidenceChunk` (the RAG-v2 semantic retrieval unit) into an
:class:`EvidenceDocumentRead` so that chunks can flow through the existing
``map_evidence_document`` pipeline without any changes to
``evidence_document_mapper.py`` or ``evidence_service.py``.

Design rules (mirrors ``evidence_document_mapper``):

1. Pure functions only — no DB, no LLM, no network, no ranking_engine /
   simulation_service / prediction_calibration calls.
2. The mapper only re-shapes data; it never mutates the input chunk.
3. Output ``evidence_only`` is always ``True`` (Literal-locked by the
   destination schema).
4. No dangerous override / rerank / replacement field is ever emitted.
5. If ``chunk.excerpt`` is ``None``, an excerpt is generated from
   ``chunk.content`` and truncated to ``EXCERPT_MAX_CHARS`` (1200 chars).
6. ``published_at`` (datetime) is converted to ISO 8601 string to match
   ``EvidenceDocumentRead.published_at: str | None``.
7. ``tags`` is copied (``list(chunk.tags)``) so the mapper never shares a
   mutable list reference with the input chunk.

The mapper is intentionally not wired into ``build_pick_evidence``.  Wiring
is left to a later milestone (RAG-v2-M2 / M3).
"""

from __future__ import annotations

from datetime import datetime

from app.schemas.evidence import EvidenceChunk, EvidenceDocumentRead

# Maximum character length for auto-generated excerpts.  When a chunk has no
# explicit ``excerpt``, the mapper derives one from ``content`` and truncates
# to this limit so downstream LLM payloads stay bounded.
EXCERPT_MAX_CHARS: int = 1200


def _generate_excerpt_from_content(content: str) -> str:
    """Truncate ``content`` to ``EXCERPT_MAX_CHARS`` for use as an excerpt.

    Short content is returned verbatim.  Long content is cut to the limit and
    suffixed with ``"..."`` so consumers can tell the text was truncated.
    """
    if len(content) <= EXCERPT_MAX_CHARS:
        return content
    return content[: EXCERPT_MAX_CHARS - 3] + "..."


def _datetime_to_str(dt: datetime | None) -> str | None:
    """Convert a ``datetime`` to ISO 8601 string, or ``None`` if input is ``None``."""
    if dt is None:
        return None
    return dt.isoformat()


def evidence_chunk_to_document(chunk: EvidenceChunk) -> EvidenceDocumentRead:
    """Convert an :class:`EvidenceChunk` into an :class:`EvidenceDocumentRead`.

    Mapping rules:

    - ``source_type`` → ``source_type`` (unchanged)
    - ``chunk_id`` → ``source_id`` (the chunk's global ID becomes the doc ID)
    - ``entity_type`` / ``entity_id`` / ``prospect_id`` / ``prospect_name`` /
      ``team_id`` / ``team_abbr`` / ``year`` → corresponding fields
    - ``title`` → ``title``
    - ``excerpt``: if the chunk has an explicit excerpt, use it; otherwise
      generate one from ``content`` (truncated to ``EXCERPT_MAX_CHARS``)
    - ``url`` / ``source_name`` / ``publisher`` / ``author`` → corresponding
      fields
    - ``published_at`` (datetime) → ``published_at`` (ISO 8601 string)
    - ``confidence`` / ``retrieval_score`` / ``relevance_reason`` /
      ``conflict_note`` → corresponding fields
    - ``tags`` → copied list (never shares mutable reference with input)
    - ``evidence_only`` → always ``True`` (Literal-locked)

    This function does NOT mutate the original chunk.  It does NOT query the
    DB, call the LLM, or invoke ranking_engine / simulation_service /
    prediction_calibration.
    """
    excerpt = chunk.excerpt
    if excerpt is None:
        excerpt = _generate_excerpt_from_content(chunk.content)

    return EvidenceDocumentRead(
        source_type=chunk.source_type,
        source_id=chunk.chunk_id,
        entity_type=chunk.entity_type,
        entity_id=chunk.entity_id,
        prospect_id=chunk.prospect_id,
        prospect_name=chunk.prospect_name,
        team_id=chunk.team_id,
        team_abbr=chunk.team_abbr,
        year=chunk.year,
        title=chunk.title,
        excerpt=excerpt,
        url=chunk.url,
        source_name=chunk.source_name,
        publisher=chunk.publisher,
        author=chunk.author,
        published_at=_datetime_to_str(chunk.published_at),
        confidence=chunk.confidence,
        retrieval_score=chunk.retrieval_score,
        relevance_reason=chunk.relevance_reason,
        conflict_note=chunk.conflict_note,
        tags=list(chunk.tags),
        evidence_only=True,
    )
