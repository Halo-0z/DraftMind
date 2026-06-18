"""RAG-v2-M2-B: Evidence chunking service.

Splits long text into multiple :class:`EvidenceChunk` objects using
sentence-aware character splitting.  This is the first step of the RAG-v2
semantic retrieval pipeline — it produces the chunks that will later be
embedded and indexed by the vector store (M2-C / M2-D).

Design rules (mirrors ``evidence_chunk_mapper`` and
``manual_note_chunk_adapter``):

1. Pure functions only — no DB session, no LLM, no network, no
   ranking_engine / simulation_service / prediction_calibration /
   recommendation_service calls.
2. The chunker only splits text; it never mutates the input text or tags.
3. Output ``evidence_only`` is always ``True`` (Literal-locked by
   ``EvidenceChunk``).
4. ``retrieval_score`` is never set — it is left as ``None``; only a
   retrieval service may populate it.
5. ``excerpt`` is left as ``None`` — the downstream
   ``evidence_chunk_to_document`` generates excerpts from content.
6. No embedding is generated — that is the job of the embedding service
   (M2-C).
7. ``chunk_id`` follows the stable format ``{source_type}:{source_id}:{chunk_index}``
   so chunks are deterministic, testable, and traceable.

Splitting strategy:

- **Sentence-aware**: text is first split at sentence boundaries
  (Chinese ``。！？``, English ``.!?`` followed by whitespace/end, and
  newlines ``\\n``).
- **Greedy packing**: sentences are greedily packed into chunks until
  ``chunk_size`` is exceeded, then a new chunk starts.
- **Overlap**: the last ``overlap`` characters of the previous chunk are
  prepended to the next chunk to preserve context continuity.
- **Character fallback**: if a single sentence exceeds ``chunk_size``,
  it is split by characters (with overlap) as a fallback.
- **Limits**: at most ``MAX_CHUNKS`` chunks are produced; exceeding this
  raises ``ValueError``.
"""

from __future__ import annotations

import re
from datetime import datetime

from app.schemas.evidence import EvidenceChunk

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default target length (in characters) for each chunk.
DEFAULT_CHUNK_SIZE: int = 600

#: Default overlap (in characters) between adjacent chunks.
DEFAULT_OVERLAP: int = 60

#: Maximum number of chunks produced by a single ``chunk_text`` call.
MAX_CHUNKS: int = 50

# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------

#: Sentence boundary pattern.
#:
#: Matches a single delimiter character:
#: - Chinese sentence endings: ``。`` ``！`` ``？``
#: - Newline: ``\n``
#: - English sentence endings: ``.`` ``!`` ``?`` followed by whitespace
#:   or end-of-string (lookahead, so the whitespace is not consumed).
_SENTENCE_ENDINGS = re.compile(r"([。！？\n]|[.!?](?=\s|$))")


def _split_sentences(text: str) -> list[str]:
    """Split *text* into sentences at Chinese/English boundaries and newlines.

    Each returned sentence includes its trailing delimiter (if any) and is
    stripped of leading/trailing whitespace.  Empty sentences are dropped.

    >>> _split_sentences("Hello world. 中文测试。")
    ['Hello world.', '中文测试。']
    """
    parts = _SENTENCE_ENDINGS.split(text)

    sentences: list[str] = []
    buffer = ""

    for part in parts:
        if part == "":
            continue
        buffer += part
        if _SENTENCE_ENDINGS.fullmatch(part):
            stripped = buffer.strip()
            if stripped:
                sentences.append(stripped)
            buffer = ""

    # Flush any remaining text (no trailing delimiter).
    stripped = buffer.strip()
    if stripped:
        sentences.append(stripped)

    return sentences


# ---------------------------------------------------------------------------
# Character fallback splitting
# ---------------------------------------------------------------------------


