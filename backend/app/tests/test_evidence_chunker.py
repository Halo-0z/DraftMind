"""Tests for the evidence chunking service (RAG-v2-M2-B).

Covers:
- Short text → 1 chunk; long text → multiple chunks
- chunk_index / chunk_count / chunk_id stability and uniqueness
- chunk_size / overlap defaults and customisation
- Sentence-aware splitting (Chinese / English / mixed / newlines)
- Character fallback for over-long sentences
- Edge cases: empty/whitespace text, invalid params, MAX_CHUNKS
- Safety: evidence_only=True, retrieval_score=None, excerpt=None
- Metadata propagation; tags not shared; input not mutated
- Module purity: no DB / LLM / ranking / simulation / prediction imports
- Full chain: chunk_text → EvidenceChunk → evidence_chunk_to_document
  → map_evidence_document
"""

from __future__ import annotations

import ast
import copy
from datetime import datetime

import pytest

from app.schemas.evidence import (
    EvidenceChunk,
    EvidenceCitation,
    RetrievedEvidence,
)
from app.services.evidence_chunker import (
    MAX_CHUNKS,
    chunk_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_long_text(num_sentences: int = 20, sentence_len: int = 50) -> str:
    """Build a long text with *num_sentences* sentences of ~*sentence_len* chars."""
    sentences = []
    for i in range(num_sentences):
        # Each sentence is a padded English sentence ending with a period.
        word = f"Sentence{i:04d}"
        padding = "x" * (sentence_len - len(word) - 2)
        sentences.append(f"{word} {padding}.")
    return " ".join(sentences)


# ---------------------------------------------------------------------------
# Basic splitting
# ---------------------------------------------------------------------------


def test_short_text_produces_single_chunk() -> None:
    chunks = chunk_text("Short text.", source_type="test", source_id="1")
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].chunk_count == 1


def test_long_text_produces_multiple_chunks() -> None:
    text = _make_long_text(num_sentences=30, sentence_len=50)
    chunks = chunk_text(text, source_type="test", source_id="1", chunk_size=200)
    assert len(chunks) > 1


def test_chunk_index_starts_at_zero_and_increments() -> None:
    text = _make_long_text(num_sentences=30, sentence_len=50)
    chunks = chunk_text(text, source_type="test", source_id="1", chunk_size=200)
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))


def test_chunk_count_equals_actual_chunk_count() -> None:
    text = _make_long_text(num_sentences=30, sentence_len=50)
    chunks = chunk_text(text, source_type="test", source_id="1", chunk_size=200)
    assert all(c.chunk_count == len(chunks) for c in chunks)


# ---------------------------------------------------------------------------
# chunk_id
# ---------------------------------------------------------------------------


def test_chunk_id_format_is_stable() -> None:
    chunks = chunk_text(
        "Hello world. Another sentence.",
        source_type="manual_note",
        source_id="42",
        chunk_size=15,
        overlap=0,
    )
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_id == f"manual_note:42:{i}"


def test_same_input_produces_same_chunk_ids() -> None:
    text = _make_long_text(num_sentences=20, sentence_len=40)
    chunks1 = chunk_text(text, source_type="test", source_id="1", chunk_size=200)
    chunks2 = chunk_text(text, source_type="test", source_id="1", chunk_size=200)
    assert [c.chunk_id for c in chunks1] == [c.chunk_id for c in chunks2]


def test_different_chunks_have_different_chunk_ids() -> None:
    text = _make_long_text(num_sentences=30, sentence_len=50)
    chunks = chunk_text(text, source_type="test", source_id="1", chunk_size=200)
    chunk_ids = [c.chunk_id for c in chunks]
    assert len(chunk_ids) == len(set(chunk_ids))


# ---------------------------------------------------------------------------
# chunk_size / overlap
# ---------------------------------------------------------------------------


