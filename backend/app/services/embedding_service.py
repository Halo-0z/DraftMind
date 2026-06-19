"""RAG-v2-M2-C1: Fake deterministic embedding service.

Converts :class:`~app.schemas.evidence.EvidenceChunk` content into
fixed-dimension :class:`~app.schemas.embedding.EmbeddingVector` objects
using a deterministic, offline, dependency-free algorithm based on
SHA-256 hashing.  This is the M2-C1 foundation — a future M2-C2 may swap
in a real ``sentence-transformers`` model behind the same
:func:`embed_chunk` / :func:`embed_chunks` interface.

Design rules (mirrors :mod:`app.services.evidence_chunker`):

1. Pure functions only — no DB session, no LLM, no network, no
   ranking_engine / simulation_service / prediction_calibration /
   recommendation_service calls.
2. Only ``chunk.content`` and ``chunk.chunk_id`` are read; the input
   :class:`EvidenceChunk` is never mutated.
3. The same ``content`` always produces the same vector (deterministic).
4. The vector is L2-normalized so cosine similarity reduces to dot
   product.
5. ``evidence_only`` is always ``True`` (Literal-locked by
   :class:`EmbeddingVector`).
6. No ``retrieval_score`` is generated — that is the job of the
   retrieval service (M2-D).
7. The vector is NOT written back to :class:`EvidenceChunk` — embeddings
   live in their own payload and will be stored in the vector store
   (M2-D).
8. No external dependencies — only Python standard library (``hashlib``,
   ``math``, ``struct``).  No ``sentence_transformers`` / ``torch`` /
   ``faiss`` / ``chroma`` / ``numpy``.

Fake embedding algorithm:

1. Compute ``sha256(content.encode("utf-8"))`` to get 32 deterministic
   bytes.
2. Repeatedly hash ``(counter || previous_digest)`` to extend the byte
   stream until enough bytes are available to fill
   :data:`FAKE_EMBEDDING_DIM` floats.
3. Map each 4-byte slice to a float in ``[-1, 1]`` via signed 32-bit
   little-endian interpretation divided by ``2**31``.
4. L2-normalize the resulting vector.
"""

from __future__ import annotations

import hashlib
import math
import struct

from app.schemas.embedding import EmbeddingVector
from app.schemas.evidence import EvidenceChunk

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Fixed embedding dimension.  Matches ``all-MiniLM-L6-v2`` so a future
#: M2-C2 swap to a real model needs no downstream interface changes.
FAKE_EMBEDDING_DIM: int = 384

#: Identifier of this fake embedding model.  Recorded in
#: :attr:`EmbeddingVector.model_name` so callers can distinguish fake
#: vectors from real-model vectors.
FAKE_MODEL_NAME: str = "fake-deterministic-v1"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _generate_raw_vector(content: str, dim: int) -> list[float]:
    """Generate a deterministic raw (un-normalized) vector from ``content``.

    Uses a counter-augmented SHA-256 chain to produce enough bytes for
    ``dim`` floats.  Each 4-byte slice is interpreted as a signed 32-bit
    little-endian integer and mapped to ``[-1, 1]`` via division by
    ``2**31``.
    """
    if dim <= 0:
        raise ValueError(f"dim must be >= 1, got {dim}")

    needed_bytes = dim * 4
    digest = hashlib.sha256(content.encode("utf-8")).digest()
    collected = bytearray(digest)
    counter = 0
    while len(collected) < needed_bytes:
        counter_bytes = counter.to_bytes(4, "big")
        digest = hashlib.sha256(counter_bytes + digest).digest()
        collected.extend(digest)
        counter += 1

    raw: list[float] = []
    for i in range(dim):
        chunk_bytes = bytes(collected[i * 4 : i * 4 + 4])
        (signed_int,) = struct.unpack("<i", chunk_bytes)
        raw.append(signed_int / 2**31)
    return raw


def _l2_normalize(vector: list[float]) -> list[float]:
    """Return the L2-normalized copy of ``vector``.

    If the vector has zero norm (extremely unlikely for hash-derived
    vectors), the original vector is returned unchanged to avoid
    division by zero.
    """
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return list(vector)
    return [v / norm for v in vector]


def _fake_embed(content: str) -> list[float]:
    """Produce a deterministic, L2-normalized fake embedding for ``content``."""
    raw = _generate_raw_vector(content, FAKE_EMBEDDING_DIM)
    return _l2_normalize(raw)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def embed_chunk(chunk: EvidenceChunk) -> EmbeddingVector:
    """Embed a single :class:`EvidenceChunk` into an :class:`EmbeddingVector`.

    Only ``chunk.content`` and ``chunk.chunk_id`` are read.  The input
    chunk is never mutated.

    Parameters
    ----------
    chunk:
        The source :class:`EvidenceChunk`.  Its ``content`` must be
        non-empty (enforced by the schema).

    Returns
    -------
    EmbeddingVector
        A deterministic, L2-normalized embedding tagged with
        ``chunk.chunk_id``, :data:`FAKE_MODEL_NAME`, and
        :data:`FAKE_EMBEDDING_DIM`.
    """
    vector = _fake_embed(chunk.content)
    return EmbeddingVector(
        chunk_id=chunk.chunk_id,
        vector=vector,
        model_name=FAKE_MODEL_NAME,
        dim=FAKE_EMBEDDING_DIM,
        evidence_only=True,
    )


def embed_chunks(chunks: list[EvidenceChunk]) -> list[EmbeddingVector]:
    """Embed multiple :class:`EvidenceChunk` objects, preserving input order.

    Returns an empty list for an empty input.  Each chunk is embedded
    independently via :func:`embed_chunk` — no batching optimization is
    performed (the fake implementation is fast enough; a real model in
    M2-C2 may introduce true batching).
    """
    return [embed_chunk(chunk) for chunk in chunks]


def embed_query(query_text: str) -> list[float]:
    """Embed a query string into a vector for semantic retrieval.

    RAG-v2-M2-D2: the semantic retrieval service needs to embed raw query
    text (not an :class:`EvidenceChunk`) so it can search the vector store.
    This function reuses the same deterministic fake embedding algorithm
    as :func:`embed_chunk` but returns a bare ``list[float]`` — a query
    has no ``chunk_id`` and does not need an :class:`EmbeddingVector`
    wrapper.

    Parameters
    ----------
    query_text:
        The raw query string.  Must be non-empty and not whitespace-only.

    Returns
    -------
    list[float]
        A deterministic, L2-normalized embedding of length
        :data:`FAKE_EMBEDDING_DIM`.  Identical to
        ``embed_chunk(chunk_with_content=query_text).vector``.

    Raises
    ------
    ValueError
        If *query_text* is empty or whitespace-only.

    Safety
    ------
    - Pure function — no DB, no LLM, no network, no ranking_engine /
      simulation_service / prediction_calibration / recommendation_service
      calls.
    - Returns ``list[float]`` (not ``EmbeddingVector``) so the query
      vector cannot be confused with an indexed chunk embedding.
    - The returned vector is L2-normalized so cosine similarity reduces
      to dot product in :meth:`InMemoryVectorStore.search`.
    """
    if not query_text or not query_text.strip():
        raise ValueError("query_text must not be empty or whitespace-only")
    return _fake_embed(query_text)
