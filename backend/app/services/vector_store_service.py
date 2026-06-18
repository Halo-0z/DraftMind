"""RAG-v2-M2-D1: In-memory vector store service.

Provides a pure-Python in-memory vector store that indexes
:class:`~app.schemas.evidence.EvidenceChunk` objects alongside their
:class:`~app.schemas.embedding.EmbeddingVector` vectors and supports
cosine-similarity retrieval via :class:`SemanticRetrievalResult`.

This is the M2-D1 foundation — a future M2-D3 may swap in a FAISS-backed
implementation behind the same :class:`InMemoryVectorStore` interface.

Design rules (mirrors :mod:`app.services.embedding_service` and
:mod:`app.services.evidence_chunker`):

1. Pure Python only — no DB session, no LLM, no network, no
   ``numpy`` / ``faiss`` / ``torch`` / ``sentence_transformers`` /
   ``chroma``.  Dot product is computed with a plain ``sum()`` loop.
2. Inputs are never mutated — :meth:`build_index` reads
   ``chunk.chunk_id`` and stores a deep copy of each chunk;
   ``embedding.vector`` / ``embedding.dim`` / ``embedding.chunk_id`` are
   read but the embedding object itself is not stored (only its vector
   and dim are kept).
3. ``retrieval_score`` is computed as dot product.  Because
   :class:`EmbeddingVector` is L2-normalized by the embedding service,
   dot product equals cosine similarity.  Negative scores are clamped to
   ``0.0`` so :class:`SemanticRetrievalResult.retrieval_score` is always
   ``>= 0``.
4. ``retrieval_score`` is NOT written back to
   :class:`EvidenceChunk` — it lives only in
   :class:`SemanticRetrievalResult` and downstream
   :class:`~app.schemas.evidence.RetrievedEvidence`.
5. Sorting is stable — results are sorted by ``retrieval_score``
   descending, with ``chunk_id`` ascending as the deterministic
   tie-breaker.
6. No ``retrieval_score`` is exposed to
   :class:`~app.schemas.evidence.EvidenceCitation` or LLM payloads —
   that boundary is enforced by the retrieval service (M2-D2) and the
   LLM payload whitelist (RAG-v1-D3-B).
7. No calls to ``ranking_engine`` / ``simulation_service`` /
   ``prediction_calibration`` / ``recommendation_service`` — the vector
   store is a knowledge-source module.
"""

from __future__ import annotations

import copy

from app.schemas.embedding import EmbeddingVector
from app.schemas.evidence import EvidenceChunk
from app.schemas.vector_store import SemanticRetrievalResult