def test_default_chunk_size_is_600() -> None:
    """A text just under 600 chars should produce 1 chunk with default size."""
    text = "x" * 599
    chunks = chunk_text(text, source_type="test", source_id="1")
    assert len(chunks) == 1


def test_custom_chunk_size_takes_effect() -> None:
    text = _make_long_text(num_sentences=20, sentence_len=50)
    chunks_small = chunk_text(text, source_type="t", source_id="1", chunk_size=100)
    chunks_large = chunk_text(text, source_type="t", source_id="1", chunk_size=500)
    assert len(chunks_small) > len(chunks_large)


def test_custom_overlap_takes_effect() -> None:
    text = _make_long_text(num_sentences=20, sentence_len=50)
    chunks_no_overlap = chunk_text(
        text, source_type="t", source_id="1", chunk_size=200, overlap=0
    )
    chunks_with_overlap = chunk_text(
        text, source_type="t", source_id="1", chunk_size=200, overlap=50
    )
    # With overlap, chunks should be slightly longer on average (context prefix).
    avg_no = sum(len(c.content) for c in chunks_no_overlap) / len(chunks_no_overlap)
    avg_yes = sum(len(c.content) for c in chunks_with_overlap) / len(chunks_with_overlap)
    assert avg_yes >= avg_no


def test_adjacent_chunks_have_overlap_context() -> None:
    """When overlap > 0, a suffix of chunk[i] should appear in chunk[i+1]."""
    text = _make_long_text(num_sentences=30, sentence_len=50)
    chunks = chunk_text(text, source_type="t", source_id="1", chunk_size=200, overlap=60)
    assert len(chunks) >= 2

    for i in range(len(chunks) - 1):
        prev_tail = chunks[i].content[-60:]
        # The overlap text should appear somewhere in the next chunk's start.
        assert prev_tail in chunks[i + 1].content


# ---------------------------------------------------------------------------
# Sentence boundaries
# ---------------------------------------------------------------------------


def test_chinese_period_as_boundary() -> None:
    text = "第一句话在这里。第二句话在这里。第三句话在这里。"
    chunks = chunk_text(text, source_type="t", source_id="1", chunk_size=20, overlap=0)
    # Each sentence is 8 chars + 1 delimiter = 9 chars.
    # With chunk_size=20, sentences should be packed but separated.
    assert len(chunks) >= 2
    # No chunk should contain parts of different sentences mid-way.
    for chunk in chunks:
        assert chunk.content.strip()


def test_english_period_as_boundary() -> None:
    text = "First sentence here. Second sentence here. Third sentence here."
    chunks = chunk_text(text, source_type="t", source_id="1", chunk_size=25, overlap=0)
    assert len(chunks) >= 2


def test_question_and_exclamation_as_boundary() -> None:
    text = "Is this a question? Yes it is! What about this? No it is not!"
    chunks = chunk_text(text, source_type="t", source_id="1", chunk_size=25, overlap=0)
    assert len(chunks) >= 2


def test_newline_as_boundary() -> None:
    text = "Line one content here.\nLine two content here.\nLine three here."
    chunks = chunk_text(text, source_type="t", source_id="1", chunk_size=25, overlap=0)
    assert len(chunks) >= 2


def test_mixed_chinese_english_text() -> None:
    text = "English sentence. 中文句子。Mixed 中英 text here. 又一句中文。"
    chunks = chunk_text(text, source_type="t", source_id="1", chunk_size=25, overlap=0)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.content.strip()


def test_single_sentence_exceeding_chunk_size_uses_char_fallback() -> None:
    """A single sentence longer than chunk_size is split by characters."""
    # No sentence boundaries — one long "sentence".
    text = "x" * 500
    chunks = chunk_text(text, source_type="t", source_id="1", chunk_size=200, overlap=20)
    assert len(chunks) >= 2
    # Each chunk should be at most chunk_size chars.
    for chunk in chunks:
        assert len(chunk.content) <= 200


# ---------------------------------------------------------------------------
# Edge cases / error handling
# ---------------------------------------------------------------------------


