"""RAG-v2-M2-D2: Semantic retrieval service.

Converts a raw query string into a pair of
:class:`~app.schemas.evidence.RetrievedEvidence` /
:class:`~app.schemas.evidence.EvidenceCitation` lists by orchestrating
the M2-B / M2-C1 / M2-D1 / M1-B building blocks:

```text
query_text
  -> embed_query()                       [M2-D2, in embedding_service]
  -> list[float]
  -> InMemoryVectorStore.search()        [M2-D1]
  -> list[SemanticRetrievalResult]
  -> InMemoryVectorStore.get_chunk()     [M2-D1]
  -> EvidenceChunk (deepcopy, retrieval_score set on the copy)
  -> evidence_chunk_to_document()        [M1-B]
  -> EvidenceDocumentRead
  -> map_evidence_document()             [RAG-v1-B1]
  -> tuple[list[RetrievedEvidence], list[EvidenceCitation]]
```

Design rules (mirrors :mod:`app.services.vector_store_service` and
:mod:`app.services.evidence_chunk_mapper`):

1. Pure function only — no DB session, no LLM, no network, no
   ``ranking_engine`` / ``simulation_service`` /
   ``prediction_calibration`` / ``recommendation_service`` calls.
2. Inputs are never mutated — ``chunks`` is only read (it is the
   caller's responsibility to keep it in sync with the vector store);
   ``vector_store`` is only read via ``search()`` / ``get_chunk()`` /
   ``count()`` and is never written to.
3. ``retrieval_score`` flows from
   :class:`~app.schemas.vector_store.SemanticRetrievalResult` to a
   *disposable deep copy* of the indexed :class:`EvidenceChunk`
   (returned by :meth:`InMemoryVectorStore.get_chunk`) and then through
   the existing M1-B mapper chain to
   :class:`~app.schemas.evidence.RetrievedEvidence.retrieval_score`.
   The indexed chunk is never mutated (``get_chunk`` returns a deep
   copy).
4. ``retrieval_score`` does NOT enter
   :class:`~app.schemas.evidence.EvidenceCitation` — enforced by
   :mod:`app.services.evidence_document_mapper` (the citation mapper
   does not propagate ``retrieval_score``) and by the
   :class:`EvidenceCitation` schema (no ``retrieval_score`` field).
5. ``retrieval_score`` does NOT enter the LLM payload — enforced by
   :mod:`app.services.evidence_llm_explanation_service` (the
   ``_whitelist_retrieved_evidence`` whitelist excludes
   ``retrieval_score``).
6. ``retrieval_score`` is NOT written back to the indexed
   :class:`EvidenceChunk` — ``get_chunk`` returns a deep copy, and the
   score is set on that copy only.
7. ``retrieval_score`` is NOT written to
   :class:`~app.schemas.embedding.EmbeddingVector` — the
   :class:`EmbeddingVector` schema has no ``retrieval_score`` field and
   uses ``extra="forbid"``.
8. No calls to ``ranking_engine`` / ``simulation_service`` /
   ``prediction_calibration`` / ``recommendation_service`` — the
   semantic retrieval service is a knowledge-source module.

This service is intentionally NOT wired into
:mod:`app.services.evidence_service`.  Wiring (config flag, fallback to
RAG-v1 manual note retrieval, index construction) is left to M2-E.
"""

from __future__ import annotations

from app.schemas.evidence import (
    EvidenceChunk,
    EvidenceCitation,
    RetrievedEvidence,
)
from app.services.evidence_chunk_mapper import evidence_chunk_to_document
from app.services.evidence_document_mapper import map_evidence_document
from app.services.embedding_service import embed_query
from app.services.vector_store_service import InMemoryVectorStore