class InMemoryVectorStore:
    """Pure-Python in-memory vector store.

    The store holds:

    - ``_chunks: dict[str, EvidenceChunk]`` — ``chunk_id`` → deep-copied
      :class:`EvidenceChunk` (so callers cannot mutate the index by
      mutating the original chunk objects).
    - ``_vectors: dict[str, list[float]]`` — ``chunk_id`` → vector
      (copied from :attr:`EmbeddingVector.vector`).
    - ``_dim: int | None`` — vector dimension, ``None`` when the index
      is empty.

    The store is NOT thread-safe.  Callers that need concurrent access
    must wrap it in a lock.  In the RAG-v2 pipeline the store is built
    once at startup and read-only afterwards, so thread-safety is not a
    concern.
    """

    def __init__(self) -> None:
        self._chunks: dict[str, EvidenceChunk] = {}
        self._vectors: dict[str, list[float]] = {}
        self._dim: int | None = None

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------

    def build_index(
        self,
        chunks: list[EvidenceChunk],
        embeddings: list[EmbeddingVector],
    ) -> None:
        """Build the index from ``chunks`` and ``embeddings``.

        Requirements:

        - ``chunks`` and ``embeddings`` must have the same length.
        - At each position ``i``, ``chunks[i].chunk_id`` must equal
          ``embeddings[i].chunk_id``.
        - ``chunk_id`` values must be unique across the whole input.
        - An empty input (``chunks=[]``, ``embeddings=[]``) is legal and
          produces an empty index.

        The input ``chunks`` and ``embeddings`` are NOT mutated.  Each
        chunk is deep-copied before storage so callers cannot mutate the
        index by mutating the original chunk objects.

        Calling :meth:`build_index` on a non-empty store replaces the
        previous index entirely (the store is reset).
        """
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks length ({len(chunks)}) must equal embeddings length "
                f"({len(embeddings)})"
            )

        # Reset the store — build_index replaces, it does not append.
        self._chunks = {}
        self._vectors = {}
        self._dim = None

        if not chunks:
            return

        # Validate alignment + uniqueness in a single pass.
        seen_chunk_ids: set[str] = set()
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            if chunk.chunk_id != embedding.chunk_id:
                raise ValueError(
                    f"chunk_id mismatch at index {i}: "
                    f"chunk.chunk_id={chunk.chunk_id!r} != "
                    f"embedding.chunk_id={embedding.chunk_id!r}"
                )
            if chunk.chunk_id in seen_chunk_ids:
                raise ValueError(f"duplicate chunk_id: {chunk.chunk_id!r}")
            seen_chunk_ids.add(chunk.chunk_id)

        # All embeddings must share the same dimension.
        first_dim = embeddings[0].dim
        for i, embedding in enumerate(embeddings):
            if embedding.dim != first_dim:
                raise ValueError(
                    f"embedding dim mismatch at index {i}: "
                    f"expected {first_dim}, got {embedding.dim}"
                )

        self._dim = first_dim
        for chunk, embedding in zip(chunks, embeddings):
            # Deep-copy the chunk so callers cannot mutate the index.
            self._chunks[chunk.chunk_id] = copy.deepcopy(chunk)
            # Copy the vector list so callers cannot mutate it via the
            # original EmbeddingVector object.
            self._vectors[chunk.chunk_id] = list(embedding.vector)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
    ) -> list[SemanticRetrievalResult]:
        """Return the top-K chunks most similar to ``query_vector``.

        Similarity is dot product.  Because indexed embeddings are
        L2-normalized, dot product equals cosine similarity.  Negative
        scores are clamped to ``0.0``.

        Results are sorted by ``retrieval_score`` descending, with
        ``chunk_id`` ascending as the deterministic tie-breaker.

        Parameters
        ----------
        query_vector:
            Query embedding vector.  Its length must equal the index
            dimension (``self._dim``).  On an empty index any non-empty
            vector is accepted and an empty list is returned.
        top_k:
            Maximum number of results to return.  Must be ``>= 1``.
            If ``top_k > count()``, all indexed chunks are returned.

        Returns
        -------
        list[SemanticRetrievalResult]
            Top-K results, sorted by score descending then chunk_id
            ascending.  Empty list if the index is empty.
        """
        if top_k <= 0:
            raise ValueError(f"top_k must be >= 1, got {top_k}")

        # Empty index — nothing to search.
        if self._dim is None or not self._chunks:
            return []

        if len(query_vector) != self._dim:
            raise ValueError(
                f"query vector dim ({len(query_vector)}) must match "
                f"index dim ({self._dim})"
            )

        # Compute dot product for every indexed chunk.
        results: list[SemanticRetrievalResult] = []
        for chunk_id, vector in self._vectors.items():
            score = _dot_product(query_vector, vector)
            # Clamp negative scores to 0.0 — cosine similarity in [-1, 1]
            # but negative correlation is treated as "not relevant".
            if score < 0.0:
                score = 0.0
            results.append(
                SemanticRetrievalResult(
                    chunk_id=chunk_id,
                    retrieval_score=score,
                    evidence_only=True,
                )
            )

        # Stable sort: score descending, chunk_id ascending.
        # Python's sorted() is stable (Timsort), so equal scores retain
        # insertion order — but we add chunk_id as an explicit
        # tie-breaker for full determinism across Python versions.
        results.sort(key=lambda r: (-r.retrieval_score, r.chunk_id))

        return results[:top_k]

    # ------------------------------------------------------------------
    # Chunk lookup
    # ------------------------------------------------------------------

    def get_chunk(self, chunk_id: str) -> EvidenceChunk | None:
        """Return the indexed :class:`EvidenceChunk` for ``chunk_id``.

        Returns ``None`` if the chunk is not in the index.  The returned
        chunk is a deep copy so callers cannot mutate the index by
        mutating the returned object.
        """
        chunk = self._chunks.get(chunk_id)
        if chunk is None:
            return None
        return copy.deepcopy(chunk)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return the number of indexed chunks."""
        return len(self._chunks)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dot_product(a: list[float], b: list[float]) -> float:
    """Return the dot product of two equal-length float vectors.

    Pure Python — no ``numpy``.  The vectors are assumed to have the
    same length (validated by the caller).
    """
    return sum(x * y for x, y in zip(a, b))
