"""RAG-v2-M2-D1: SemanticRetrievalResult schema for in-memory vector store.

Defines the payload returned by
:class:`~app.services.vector_store_service.InMemoryVectorStore.search`.
A :class:`SemanticRetrievalResult` carries the ``chunk_id`` back-reference
plus the ``retrieval_score`` (cosine similarity) computed by the vector
store.

Safety contract (mirrors :class:`~app.schemas.embedding.EmbeddingVector`
and :class:`~app.schemas.evidence.EvidenceChunk`):

- ``evidence_only`` is Literal-locked to ``True`` — retrieval results can
  only be used for evidence recall / sorting, never for selection /
  scoring / ranking / reranking.
- ``extra="forbid"`` rejects any dangerous field (``selected_player``,
  ``final_score``, ``prediction_sort_score``, ``rerank_score``,
  ``embedding``, ``vector``, etc.) at construction time.
- ``retrieval_score`` must be ``>= 0`` — negative cosine similarities are
  clamped to ``0.0`` by the vector store so callers never see negative
  scores.
- ``chunk_id`` is required — every retrieval result must trace back to a
  source :class:`~app.schemas.evidence.EvidenceChunk`.

This schema does NOT touch :class:`~app.schemas.evidence.EvidenceChunk`
or :class:`~app.schemas.embedding.EmbeddingVector` — retrieval results
are kept in their own payload so that vectors and scores are not carried
inside chunk objects, LLM explanations, or frontend citations.  The
semantic retrieval service (M2-D2) will consume
:class:`SemanticRetrievalResult` and map it to
:class:`~app.schemas.evidence.RetrievedEvidence` (which carries
``retrieval_score`` for display) and
:class:`~app.schemas.evidence.EvidenceCitation` (which does NOT carry
``retrieval_score``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SemanticRetrievalResult(BaseModel):
    """A single retrieval result from the in-memory vector store.

    Fields
    ------
    chunk_id:
        Back-reference to the source :class:`EvidenceChunk.chunk_id`.
        Used by the retrieval service (M2-D2) to fetch the original
        chunk for evidence package assembly.
    retrieval_score:
        Cosine similarity between the query vector and the chunk's
        embedding vector.  Because :class:`EmbeddingVector` is
        L2-normalized, cosine similarity reduces to dot product.
        Negative scores are clamped to ``0.0`` so callers never see
        negative values.  Must be ``>= 0``.
    evidence_only:
        Safety lock — always ``True``.  Retrieval results can only be
        used for evidence recall / sorting, never for selection /
        scoring / ranking.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    # Identity — back-reference to the source EvidenceChunk
    chunk_id: str

    # Similarity score
    retrieval_score: float = Field(ge=0)

    # Safety lock
    evidence_only: Literal[True] = True