def retrieve_semantic(
    *,
    query_text: str,
    chunks: list[EvidenceChunk],
    vector_store: InMemoryVectorStore,
    top_k: int = 5,
    min_score: float = 0.0,
) -> tuple[list[RetrievedEvidence], list[EvidenceCitation]]:
    """Retrieve evidence chunks that semantically match *query_text*.

    Parameters
    ----------
    query_text:
        The raw query string.  Must be non-empty and not whitespace-only.
        Embedded via :func:`embed_query` to produce a query vector.
    chunks:
        The list of :class:`EvidenceChunk` objects that were indexed into
        *vector_store*.  This argument is accepted for API symmetry and
        future use (e.g. multi-source retrieval); the current
        implementation only reads chunks back out of *vector_store* via
        :meth:`InMemoryVectorStore.get_chunk`.  The list and its
        elements are NOT mutated.
    vector_store:
        The :class:`InMemoryVectorStore` to search.  Must already have
        been built via :meth:`InMemoryVectorStore.build_index`.  The
        store is only read (``search`` / ``get_chunk`` / ``count``) and
        is never written to.
    top_k:
        Maximum number of results to return.  Must be ``>= 1`` (enforced
        by :meth:`InMemoryVectorStore.search`).  Defaults to 5.
    min_score:
        Minimum ``retrieval_score`` threshold.  Results with a lower
        score are skipped.  Defaults to ``0.0`` (no filtering).

    Returns
    -------
    tuple[list[RetrievedEvidence], list[EvidenceCitation]]
        A pair of parallel lists.  ``RetrievedEvidence`` carries
        ``retrieval_score`` (for LLM explanation sorting, but the LLM
        payload whitelist excludes it).  ``EvidenceCitation`` does NOT
        carry ``retrieval_score`` (frontend display only).

    Raises
    ------
    ValueError
        If *query_text* is empty or whitespace-only (raised by
        :func:`embed_query`).
    ValueError
        If *top_k* <= 0 (raised by :meth:`InMemoryVectorStore.search`).
    ValueError
        If the query vector dimension does not match the index
        dimension (raised by :meth:`InMemoryVectorStore.search`).

    Notes
    -----
    - An empty index naturally returns ``([], [])``.
    - If :meth:`InMemoryVectorStore.get_chunk` returns ``None`` for a
      ``chunk_id`` returned by ``search`` (a theoretical inconsistency
      that should not happen with a properly built index), that result
      is skipped and the remaining results are returned normally.
    - The indexed :class:`EvidenceChunk` objects are never mutated.
      ``retrieval_score`` is set on a disposable deep copy returned by
      ``get_chunk``.
    """
    # 1. Embed the query text into a vector.  Raises ValueError on
    #    empty / whitespace-only input.
    query_vector = embed_query(query_text)

    # 2. Search the vector store.  Raises ValueError on top_k <= 0 or
    #    dimension mismatch.  Returns [] on an empty index.
    semantic_results = vector_store.search(query_vector, top_k=top_k)

    # 3. Map each SemanticRetrievalResult to (RetrievedEvidence,
    #    EvidenceCitation) via the M1-B mapper chain.
    retrieved_list: list[RetrievedEvidence] = []
    citation_list: list[EvidenceCitation] = []

    for result in semantic_results:
        # 3a. Skip results below the minimum score threshold.
        if result.retrieval_score < min_score:
            continue

        # 3b. Fetch the indexed chunk.  get_chunk returns a deep copy so
        #     setting retrieval_score on it does NOT mutate the index.
        chunk = vector_store.get_chunk(result.chunk_id)
        if chunk is None:
            # Defensive: should not happen with a properly built index
            # (build_index validates chunk_id alignment), but skip
            # gracefully if it does.
            continue

        # 3c. Set retrieval_score on the disposable deep copy.  The
        #     indexed chunk is unaffected (get_chunk returns deepcopy).
        chunk.retrieval_score = result.retrieval_score

        # 3d. Flow through the M1-B mapper chain:
        #     EvidenceChunk -> EvidenceDocumentRead -> (Retrieved, Citation)
        document = evidence_chunk_to_document(chunk)
        retrieved, citation = map_evidence_document(document)

        retrieved_list.append(retrieved)
        citation_list.append(citation)

    return retrieved_list, citation_list