def test_empty_text_raises_value_error() -> None:
    with pytest.raises(ValueError, match="empty"):
        chunk_text("", source_type="t", source_id="1")


def test_whitespace_only_text_raises_value_error() -> None:
    with pytest.raises(ValueError, match="empty"):
        chunk_text("   \n\t  ", source_type="t", source_id="1")


def test_chunk_size_zero_raises_value_error() -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        chunk_text("Hello.", source_type="t", source_id="1", chunk_size=0)


def test_chunk_size_negative_raises_value_error() -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        chunk_text("Hello.", source_type="t", source_id="1", chunk_size=-10)


def test_overlap_negative_raises_value_error() -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("Hello.", source_type="t", source_id="1", overlap=-5)


def test_overlap_equal_to_chunk_size_raises_value_error() -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("Hello.", source_type="t", source_id="1", chunk_size=100, overlap=100)


def test_overlap_greater_than_chunk_size_raises_value_error() -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("Hello.", source_type="t", source_id="1", chunk_size=50, overlap=60)


def test_exceeding_max_chunks_raises_value_error() -> None:
    """A very long text with tiny chunk_size should exceed MAX_CHUNKS."""
    # Produce a text that would generate > MAX_CHUNKS chunks.
    # Each chunk is ~chunk_size chars; we need > MAX_CHUNKS * chunk_size chars.
    chunk_size = 50
    text = "x" * (MAX_CHUNKS * chunk_size + 100)
    with pytest.raises(ValueError, match="MAX_CHUNKS"):
        chunk_text(
            text,
            source_type="t",
            source_id="1",
            chunk_size=chunk_size,
            overlap=0,
        )


# ---------------------------------------------------------------------------
# Content / safety constraints
# ---------------------------------------------------------------------------


def test_every_chunk_content_is_non_empty() -> None:
    text = _make_long_text(num_sentences=30, sentence_len=50)
    chunks = chunk_text(text, source_type="t", source_id="1", chunk_size=200)
    for chunk in chunks:
        assert chunk.content
        assert chunk.content.strip()


def test_every_chunk_evidence_only_is_true() -> None:
    text = _make_long_text(num_sentences=20, sentence_len=50)
    chunks = chunk_text(text, source_type="t", source_id="1", chunk_size=200)
    for chunk in chunks:
        assert chunk.evidence_only is True


def test_every_chunk_retrieval_score_is_none() -> None:
    text = _make_long_text(num_sentences=20, sentence_len=50)
    chunks = chunk_text(text, source_type="t", source_id="1", chunk_size=200)
    for chunk in chunks:
        assert chunk.retrieval_score is None


def test_every_chunk_excerpt_is_none() -> None:
    text = _make_long_text(num_sentences=20, sentence_len=50)
    chunks = chunk_text(text, source_type="t", source_id="1", chunk_size=200)
    for chunk in chunks:
        assert chunk.excerpt is None


# ---------------------------------------------------------------------------
# Metadata propagation
# ---------------------------------------------------------------------------


def test_metadata_propagated_to_every_chunk() -> None:
    ts = datetime(2026, 6, 19, 12, 0, 0)
    text = _make_long_text(num_sentences=20, sentence_len=50)
    chunks = chunk_text(
        text,
        source_type="scouting_report",
        source_id="77",
        title="Workout Notes",
        entity_type="prospect",
        entity_id=101,
        prospect_id=101,
        prospect_name="John Doe",
        team_id=7,
        team_abbr="LAL",
        pick_no=5,
        year=2026,
        url="https://example.test/report/77",
        source_name="Scout Notes",
        publisher="DraftMind",
        author="Analyst A",
        published_at=ts,
        confidence=0.85,
        relevance_reason="Explains creation upside.",
        conflict_note="Conflicts with mock draft.",
        tags=["shooting", "defense"],
        chunk_size=200,
    )
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.source_type == "scouting_report"
        assert chunk.source_id == "77"
        assert chunk.title == "Workout Notes"
        assert chunk.entity_type == "prospect"
        assert chunk.entity_id == 101
        assert chunk.prospect_id == 101
        assert chunk.prospect_name == "John Doe"
        assert chunk.team_id == 7
        assert chunk.team_abbr == "LAL"
        assert chunk.pick_no == 5
        assert chunk.year == 2026
        assert chunk.url == "https://example.test/report/77"
        assert chunk.source_name == "Scout Notes"
        assert chunk.publisher == "DraftMind"
        assert chunk.author == "Analyst A"
        assert chunk.published_at == ts
        assert chunk.confidence == 0.85
        assert chunk.relevance_reason == "Explains creation upside."
        assert chunk.conflict_note == "Conflicts with mock draft."
        assert chunk.tags == ["shooting", "defense"]


