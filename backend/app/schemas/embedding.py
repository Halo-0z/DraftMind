"""RAG-v2-M2-C1: EmbeddingVector schema for fake deterministic embeddings.

Defines the payload returned by the embedding service
(:mod:`app.services.embedding_service`).  An :class:`EmbeddingVector`
carries the fixed-dimension vector computed from an
:class:`~app.schemas.evidence.EvidenceChunk`'s ``content`` plus a
back-reference to the source ``chunk_id``.

Safety contract (mirrors :class:`~app.schemas.evidence.EvidenceChunk`):

- ``evidence_only`` is Literal-locked to ``True`` — embeddings can only
  be used for retrieval preparation, never for selection / scoring /
  ranking / reranking.
- ``extra="forbid"`` rejects any dangerous field (``selected_player``,
  ``final_score``, ``prediction_sort_score``, ``retrieval_score``,
  ``rerank_score``, etc.) at construction time.
- ``vector`` length must equal ``dim`` and must not be empty.
- ``dim`` must be ``>= 1``.
- ``model_name`` records which embedding model produced this vector
  (e.g. ``"fake-deterministic-v1"`` or a future ``"all-MiniLM-L6-v2"``).

This schema does NOT touch :class:`~app.schemas.evidence.EvidenceChunk` —
embeddings are kept in their own payload so that vectors are not carried
inside chunk objects, LLM explanations, or frontend citations.  The
vector store (M2-D) will consume :class:`EmbeddingVector` directly.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EmbeddingVector(BaseModel):
    """A single embedding vector produced by the embedding service.

    Fields
    ------
    chunk_id:
        Back-reference to the source :class:`EvidenceChunk.chunk_id`.
        Used by the vector store (M2-D) to align vectors with chunks.
    vector:
        Fixed-dimension float vector.  Length must equal ``dim`` and must
        not be empty.  Vectors are expected to be L2-normalized by the
        embedding service so cosine similarity reduces to dot product.
    model_name:
        Identifier of the embedding model that produced this vector
        (e.g. ``"fake-deterministic-v1"``).
    dim:
        Vector dimension.  Must be ``>= 1`` and equal to
        ``len(vector)``.
    evidence_only:
        Safety lock — always ``True``.  Embeddings can only be used for
        retrieval preparation, never for selection / scoring / ranking.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    # Identity — back-reference to the source EvidenceChunk
    chunk_id: str

    # Vector payload
    vector: list[float]
    model_name: str
    dim: int = Field(ge=1)

    # Safety lock
    evidence_only: Literal[True] = True

    @field_validator("vector")
    @classmethod
    def _vector_must_not_be_empty(cls, value: list[float]) -> list[float]:
        """Reject empty vectors — every embedding must carry real signal."""
        if not value:
            raise ValueError("vector must not be empty")
        return value

    @model_validator(mode="after")
    def _vector_length_must_equal_dim(self) -> "EmbeddingVector":
        """Enforce ``len(vector) == dim`` so callers cannot lie about size."""
        if len(self.vector) != self.dim:
            raise ValueError(
                f"vector length ({len(self.vector)}) must equal dim ({self.dim})"
            )
        return self
