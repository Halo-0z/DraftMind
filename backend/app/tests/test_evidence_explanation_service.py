"""Tests for the deterministic mock pick explanation service (RAG-v0-M3.0-B).

These tests lock down the behavior of ``build_mock_pick_explanation``:

1. Returns a ``PickExplanation``.
2. Identity fields are copied verbatim.
3. ``decision_locked`` is ``True``.
4. ``llm_can_modify_decision`` is ``False``.
5. Works with empty ``retrieved_evidence``.
6. ``manual_note`` evidence is tagged as read-only / not scored.
7. ``citation_refs`` only reference existing citations.
8. ``limitations`` reflects ``limited`` / ``insufficient`` sufficiency.
9. ``limitations`` / ``evidence_notes`` describe ``conflict_evidence``.
10. ``risk_summary`` is populated when ``risk_evidence`` is present.
11. No forbidden override / rerank / replacement field is emitted.
12. No forbidden natural-language phrase is emitted.
13. The service does not call ``ranking_engine``.
14. The service does not query the DB.
15. The service does not call OpenAI / LLM.
16. The service does not import ``httpx`` / ``requests`` / ``socket``.
17. The service does not mutate the input ``PickEvidencePackage``.
18. ``final_score`` / ``prediction_sort_score`` are only read, never
    re-emitted as new scores or adjustments.
"""

from __future__ import annotations

import copy
import json

import pytest

from app.schemas.evidence import (
    ConflictEvidence,
    EvidenceCitation,
    EvidenceSufficiency,
    MarketEvidence,
    PickEvidencePackage,
    PickExplanation,
    RankingEvidence,
    RetrievedEvidence,
    RiskEvidence,
    TeamFitEvidence,
)
from app.services.evidence_explanation_service import (
    FORBIDDEN_PHRASES,
    build_mock_pick_explanation,
)


