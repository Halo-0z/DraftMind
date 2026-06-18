"""RAG-v1-B2: Knowledge source boundary tests.

These tests enforce the safety boundary that knowledge-source modules
(ManualNoteRecord, evidence_document_mapper, future evidence_retrieval) are
NOT imported by the selection system (ranking_engine, simulation_service,
prediction_calibration).  This keeps the "evidence only explains, never
selects" guarantee at the source-code level.

The checks are intentionally simple text-based inspections of the module
source so that a future import slip is caught immediately without needing
to run the full ranking pipeline.
"""

from __future__ import annotations

from pathlib import Path

from app.models.manual_note import ManualNoteRecord

# Modules that form the selection system and must remain knowledge-source-free.
SELECTION_SYSTEM_MODULES = [
    "app/services/ranking_engine.py",
    "app/services/simulation_service.py",
    "app/services/prediction_calibration.py",
]

# Knowledge-source module names that must never appear in selection-system
# imports or top-level references.
FORBIDDEN_KNOWLEDGE_TOKENS = [
    "manual_note",
    "ManualNoteRecord",
    "evidence_document_mapper",
    "EvidenceDocumentRead",
    "evidence_retrieval",
    # RAG-v2-M2-C1: embedding modules are knowledge-source-only — they
    # prepare retrieval payloads but must never influence selection /
    # scoring / ranking.
    "embedding_service",
    "EmbeddingVector",
    "embed_chunk",
    "embed_chunks",
    # RAG-v2-M2-D1: vector store modules are knowledge-source-only — they
    # compute retrieval_score for evidence recall / sorting but must
    # never influence selection / scoring / ranking.
    "vector_store_service",
    "SemanticRetrievalResult",
    "InMemoryVectorStore",
]


def _module_source_path(module_relative_path: str) -> Path:
    # backend/app/services/ranking_engine.py -> d:/DraftMind/backend/app/services/ranking_engine.py
    backend_root = Path(__file__).resolve().parents[2]
    return backend_root / module_relative_path


def test_manual_note_record_evidence_only_defaults_to_true() -> None:
    """The DB model must default evidence_only to True."""
    column = ManualNoteRecord.__table__.columns["evidence_only"]
    assert column.default is not None
    assert column.default.arg is True


def test_selection_system_modules_do_not_import_knowledge_sources() -> None:
    """ranking_engine / simulation_service / prediction_calibration must not
    import any knowledge-source module."""
    for module_path in SELECTION_SYSTEM_MODULES:
        source_path = _module_source_path(module_path)
        assert source_path.exists(), f"missing selection-system module: {module_path}"

        source_text = source_path.read_text(encoding="utf-8")

        for token in FORBIDDEN_KNOWLEDGE_TOKENS:
            assert token not in source_text, (
                f"{module_path} must not reference knowledge-source token "
                f"'{token}' — selection system must remain knowledge-source-free"
            )


def test_manual_note_model_does_not_import_selection_system() -> None:
    """The ManualNoteRecord model must not import ranking / simulation /
    prediction modules (reverse boundary)."""
    import app.models.manual_note as model_module

    forbidden_module_attrs = {
        "ranking_engine",
        "simulation_service",
        "prediction_calibration",
        "rank_prospects",
        "simulate_draft",
    }

    module_attrs = set(vars(model_module).keys())
    assert forbidden_module_attrs.isdisjoint(module_attrs)


def test_embedding_service_does_not_import_selection_system() -> None:
    """The embedding service must not import ranking / simulation /
    prediction / recommendation modules (reverse boundary).

    RAG-v2-M2-C1: embeddings are knowledge-source-only — they prepare
    retrieval payloads but must never influence selection / scoring /
    ranking.  This test enforces the boundary at the module-attribute
    level so a future import slip is caught immediately.
    """
    import app.services.embedding_service as embedding_module

    forbidden_module_attrs = {
        "ranking_engine",
        "simulation_service",
        "prediction_calibration",
        "recommendation_service",
        "team_need_service",
        "team_need_adjustment",
        "scouting_fit",
        "rank_prospects",
        "simulate_draft",
    }

    module_attrs = set(vars(embedding_module).keys())
    assert forbidden_module_attrs.isdisjoint(module_attrs)


def test_embedding_service_does_not_import_db_or_llm_or_ml_libs() -> None:
    """The embedding service must not import DB / LLM / external ML libraries.

    RAG-v2-M2-C1: the fake embedding is pure-Python (``hashlib`` +
    ``math`` + ``struct``).  This test guards against accidental
    introduction of ``sqlalchemy`` / ``openai`` / ``sentence_transformers``
    / ``torch`` / ``faiss`` / ``chroma`` / ``numpy`` imports.
    """
    import app.services.embedding_service as embedding_module

    forbidden_module_attrs = {
        "sqlalchemy",
        "SessionLocal",
        "sessionmaker",
        "create_engine",
        "get_db",
        "openai",
        "anthropic",
        "sentence_transformers",
        "torch",
        "faiss",
        "chromadb",
        "numpy",
        "transformers",
        "sklearn",
    }

    module_attrs = set(vars(embedding_module).keys())
    assert forbidden_module_attrs.isdisjoint(module_attrs)


def test_vector_store_service_does_not_import_selection_system() -> None:
    """The vector store must not import ranking / simulation /
    prediction / recommendation modules (reverse boundary).

    RAG-v2-M2-D1: the vector store computes retrieval_score for evidence
    recall / sorting but must never influence selection / scoring /
    ranking.  This test enforces the boundary at the module-attribute
    level so a future import slip is caught immediately.
    """
    import app.services.vector_store_service as vs_module

    forbidden_module_attrs = {
        "ranking_engine",
        "simulation_service",
        "prediction_calibration",
        "recommendation_service",
        "team_need_service",
        "team_need_adjustment",
        "scouting_fit",
        "rank_prospects",
        "simulate_draft",
    }

    module_attrs = set(vars(vs_module).keys())
    assert forbidden_module_attrs.isdisjoint(module_attrs)


def test_vector_store_service_does_not_import_db_or_llm_or_ml_libs() -> None:
    """The vector store must not import DB / LLM / external ML libraries.

    RAG-v2-M2-D1: the in-memory store is pure-Python (``copy`` +
    ``app.schemas.*``).  This test guards against accidental introduction
    of ``sqlalchemy`` / ``openai`` / ``numpy`` / ``faiss`` / ``torch`` /
    ``sentence_transformers`` / ``chroma`` imports.
    """
    import app.services.vector_store_service as vs_module

    forbidden_module_attrs = {
        "sqlalchemy",
        "SessionLocal",
        "sessionmaker",
        "create_engine",
        "get_db",
        "openai",
        "anthropic",
        "numpy",
        "faiss",
        "torch",
        "sentence_transformers",
        "chroma",
        "chromadb",
        "sklearn",
        "transformers",
    }

    module_attrs = set(vars(vs_module).keys())
    assert forbidden_module_attrs.isdisjoint(module_attrs)


def test_manual_note_record_does_not_expose_scoring_or_replacement_fields() -> None:
    """ManualNoteRecord must not carry any scoring / selection / rerank /
    replacement field."""
    forbidden_fields = {
        "recommended_player",
        "replacement_player",
        "new_selected_player",
        "rerank_score",
        "new_score",
        "score_adjustment",
        "ranking_weight",
        "selection_override",
        "final_score_delta",
        "prediction_sort_delta",
        "should_have_selected",
        "better_pick",
    }

    column_names = {column.name for column in ManualNoteRecord.__table__.columns}

    assert forbidden_fields.isdisjoint(column_names)