def _split_by_chars(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split *text* by characters with overlap (fallback for long sentences).

    Each chunk is at most ``chunk_size`` characters.  Adjacent chunks share
    ``overlap`` characters of context.
    """
    result: list[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end].strip()
        if chunk:
            result.append(chunk)

        if end >= text_len:
            break

        step = chunk_size - overlap
        if step <= 0:
            step = 1  # Safety: guarantee forward progress.
        start += step

    return result


# ---------------------------------------------------------------------------
# Sentence grouping
# ---------------------------------------------------------------------------


def _group_sentences_into_chunks(
    sentences: list[str],
    chunk_size: int,
    overlap: int,
) -> list[str]:
    """Greedily pack *sentences* into text chunks respecting *chunk_size*.

    When a chunk is full, the next chunk starts with the last *overlap*
    characters of the flushed chunk (context continuity).  Sentences
    longer than *chunk_size* are split by characters via
    :func:`_split_by_chars`.
    """
    if not sentences:
        return []

    chunks: list[str] = []
    current: str = ""

    for sentence in sentences:
        # --- Character fallback for over-long sentences -----------------
        if len(sentence) > chunk_size:
            # Flush any pending content first.
            if current.strip():
                chunks.append(current.strip())
                current = ""
            # Split the long sentence by characters.
            chunks.extend(_split_by_chars(sentence, chunk_size, overlap))
            continue

        # --- Greedy packing ----------------------------------------------
        if current:
            candidate = current + " " + sentence
        else:
            candidate = sentence

        if len(candidate) <= chunk_size:
            current = candidate
        else:
            # Current chunk is full — flush it.
            flushed = current.strip()
            if flushed:
                chunks.append(flushed)
            # Start the next chunk with overlap from the flushed chunk.
            if overlap > 0 and len(flushed) >= overlap:
                current = flushed[-overlap:] + " " + sentence
            else:
                current = sentence

    # Flush the last pending chunk.
    if current.strip():
        chunks.append(current.strip())

    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def chunk_text(
    text: str,
    *,
    source_type: str,
    source_id: str,
    title: str | None = None,
    entity_type: str | None = None,
    entity_id: int | str | None = None,
    prospect_id: int | None = None,
    prospect_name: str | None = None,
    team_id: int | None = None,
    team_abbr: str | None = None,
    pick_no: int | None = None,
    year: int | None = None,
    url: str | None = None,
    source_name: str | None = None,
    publisher: str | None = None,
    author: str | None = None,
    published_at: datetime | None = None,
    confidence: float | None = None,
    relevance_reason: str | None = None,
    conflict_note: str | None = None,
    tags: list[str] | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[EvidenceChunk]:
    """Split *text* into a list of :class:`EvidenceChunk` objects.

    The function uses sentence-aware character splitting with configurable
    ``chunk_size`` and ``overlap``.  Each chunk inherits the supplied
    source metadata (``source_type``, ``source_id``, entity fields, etc.).

    Safety guarantees:

    - ``evidence_only`` is always ``True`` (Literal-locked by EvidenceChunk).
    - ``retrieval_score`` is always ``None`` (only retrieval services set it).
    - ``excerpt`` is always ``None`` (downstream mapper generates it).
    - No embedding is generated.
    - No DB / LLM / ranking_engine calls are made.

    Raises:
        ValueError: if *text* is empty or whitespace-only.
        ValueError: if *chunk_size* <= 0.
        ValueError: if *overlap* < 0.
        ValueError: if *overlap* >= *chunk_size*.
        ValueError: if the number of chunks exceeds ``MAX_CHUNKS``.
    """
    # ------------------------------------------------------------------
    # Validate inputs
    # ------------------------------------------------------------------
    if not text or not text.strip():
        raise ValueError(
            "text must not be empty or whitespace-only"
        )
    if chunk_size <= 0:
        raise ValueError(
            f"chunk_size must be positive, got {chunk_size}"
        )
    if overlap < 0:
        raise ValueError(
            f"overlap must not be negative, got {overlap}"
        )
    if overlap >= chunk_size:
        raise ValueError(
            f"overlap ({overlap}) must be less than chunk_size ({chunk_size})"
        )

    # ------------------------------------------------------------------
    # Split text into chunk contents
    # ------------------------------------------------------------------
    sentences = _split_sentences(text)
    chunk_contents = _group_sentences_into_chunks(sentences, chunk_size, overlap)

    if not chunk_contents:
        # Should not happen given the earlier empty-text check, but guard
        # against edge cases where splitting produces nothing usable.
        raise ValueError("chunking produced no usable chunks")

    if len(chunk_contents) > MAX_CHUNKS:
        raise ValueError(
            f"Number of chunks ({len(chunk_contents)}) exceeds MAX_CHUNKS "
            f"({MAX_CHUNKS}); reduce text length or increase chunk_size"
        )

    # ------------------------------------------------------------------
    # Build EvidenceChunk objects
    # ------------------------------------------------------------------
    chunk_count = len(chunk_contents)
    # Copy tags once so each chunk gets its own independent list.
    tags_copy: list[str] = list(tags) if tags else []

    result: list[EvidenceChunk] = []
    for index, content in enumerate(chunk_contents):
        chunk = EvidenceChunk(
            chunk_id=f"{source_type}:{source_id}:{index}",
            source_type=source_type,
            source_id=source_id,
            chunk_index=index,
            chunk_count=chunk_count,
            title=title,
            content=content,
            excerpt=None,
            entity_type=entity_type,
            entity_id=entity_id,
            prospect_id=prospect_id,
            prospect_name=prospect_name,
            team_id=team_id,
            team_abbr=team_abbr,
            pick_no=pick_no,
            year=year,
            url=url,
            source_name=source_name,
            publisher=publisher,
            author=author,
            published_at=published_at,
            confidence=confidence,
            retrieval_score=None,
            relevance_reason=relevance_reason,
            conflict_note=conflict_note,
            tags=list(tags_copy),  # Each chunk gets its own copy.
            evidence_only=True,
        )
        result.append(chunk)

    return result