FORBIDDEN_FIELDS = {
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _full_evidence() -> PickEvidencePackage:
    return PickEvidencePackage(
        pick_number=5,
        team_abbr="LAC",
        selected_player_id=101,
        selected_player_name="Keaton Sample",
        ranking_evidence=RankingEvidence(
            final_score=82.4,
            prediction_sort_score=84.1,
            rank_in_available_pool=1,
            score_gap_to_next=2.3,
            primary_score_drivers=["final_score led available board"],
        ),
        team_fit_evidence=TeamFitEvidence(
            team_needs=["wing defense"],
            matched_needs=["wing defense"],
            fit_strength="moderate",
            explanation_basis=["scouting fit diagnostics"],
        ),
        market_evidence=MarketEvidence(
            has_market_reference=True,
            market_expected_pick=7,
            market_range_min=5,
            market_range_max=10,
            market_pick_delta=-2,
            market_alignment_label="接近",
            market_alignment_notes=["市场预计约第 7 顺位。"],
            market_sources=["manual_projection"],
        ),
        risk_evidence=RiskEvidence(
            diagnostics_warnings=["Low-confidence imported stats used in ranking context."],
            stats_risk_flags=["low_confidence_stats"],
            overall_risk_level="moderate",
        ),
        conflict_evidence=[
            ConflictEvidence(
                type="market_model_delta",
                severity="low",
                description="DraftMind selected two picks earlier than market.",
                related_fields=["market_pick_delta"],
            )
        ],
        evidence_sufficiency=EvidenceSufficiency(level="strong"),
        citations=[
            EvidenceCitation(
                source_type="projection",
                source_id="manual_projection:101",
                title="Manual Projection 101",
                url="https://example.com/projection/101",
                confidence=0.75,
            ),
            EvidenceCitation(
                source_type="manual_note",
                source_id="note:42",
                title="Scouting note",
                evidence_source_type="manual_note",
            ),
        ],
        retrieved_evidence=[
            RetrievedEvidence(
                source_type="manual_note",
                source_id="note:42",
                title="Scouting summary",
                excerpt="Defensive versatility stands out.",
                relevance_reason="Matches team need: wing defense.",
                evidence_only=True,
            ),
            RetrievedEvidence(
                source_type="projection",
                source_id="manual_projection:101",
                excerpt="Projected as a late-lottery pick.",
                relevance_reason="Market reference for slot 5.",
            ),
        ],
    )


def _minimal_evidence() -> PickEvidencePackage:
    return PickEvidencePackage(
        pick_number=1,
        selected_player_name="Anonymous Prospect",
        evidence_sufficiency=EvidenceSufficiency(level="strong"),
    )


# ---------------------------------------------------------------------------
# 1-4. Basic contract
# ---------------------------------------------------------------------------


def test_returns_pick_explanation() -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    assert isinstance(explanation, PickExplanation)


def test_identity_fields_are_copied_verbatim() -> None:
    evidence = _full_evidence()
    explanation = build_mock_pick_explanation(evidence)
    assert explanation.pick_number == evidence.pick_number
    assert explanation.team_abbr == evidence.team_abbr
    assert explanation.selected_player_id == evidence.selected_player_id
    assert explanation.selected_player_name == evidence.selected_player_name


def test_decision_locked_is_true() -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    assert explanation.decision_locked is True


def test_llm_can_modify_decision_is_false() -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    assert explanation.llm_can_modify_decision is False


# ---------------------------------------------------------------------------
# 5. Empty retrieved_evidence
# ---------------------------------------------------------------------------


def test_works_with_empty_retrieved_evidence() -> None:
    evidence = _minimal_evidence()
    explanation = build_mock_pick_explanation(evidence)
    assert isinstance(explanation, PickExplanation)
    assert explanation.evidence_notes == []
    assert explanation.summary
    assert explanation.market_context == "市场证据有限。"


# ---------------------------------------------------------------------------
# 6. manual_note tagged as read-only
# ---------------------------------------------------------------------------


def test_manual_note_evidence_notes_tagged_read_only() -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    manual_notes = [
        n for n in explanation.evidence_notes if "manual_note" in n or "人工备注" in n
    ]
    assert manual_notes, "Expected at least one manual_note evidence note"
    for note in manual_notes:
        assert "只读证据" in note
        assert "不参与评分" in note


def test_manual_note_never_described_as_scoring_factor() -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    dumped = json.dumps(explanation.model_dump(), ensure_ascii=False).lower()
    # manual_note must not be described as a scoring factor.
    assert "manual note boost" not in dumped
    assert "加分原因" not in dumped
    assert "评分权重" not in dumped


# ---------------------------------------------------------------------------
# 7. citation_refs only reference existing citations
# ---------------------------------------------------------------------------


def test_citation_refs_only_reference_existing_citations() -> None:
    evidence = _full_evidence()
    explanation = build_mock_pick_explanation(evidence)

    valid_refs = set()
    for citation in evidence.citations:
        if citation.source_id:
            valid_refs.add(citation.source_id)
        if citation.title:
            valid_refs.add(citation.title)
        if citation.url:
            valid_refs.add(citation.url)

    for ref in explanation.citation_refs:
        assert ref in valid_refs, f"citation_ref '{ref}' not in existing citations"


def test_citation_refs_empty_when_no_citations() -> None:
    evidence = _minimal_evidence()
    explanation = build_mock_pick_explanation(evidence)
    assert explanation.citation_refs == []


# ---------------------------------------------------------------------------
# 8. limitations reflects sufficiency
# ---------------------------------------------------------------------------


def test_limitations_reflects_limited_sufficiency() -> None:
    evidence = _full_evidence()
    evidence.evidence_sufficiency = EvidenceSufficiency(
        level="limited",
        missing_sections=["market_evidence"],
        weak_sections=["team_fit_evidence"],
    )
    explanation = build_mock_pick_explanation(evidence)
    assert len(explanation.limitations) > 0
    joined = " ".join(explanation.limitations)
    assert "limited" in joined.lower() or "受限" in joined


def test_limitations_reflects_insufficient_sufficiency() -> None:
    evidence = _full_evidence()
    evidence.evidence_sufficiency = EvidenceSufficiency(level="insufficient")
    explanation = build_mock_pick_explanation(evidence)
    assert len(explanation.limitations) > 0
    joined = " ".join(explanation.limitations)
    assert "insufficient" in joined.lower() or "受限" in joined


def test_limitations_empty_when_strong_and_no_conflict() -> None:
    evidence = _minimal_evidence()
    evidence.evidence_sufficiency = EvidenceSufficiency(level="strong")
    explanation = build_mock_pick_explanation(evidence)
    assert explanation.limitations == []


# ---------------------------------------------------------------------------
# 9. conflict_evidence described in limitations
# ---------------------------------------------------------------------------


def test_conflict_evidence_described_in_limitations() -> None:
    evidence = _full_evidence()
    explanation = build_mock_pick_explanation(evidence)
    joined = " ".join(explanation.limitations)
    assert "冲突" in joined
    assert "market_model_delta" in joined


# ---------------------------------------------------------------------------
# 10. risk_summary populated
# ---------------------------------------------------------------------------


def test_risk_summary_populated_when_risk_present() -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    assert explanation.risk_summary is not None
    assert "风险" in explanation.risk_summary


def test_risk_summary_none_when_no_risk() -> None:
    evidence = _minimal_evidence()
    explanation = build_mock_pick_explanation(evidence)
    assert explanation.risk_summary is None


# ---------------------------------------------------------------------------
# 11. No forbidden fields
# ---------------------------------------------------------------------------


def test_output_has_no_forbidden_fields() -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    dumped = explanation.model_dump()
    for field in FORBIDDEN_FIELDS:
        assert field not in dumped, f"Forbidden field '{field}' in output"


# ---------------------------------------------------------------------------
# 12. No forbidden natural-language phrases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_output_does_not_contain_forbidden_phrases(phrase: str) -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    dumped = json.dumps(explanation.model_dump(), ensure_ascii=False).lower()
    assert phrase.lower() not in dumped, f"Forbidden phrase '{phrase}' in output"


def test_output_does_not_contain_should_or_better_pick() -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    dumped = json.dumps(explanation.model_dump(), ensure_ascii=False).lower()
    assert "应该选别人" not in dumped
    assert "更好的选择" not in dumped
    assert "建议改选" not in dumped
    assert "重新排序" not in dumped
    assert "提升分数" not in dumped
    assert "replacement player" not in dumped
    assert "better pick" not in dumped
    assert "rerank" not in dumped
    assert "adjust score" not in dumped


# ---------------------------------------------------------------------------
# 13. Does not call ranking_engine
# ---------------------------------------------------------------------------


def test_does_not_call_ranking_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_rank(*args: object, **kwargs: object) -> object:
        raise AssertionError(
            "build_mock_pick_explanation must not call ranking_engine"
        )

    monkeypatch.setattr(
        "app.services.ranking_engine.rank_prospects", fail_rank
    )
    # Also patch score_prospect just in case.
    monkeypatch.setattr(
        "app.services.ranking_engine.score_prospect", fail_rank
    )
    build_mock_pick_explanation(_full_evidence())


# ---------------------------------------------------------------------------
# 14. Does not query DB
# ---------------------------------------------------------------------------


def test_does_not_import_database_session() -> None:
    from app.services import evidence_explanation_service as module

    forbidden_attrs = {
        "SessionLocal",
        "get_session",
        "sessionmaker",
        "create_engine",
        "Session",
    }
    module_attrs = set(vars(module).keys())
    offending = module_attrs & forbidden_attrs
    assert not offending, f"DB-related attrs imported: {offending}"


# ---------------------------------------------------------------------------
# 15. Does not call OpenAI / LLM
# ---------------------------------------------------------------------------


def test_does_not_import_llm_client() -> None:
    from app.services import evidence_explanation_service as module

    forbidden_attrs = {"openai", "OpenAI", "ChatCompletion", "llm_service"}
    module_attrs = set(vars(module).keys())
    offending = module_attrs & forbidden_attrs
    assert not offending, f"LLM-related attrs imported: {offending}"


# ---------------------------------------------------------------------------
# 16. Does not import httpx / requests / socket
# ---------------------------------------------------------------------------


def test_does_not_import_network_modules() -> None:
    from app.services import evidence_explanation_service as module

    source = open(module.__file__, encoding="utf-8").read().lower()
    assert "import httpx" not in source
    assert "import requests" not in source
    assert "import socket" not in source
    assert "from httpx" not in source
    assert "from requests" not in source
    assert "from socket" not in source


# ---------------------------------------------------------------------------
# 17. Does not mutate input
# ---------------------------------------------------------------------------


def test_does_not_mutate_input() -> None:
    evidence = _full_evidence()
    snapshot = copy.deepcopy(evidence.model_dump())
    build_mock_pick_explanation(evidence)
    after = evidence.model_dump()
    assert after == snapshot, "Input PickEvidencePackage was mutated"


# ---------------------------------------------------------------------------
# 18. final_score / prediction_sort_score are read-only
# ---------------------------------------------------------------------------


def test_final_score_and_prediction_sort_score_are_read_only() -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    dumped = explanation.model_dump()

    # No new_score / score_adjustment / final_score_delta fields exist.
    assert "new_score" not in dumped
    assert "score_adjustment" not in dumped
    assert "final_score_delta" not in dumped
    assert "prediction_sort_delta" not in dumped

    # final_score / prediction_sort_score may appear inside text fields only
    # as read-only display values, never as output score fields.
    assert "final_score" not in dumped  # not a top-level field
    assert "prediction_sort_score" not in dumped  # not a top-level field


def test_summary_mentions_final_score_as_display_only() -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    # final_score may appear in summary/key_reasons as a display value.
    text = explanation.summary + " ".join(explanation.key_reasons)
    assert "82.4" in text  # the final_score value
    # But must not describe it as adjustable.
    assert "adjust" not in text.lower()
    assert "boost" not in text.lower()


# ---------------------------------------------------------------------------
# Additional: summary / key_reasons / market_context structure
# ---------------------------------------------------------------------------


def test_summary_is_non_empty_and_bounded() -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    assert 1 <= len(explanation.summary) <= 1200


def test_key_reasons_bounded_to_5() -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    assert 0 <= len(explanation.key_reasons) <= 5


def test_market_context_populated_when_market_present() -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    assert explanation.market_context is not None
    assert "市场" in explanation.market_context or "顺位" in explanation.market_context


def test_evidence_notes_bounded_to_6() -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    assert 0 <= len(explanation.evidence_notes) <= 6


def test_citation_refs_bounded_to_10() -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    assert 0 <= len(explanation.citation_refs) <= 10


def test_limitations_bounded_to_5() -> None:
    explanation = build_mock_pick_explanation(_full_evidence())
    assert 0 <= len(explanation.limitations) <= 5


def test_minimal_evidence_still_produces_valid_explanation() -> None:
    evidence = _minimal_evidence()
    explanation = build_mock_pick_explanation(evidence)
    assert isinstance(explanation, PickExplanation)
    assert explanation.pick_number == 1
    assert explanation.selected_player_name == "Anonymous Prospect"
    assert explanation.summary
    assert explanation.market_context == "市场证据有限。"
    assert explanation.risk_summary is None
    assert explanation.evidence_notes == []
    assert explanation.citation_refs == []
    assert explanation.limitations == []


# ---------------------------------------------------------------------------
# 19. Poisoned input: dangerous phrases in input text must be redacted
# ---------------------------------------------------------------------------
#
# The service must not blindly copy text from the input ``PickEvidencePackage``
# into the output ``PickExplanation``.  If any input-derived text contains a
# forbidden phrase, it must be scrubbed (replaced with ``[redacted]``) so the
# output never carries dangerous semantics.
# ---------------------------------------------------------------------------


def _poisoned_evidence() -> PickEvidencePackage:
    """Return an evidence package whose text fields are laced with forbidden
    phrases.  Every text-bearing field that the mock service reads is
    poisoned with at least one Chinese and one English forbidden phrase."""
    return PickEvidencePackage(
        pick_number=3,
        team_abbr="CHA",
        selected_player_id=42,
        selected_player_name="Poisoned Prospect",
        ranking_evidence=RankingEvidence(
            final_score=70.0,
            prediction_sort_score=71.0,
            rank_in_available_pool=2,
        ),
        team_fit_evidence=TeamFitEvidence(
            team_needs=["wing defense"],
            matched_needs=["wing defense 建议改选 替代人选"],
            fit_strength="moderate",
        ),
        market_evidence=MarketEvidence(
            has_market_reference=True,
            market_expected_pick=4,
            market_range_min=3,
            market_range_max=6,
            market_pick_delta=-1,
            market_alignment_label="接近 better pick",
            market_alignment_notes=[
                "市场预计约第 4 顺位，但有人说应该选别人 rerank candidates"
            ],
            market_sources=["manual_projection"],
        ),
        risk_evidence=RiskEvidence(
            diagnostics_warnings=["Low-confidence stats; adjust score to fix"],
            market_risk_flags=["market rerank signal"],
            stats_risk_flags=["low_confidence_stats"],
            data_quality_flags=["data quality: replacement player flagged"],
            overall_risk_level="moderate score boost",
        ),
        conflict_evidence=[
            ConflictEvidence(
                type="market_model_delta better pick",
                severity="low should have selected",
                description="DraftMind reached earlier; 建议改选 替代人选。",
                related_fields=["market_pick_delta"],
            )
        ],
        evidence_sufficiency=EvidenceSufficiency(
            level="limited",
            missing_sections=["market_evidence 提升分数"],
            weak_sections=["team_fit_evidence 加权"],
            explanation_limits=[
                "evidence limited; rerank not allowed",
                "manual note boost not permitted",
            ],
        ),
        citations=[
            EvidenceCitation(
                source_type="manual_note",
                source_id="note:1",
                title="Scouting note",
            ),
        ],
        retrieved_evidence=[
            RetrievedEvidence(
                source_type="manual_note",
                source_id="note:1",
                title="Scouting summary 建议改选",
                excerpt="Defensive versatility; better pick available.",
                relevance_reason="Matches team need; rerank suggested.",
                evidence_only=True,
            ),
            RetrievedEvidence(
                source_type="projection",
                source_id="proj:1",
                excerpt="Projected late-lottery; replacement player risk.",
                relevance_reason="Market reference; adjust score context.",
            ),
        ],
    )


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_poisoned_input_does_not_leak_forbidden_phrases(phrase: str) -> None:
    """Every forbidden phrase must be redacted from the output even when the
    input evidence package contains it."""
    evidence = _poisoned_evidence()
    explanation = build_mock_pick_explanation(evidence)
    dumped = json.dumps(explanation.model_dump(), ensure_ascii=False).lower()
    assert phrase.lower() not in dumped, (
        f"Forbidden phrase '{phrase}' leaked from poisoned input into output."
    )


def test_poisoned_input_all_fields_redacted() -> None:
    """Comprehensive check: dump the full output JSON and assert none of the
    forbidden phrases appear anywhere."""
    evidence = _poisoned_evidence()
    explanation = build_mock_pick_explanation(evidence)
    dumped = json.dumps(explanation.model_dump(), ensure_ascii=False).lower()

    for phrase in FORBIDDEN_PHRASES:
        assert phrase.lower() not in dumped, (
            f"Forbidden phrase '{phrase}' found in output."
        )

    # The output should contain [redacted] markers where phrases were scrubbed.
    assert "[redacted]" in dumped


def test_poisoned_market_alignment_label_is_redacted() -> None:
    evidence = _poisoned_evidence()
    explanation = build_mock_pick_explanation(evidence)
    assert explanation.market_context is not None
    assert "better pick" not in explanation.market_context.lower()
    assert "[redacted]" in explanation.market_context


def test_poisoned_market_alignment_notes_are_redacted() -> None:
    evidence = _poisoned_evidence()
    explanation = build_mock_pick_explanation(evidence)
    joined_reasons = " ".join(explanation.key_reasons).lower()
    assert "应该选别人" not in joined_reasons
    assert "rerank" not in joined_reasons
    assert "[redacted]" in " ".join(explanation.key_reasons)


def test_poisoned_team_fit_matched_needs_are_redacted() -> None:
    evidence = _poisoned_evidence()
    explanation = build_mock_pick_explanation(evidence)
    joined_reasons = " ".join(explanation.key_reasons).lower()
    assert "建议改选" not in joined_reasons
    assert "替代人选" not in joined_reasons


def test_poisoned_risk_flags_are_redacted() -> None:
    evidence = _poisoned_evidence()
    explanation = build_mock_pick_explanation(evidence)
    assert explanation.risk_summary is not None
    lowered = explanation.risk_summary.lower()
    assert "adjust score" not in lowered
    assert "rerank" not in lowered
    assert "replacement player" not in lowered
    assert "score boost" not in lowered
    assert "[redacted]" in explanation.risk_summary


def test_poisoned_retrieved_evidence_is_redacted() -> None:
    evidence = _poisoned_evidence()
    explanation = build_mock_pick_explanation(evidence)
    joined_notes = " ".join(explanation.evidence_notes).lower()
    assert "建议改选" not in joined_notes
    assert "better pick" not in joined_notes
    assert "rerank" not in joined_notes
    assert "replacement player" not in joined_notes
    assert "adjust score" not in joined_notes
    assert "[redacted]" in " ".join(explanation.evidence_notes)


def test_poisoned_conflict_evidence_is_redacted() -> None:
    evidence = _poisoned_evidence()
    explanation = build_mock_pick_explanation(evidence)
    joined_limits = " ".join(explanation.limitations).lower()
    assert "better pick" not in joined_limits
    assert "should have selected" not in joined_limits
    assert "建议改选" not in joined_limits
    assert "替代人选" not in joined_limits
    assert "[redacted]" in " ".join(explanation.limitations)


def test_poisoned_sufficiency_sections_are_redacted() -> None:
    evidence = _poisoned_evidence()
    explanation = build_mock_pick_explanation(evidence)
    joined_limits = " ".join(explanation.limitations).lower()
    assert "提升分数" not in joined_limits
    assert "加权" not in joined_limits
    assert "rerank" not in joined_limits
    assert "manual note boost" not in joined_limits


def test_sanitize_text_replaces_all_forbidden_phrases() -> None:
    """Direct unit test of the ``_sanitize_text`` helper."""
    from app.services.evidence_explanation_service import _sanitize_text

    assert _sanitize_text(None) == ""
    assert _sanitize_text("") == ""
    assert _sanitize_text("clean text") == "clean text"

    # Chinese phrases
    assert _sanitize_text("应该选别人") == "[redacted]"
    assert _sanitize_text("text 建议改选 more") == "text [redacted] more"
    assert _sanitize_text("替代人选 here") == "[redacted] here"

    # English phrases (case-insensitive)
    assert _sanitize_text("BETTER PICK") == "[redacted]"
    assert _sanitize_text("Rerank now") == "[redacted] now"
    assert _sanitize_text("adjust score please") == "[redacted] please"

    # Multiple phrases in one string
    result = _sanitize_text("建议改选 and rerank too")
    assert "建议改选" not in result
    assert "rerank" not in result.lower()
    assert result.count("[redacted]") == 2


def test_poisoned_input_does_not_mutate_input() -> None:
    """Sanitization must not mutate the input evidence package."""
    evidence = _poisoned_evidence()
    snapshot = copy.deepcopy(evidence.model_dump())
    build_mock_pick_explanation(evidence)
    after = evidence.model_dump()
    assert after == snapshot, "Input PickEvidencePackage was mutated during sanitization"


# ---------------------------------------------------------------------------
# 20. Poisoned citations: source_id / title / url must be redacted
# ---------------------------------------------------------------------------


def _poisoned_citation_evidence() -> PickEvidencePackage:
    """Return an evidence package whose citations contain forbidden phrases
    in ``source_id``, ``title``, and ``url``."""
    return PickEvidencePackage(
        pick_number=7,
        team_abbr="ATL",
        selected_player_id=99,
        selected_player_name="Cited Prospect",
        evidence_sufficiency=EvidenceSufficiency(level="strong"),
        citations=[
            EvidenceCitation(
                source_type="manual_note",
                source_id="note:better pick",
                title="Scouting note",
                url="https://example.com/normal",
            ),
            EvidenceCitation(
                source_type="projection",
                source_id="proj:1",
                title="建议改选",
                url="https://example.com/normal-2",
            ),
            EvidenceCitation(
                source_type="news",
                source_id="news:1",
                title="Normal title",
                url="https://example.com/rerank",
            ),
            EvidenceCitation(
                source_type="manual_note",
                source_id="note:replacement player",
                title="Another 建议改选 title",
                url="https://example.com/adjust%20score",
            ),
        ],
    )


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_poisoned_citations_do_not_leak_forbidden_phrases(phrase: str) -> None:
    """Forbidden phrases in citation source_id / title / url must be redacted
    from the full output JSON."""
    evidence = _poisoned_citation_evidence()
    json_output = build_mock_pick_explanation(evidence).model_dump_json().lower()
    assert phrase.lower() not in json_output, (
        f"Forbidden phrase '{phrase}' leaked from citation into output JSON."
    )


def test_poisoned_citation_refs_are_redacted() -> None:
    evidence = _poisoned_citation_evidence()
    explanation = build_mock_pick_explanation(evidence)
    joined_refs = " ".join(explanation.citation_refs).lower()
    assert "better pick" not in joined_refs
    assert "建议改选" not in joined_refs
    assert "rerank" not in joined_refs
    assert "replacement player" not in joined_refs
    assert "adjust score" not in joined_refs
    assert "[redacted]" in " ".join(explanation.citation_refs)


def test_poisoned_citation_refs_still_reference_existing_citations() -> None:
    """Even after redaction, citation_refs must still originate from the
    input citations — no citation is fabricated."""
    evidence = _poisoned_citation_evidence()
    explanation = build_mock_pick_explanation(evidence)

    # Build the set of valid original refs (before sanitization).
    valid_refs = set()
    for citation in evidence.citations:
        if citation.source_id:
            valid_refs.add(citation.source_id)
        if citation.title:
            valid_refs.add(citation.title)
        if citation.url:
            valid_refs.add(citation.url)

    # Each output ref must either be an exact original ref (if it contained
    # no forbidden phrase) or a redacted version of an original ref.
    # We verify provenance: every output ref must be derivable from some
    # original citation field by applying _sanitize_text.
    from app.services.evidence_explanation_service import _sanitize_text

    valid_sanitized_refs = set()
    for citation in evidence.citations:
        for field in (citation.source_id, citation.title, citation.url):
            if field:
                valid_sanitized_refs.add(_sanitize_text(field))

    for ref in explanation.citation_refs:
        assert ref in valid_sanitized_refs, (
            f"citation_ref '{ref}' not derivable from any input citation field."
        )


def test_poisoned_citation_refs_count_matches_citations() -> None:
    """All 4 poisoned citations should produce 4 refs (none dropped)."""
    evidence = _poisoned_citation_evidence()
    explanation = build_mock_pick_explanation(evidence)
    assert len(explanation.citation_refs) == 4


def test_clean_citations_are_not_redacted() -> None:
    """Citations without forbidden phrases must pass through unchanged."""
    evidence = PickEvidencePackage(
        pick_number=1,
        selected_player_name="Clean Prospect",
        evidence_sufficiency=EvidenceSufficiency(level="strong"),
        citations=[
            EvidenceCitation(
                source_type="projection",
                source_id="proj:clean-1",
                title="Clean Projection",
                url="https://example.com/clean",
            ),
        ],
    )
    explanation = build_mock_pick_explanation(evidence)
    assert explanation.citation_refs == ["proj:clean-1"]
    assert "[redacted]" not in " ".join(explanation.citation_refs)