def test_tags_not_shared_mutable_list() -> None:
    """Each chunk must have its own independent tags list."""
    chunks = chunk_text(
        _make_long_text(num_sentences=20, sentence_len=50),
        source_type="t",
        source_id="1",
        tags=["a", "b"],
        chunk_size=200,
    )
    assert len(chunks) >= 2
    # Mutating one chunk's tags must not affect others.
    chunks[0].tags.append("c")
    assert chunks[1].tags == ["a", "b"]


def test_chunk_text_does_not_mutate_input_tags() -> None:
    input_tags = ["shooting", "defense"]
    original = copy.deepcopy(input_tags)
    chunk_text(
        _make_long_text(num_sentences=10, sentence_len=50),
        source_type="t",
        source_id="1",
        tags=input_tags,
        chunk_size=200,
    )
    assert input_tags == original


# ---------------------------------------------------------------------------
# Module purity
# ---------------------------------------------------------------------------


def test_chunker_module_does_not_import_db() -> None:
    import app.services.evidence_chunker as module

    forbidden_attrs = {
        "database",
        "SessionLocal",
        "get_db",
        "sessionmaker",
        "sqlalchemy",
        "engine",
        "Session",
    }
    module_attrs = set(vars(module).keys())
    assert forbidden_attrs.isdisjoint(module_attrs)


def test_chunker_module_does_not_import_llm() -> None:
    import app.services.evidence_chunker as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "import openai" not in source
    assert "import anthropic" not in source
    assert "llm_service" not in source


def test_chunker_module_does_not_import_decision_modules() -> None:
    """AST-verify the chunker does not import ranking/simulation/prediction/recommendation."""
    import app.services.evidence_chunker as module

    source = open(module.__file__, encoding="utf-8").read()
    tree = ast.parse(source)

    forbidden_modules = {
        "ranking_engine",
        "simulation_service",
        "prediction_calibration",
        "recommendation_service",
    }

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.add(node.module.split(".")[-1])
            for alias in node.names:
                imported_names.add(alias.name)

    for forbidden in forbidden_modules:
        assert forbidden not in imported_names, (
            f"chunker module imports forbidden module '{forbidden}'"
        )


def test_chunk_text_does_not_call_ranking_engine(monkeypatch) -> None:
    def fail_rank_prospects(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("chunk_text must not call ranking_engine")

    monkeypatch.setattr(
        "app.services.ranking_engine.rank_prospects",
        fail_rank_prospects,
    )

    chunks = chunk_text("Hello world.", source_type="t", source_id="1")
    assert len(chunks) == 1


def test_chunk_output_does_not_expose_dangerous_fields() -> None:
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

    chunks = chunk_text("Hello world.", source_type="t", source_id="1")
    assert forbidden_fields.isdisjoint(EvidenceChunk.model_fields)
    for chunk in chunks:
        assert forbidden_fields.isdisjoint(chunk.model_dump())


# ---------------------------------------------------------------------------
# Full chain: chunk_text → EvidenceChunk → evidence_chunk_to_document
#             → map_evidence_document
# ---------------------------------------------------------------------------


def test_full_chain_single_chunk_produces_retrieved_evidence_and_citation() -> None:
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    chunks = chunk_text(
        "Short text for single chunk.",
        source_type="test",
        source_id="1",
    )
    assert len(chunks) == 1

    document = evidence_chunk_to_document(chunks[0])
    retrieved, citation = map_evidence_document(document)

    assert isinstance(retrieved, RetrievedEvidence)
    assert isinstance(citation, EvidenceCitation)


def test_full_chain_multi_chunk_each_produces_retrieved_and_citation() -> None:
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    text = _make_long_text(num_sentences=30, sentence_len=50)
    chunks = chunk_text(text, source_type="test", source_id="1", chunk_size=200)
    assert len(chunks) > 1

    for chunk in chunks:
        document = evidence_chunk_to_document(chunk)
        retrieved, citation = map_evidence_document(document)
        assert isinstance(retrieved, RetrievedEvidence)
        assert isinstance(citation, EvidenceCitation)


def test_full_chain_preserves_source_type_and_source_id() -> None:
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    text = _make_long_text(num_sentences=20, sentence_len=50)
    chunks = chunk_text(text, source_type="scouting_report", source_id="42", chunk_size=200)

    for chunk in chunks:
        document = evidence_chunk_to_document(chunk)
        retrieved, citation = map_evidence_document(document)
        assert retrieved.source_type == "scouting_report"
        assert citation.source_type == "scouting_report"
        # source_id on the document is the chunk_id.
        assert retrieved.source_id == chunk.chunk_id


def test_full_chain_preserves_evidence_only() -> None:
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    text = _make_long_text(num_sentences=20, sentence_len=50)
    chunks = chunk_text(text, source_type="t", source_id="1", chunk_size=200)

    for chunk in chunks:
        document = evidence_chunk_to_document(chunk)
        retrieved, citation = map_evidence_document(document)
        assert retrieved.evidence_only is True
        assert citation.evidence_only is True


def test_full_chain_retrieval_score_stays_none() -> None:
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    text = _make_long_text(num_sentences=20, sentence_len=50)
    chunks = chunk_text(text, source_type="t", source_id="1", chunk_size=200)

    for chunk in chunks:
        assert chunk.retrieval_score is None
        document = evidence_chunk_to_document(chunk)
        retrieved, citation = map_evidence_document(document)
        # retrieval_score stays None through the chain.
        assert retrieved.retrieval_score is None
        # EvidenceCitation does not have a retrieval_score field.
        assert "retrieval_score" not in citation.__class__.model_fields


def test_full_chain_excerpt_generated_by_mapper() -> None:
    """chunk_text sets excerpt=None; the mapper generates it from content."""
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    chunks = chunk_text("Hello world.", source_type="t", source_id="1")
    assert chunks[0].excerpt is None

    document = evidence_chunk_to_document(chunks[0])
    # Mapper generates excerpt from content when chunk.excerpt is None.
    assert document.excerpt is not None
    assert document.excerpt == "Hello world."

    retrieved, citation = map_evidence_document(document)
    assert citation.excerpt == "Hello world."


def test_full_chain_metadata_flows_through() -> None:
    from app.services.evidence_chunk_mapper import evidence_chunk_to_document
    from app.services.evidence_document_mapper import map_evidence_document

    ts = datetime(2026, 6, 19, 12, 0, 0)
    chunks = chunk_text(
        "Hello world. Another sentence here.",
        source_type="test",
        source_id="1",
        title="Test Title",
        entity_type="prospect",
        prospect_id=101,
        confidence=0.9,
        tags=["a", "b"],
        chunk_size=20,
        overlap=0,
    )
    for chunk in chunks:
        document = evidence_chunk_to_document(chunk)
        retrieved, citation = map_evidence_document(document)
        assert retrieved.title == "Test Title"
        assert retrieved.confidence == 0.9
        assert citation.title == "Test Title"
        assert citation.confidence == 0.9
