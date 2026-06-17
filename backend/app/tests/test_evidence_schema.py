import pytest
from pydantic import ValidationError

from app.schemas.evidence import (
    ConflictEvidence,
    EvidenceCitation,
    EvidenceSufficiency,
    ManualNote,
    MarketEvidence,
    PickEvidencePackage,
    RankingEvidence,
    RetrievedEvidence,
    RiskEvidence,
    TeamFitEvidence,
)


def test_pick_evidence_package_can_be_created_and_dumped() -> None:
    package = PickEvidencePackage(
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
                confidence=0.75,
            )
        ],
    )

    dumped = package.model_dump()

    assert dumped["pick_number"] == 5
    assert dumped["selected_player_name"] == "Keaton Sample"
    assert dumped["ranking_evidence"]["final_score"] == 82.4
    assert dumped["market_evidence"]["has_market_reference"] is True
    assert package.model_dump_json()


def test_pick_evidence_defaults_lock_decision_boundary() -> None:
    package = PickEvidencePackage(
        pick_number=25,
        selected_player_name="Mark Mitchell",
        evidence_sufficiency=EvidenceSufficiency(level="moderate"),
    )

    assert package.decision_locked is True
    assert package.decision_source == "structured_simulation"
    assert package.llm_can_modify_decision is False


def test_list_defaults_are_not_shared_between_instances() -> None:
    first = PickEvidencePackage(
        pick_number=1,
        selected_player_name="First Player",
        evidence_sufficiency=EvidenceSufficiency(level="limited"),
    )
    second = PickEvidencePackage(
        pick_number=2,
        selected_player_name="Second Player",
        evidence_sufficiency=EvidenceSufficiency(level="limited"),
    )

    first.conflict_evidence.append(
        ConflictEvidence(
            type="market_missing",
            severity="medium",
            description="No market reference found.",
        )
    )
    first.citations.append(EvidenceCitation(source_type="manual_note"))
    first.evidence_sufficiency.missing_sections.append("market_evidence")

    assert len(first.conflict_evidence) == 1
    assert second.conflict_evidence == []
    assert len(first.citations) == 1
    assert second.citations == []
    assert first.evidence_sufficiency.missing_sections == ["market_evidence"]
    assert second.evidence_sufficiency.missing_sections == []


def test_market_missing_can_be_represented_as_limited_evidence() -> None:
    package = PickEvidencePackage(
        pick_number=32,
        team_abbr="BOS",
        selected_player_name="Labaron Sample",
        market_evidence=MarketEvidence(
            has_market_reference=False,
            market_alignment_label="无市场参考",
            market_alignment_notes=["暂无市场顺位参考。"],
        ),
        evidence_sufficiency=EvidenceSufficiency(
            level="limited",
            missing_sections=["market_evidence"],
            explanation_limits=["No stable market projection is available."],
        ),
    )

    assert package.market_evidence is not None
    assert package.market_evidence.has_market_reference is False
    assert package.evidence_sufficiency.level == "limited"
    assert "market_evidence" in package.evidence_sufficiency.missing_sections


def test_schema_does_not_expose_reranking_or_replacement_fields() -> None:
    forbidden_fields = {
        "recommended_player",
        "replacement_player",
        "new_selected_player",
        "rerank_score",
        "new_score",
    }

    assert forbidden_fields.isdisjoint(PickEvidencePackage.model_fields)


def test_evidence_citation_carries_source_metadata() -> None:
    citation = EvidenceCitation(
        source_type="news_article",
        source_id="news:42",
        title="Workout report",
        url="https://example.test/workout",
        date="2026-06-16",
        excerpt="Team officials attended the workout.",
        confidence=0.82,
        evidence_source_type="news",
        entity_type="prospect",
        entity_id=101,
        publisher="Example Sports",
        author="Analyst Name",
        retrieved_at="2026-06-16T12:00:00Z",
        freshness_days=1,
        relevance_reason="Mentions selected player by name.",
    )

    dumped = citation.model_dump()

    assert dumped["evidence_source_type"] == "news"
    assert dumped["entity_type"] == "prospect"
    assert dumped["entity_id"] == 101
    assert dumped["publisher"] == "Example Sports"
    assert dumped["author"] == "Analyst Name"
    assert dumped["freshness_days"] == 1
    assert dumped["relevance_reason"] == "Mentions selected player by name."
    assert dumped["evidence_only"] is True


def test_evidence_citation_evidence_only_defaults_to_true() -> None:
    citation = EvidenceCitation(source_type="manual_note")

    assert citation.evidence_only is True


def test_evidence_citation_rejects_negative_freshness_days() -> None:
    with pytest.raises(ValidationError):
        EvidenceCitation(source_type="news_article", freshness_days=-1)


def test_evidence_citation_rejects_confidence_outside_zero_to_one() -> None:
    with pytest.raises(ValidationError):
        EvidenceCitation(source_type="news_article", confidence=1.01)

    with pytest.raises(ValidationError):
        EvidenceCitation(source_type="news_article", confidence=-0.01)


def test_evidence_citation_does_not_expose_scoring_or_replacement_fields() -> None:
    forbidden_fields = {
        "recommended_player",
        "replacement_player",
        "new_selected_player",
        "rerank_score",
        "new_score",
        "score_adjustment",
        "ranking_weight",
    }

    assert forbidden_fields.isdisjoint(EvidenceCitation.model_fields)


def test_retrieved_evidence_can_be_created() -> None:
    evidence = RetrievedEvidence(
        source_type="scouting_report",
        source_id="scouting:101:chunk-1",
        citation=EvidenceCitation(
            source_type="scouting_report",
            source_id="scouting:101",
            title="Prospect scouting profile",
            evidence_source_type="scouting",
        ),
        entity_type="prospect",
        entity_id=101,
        title="Wing creation summary",
        excerpt="The player showed advanced passing feel in transition.",
        url="https://example.test/scouting/101",
        date="2026-06-16",
        confidence=0.8,
        retrieval_score=0.72,
        freshness_days=3,
        relevance_reason="Explains a selected player's creation upside.",
        conflict_note="Does not address shooting risk.",
    )

    dumped = evidence.model_dump()

    assert dumped["source_type"] == "scouting_report"
    assert dumped["excerpt"] == "The player showed advanced passing feel in transition."
    assert dumped["citation"]["source_id"] == "scouting:101"
    assert dumped["evidence_only"] is True


def test_retrieved_evidence_requires_excerpt() -> None:
    with pytest.raises(ValidationError):
        RetrievedEvidence(source_type="news_article")


def test_retrieved_evidence_evidence_only_defaults_to_true_and_rejects_false() -> None:
    evidence = RetrievedEvidence(
        source_type="manual_note",
        excerpt="The note only explains the existing pick.",
    )

    assert evidence.evidence_only is True

    with pytest.raises(ValidationError):
        RetrievedEvidence(
            source_type="manual_note",
            excerpt="The note only explains the existing pick.",
            evidence_only=False,
        )


def test_retrieved_evidence_rejects_confidence_outside_zero_to_one() -> None:
    with pytest.raises(ValidationError):
        RetrievedEvidence(source_type="news_article", excerpt="Text.", confidence=1.01)

    with pytest.raises(ValidationError):
        RetrievedEvidence(source_type="news_article", excerpt="Text.", confidence=-0.01)


def test_retrieved_evidence_rejects_negative_retrieval_score() -> None:
    with pytest.raises(ValidationError):
        RetrievedEvidence(
            source_type="scouting_report",
            excerpt="Text.",
            retrieval_score=-0.01,
        )


def test_retrieved_evidence_rejects_negative_freshness_days() -> None:
    with pytest.raises(ValidationError):
        RetrievedEvidence(
            source_type="news_article",
            excerpt="Text.",
            freshness_days=-1,
        )


def test_pick_evidence_defaults_retrieved_evidence_to_empty_list() -> None:
    package = PickEvidencePackage(
        pick_number=10,
        selected_player_name="Default Player",
        evidence_sufficiency=EvidenceSufficiency(level="moderate"),
    )

    assert package.retrieved_evidence == []


def test_pick_evidence_retrieved_evidence_lists_are_not_shared() -> None:
    first = PickEvidencePackage(
        pick_number=11,
        selected_player_name="First Player",
        evidence_sufficiency=EvidenceSufficiency(level="moderate"),
    )
    second = PickEvidencePackage(
        pick_number=12,
        selected_player_name="Second Player",
        evidence_sufficiency=EvidenceSufficiency(level="moderate"),
    )

    first.retrieved_evidence.append(
        RetrievedEvidence(
            source_type="manual_note",
            excerpt="This note belongs only to the first package.",
        )
    )

    assert len(first.retrieved_evidence) == 1
    assert second.retrieved_evidence == []


def test_retrieved_evidence_does_not_expose_scoring_or_replacement_fields() -> None:
    forbidden_fields = {
        "recommended_player",
        "replacement_player",
        "new_selected_player",
        "rerank_score",
        "new_score",
        "score_adjustment",
        "ranking_weight",
        "selection_override",
    }

    assert forbidden_fields.isdisjoint(RetrievedEvidence.model_fields)


def test_manual_note_can_be_created() -> None:
    note = ManualNote(
        year=2026,
        entity_type="prospect",
        entity_id=101,
        prospect_id=101,
        title="Workout observation",
        body="The player showed advanced passing feel in transition.",
        summary="Passing feel note.",
        author="Analyst Name",
        source_url="https://example.test/note/101",
        source_date="2026-06-16",
        confidence=0.8,
        tags=["passing", "transition"],
        relevance_reason="Explains a selected player's creation upside.",
    )

    dumped = note.model_dump()

    assert dumped["year"] == 2026
    assert dumped["entity_type"] == "prospect"
    assert dumped["entity_id"] == 101
    assert dumped["prospect_id"] == 101
    assert dumped["title"] == "Workout observation"
    assert dumped["body"] == "The player showed advanced passing feel in transition."
    assert dumped["source"] == "manual"
    assert dumped["confidence"] == 0.8
    assert dumped["tags"] == ["passing", "transition"]
    assert dumped["evidence_only"] is True


def test_manual_note_rejects_year_below_range() -> None:
    with pytest.raises(ValidationError):
        ManualNote(
            year=1899,
            entity_type="prospect",
            title="Title",
            body="Body",
        )


def test_manual_note_rejects_year_above_range() -> None:
    with pytest.raises(ValidationError):
        ManualNote(
            year=2101,
            entity_type="prospect",
            title="Title",
            body="Body",
        )


def test_manual_note_entity_type_only_allows_enum_values() -> None:
    allowed = {
        "prospect",
        "team",
        "pick",
        "market_projection",
        "scouting_profile",
        "news_article",
        "simulation_context",
    }
    assert set(ManualNote.model_fields["entity_type"].annotation.__args__) == allowed

    with pytest.raises(ValidationError):
        ManualNote(
            year=2026,
            entity_type="unknown_entity",
            title="Title",
            body="Body",
        )


def test_manual_note_title_is_required_and_cannot_be_empty() -> None:
    with pytest.raises(ValidationError):
        ManualNote(year=2026, entity_type="prospect", title="", body="Body")

    with pytest.raises(ValidationError):
        ManualNote(year=2026, entity_type="prospect", body="Body")


def test_manual_note_body_is_required_and_cannot_be_empty() -> None:
    with pytest.raises(ValidationError):
        ManualNote(year=2026, entity_type="prospect", title="Title", body="")

    with pytest.raises(ValidationError):
        ManualNote(year=2026, entity_type="prospect", title="Title")


def test_manual_note_body_rejects_max_length_overflow() -> None:
    with pytest.raises(ValidationError):
        ManualNote(
            year=2026,
            entity_type="prospect",
            title="Title",
            body="x" * 8001,
        )


def test_manual_note_confidence_must_be_within_zero_to_one() -> None:
    with pytest.raises(ValidationError):
        ManualNote(
            year=2026,
            entity_type="prospect",
            title="Title",
            body="Body",
            confidence=1.01,
        )

    with pytest.raises(ValidationError):
        ManualNote(
            year=2026,
            entity_type="prospect",
            title="Title",
            body="Body",
            confidence=-0.01,
        )


def test_manual_note_pick_no_must_be_within_one_to_sixty() -> None:
    with pytest.raises(ValidationError):
        ManualNote(
            year=2026,
            entity_type="pick",
            title="Title",
            body="Body",
            pick_no=0,
        )

    with pytest.raises(ValidationError):
        ManualNote(
            year=2026,
            entity_type="pick",
            title="Title",
            body="Body",
            pick_no=61,
        )


def test_manual_note_evidence_only_defaults_to_true_and_rejects_false() -> None:
    note = ManualNote(
        year=2026,
        entity_type="prospect",
        title="Title",
        body="Body",
    )

    assert note.evidence_only is True

    with pytest.raises(ValidationError):
        ManualNote(
            year=2026,
            entity_type="prospect",
            title="Title",
            body="Body",
            evidence_only=False,
        )


def test_manual_note_tags_default_list_is_not_shared_between_instances() -> None:
    first = ManualNote(
        year=2026,
        entity_type="prospect",
        title="First Note",
        body="Body",
    )
    second = ManualNote(
        year=2026,
        entity_type="prospect",
        title="Second Note",
        body="Body",
    )

    first.tags.append("passing")

    assert first.tags == ["passing"]
    assert second.tags == []
    assert first.tags is not second.tags


def test_manual_note_does_not_expose_scoring_or_replacement_or_override_fields() -> None:
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
    }

    assert forbidden_fields.isdisjoint(ManualNote.model_fields)


def test_manual_note_source_defaults_to_manual() -> None:
    note = ManualNote(
        year=2026,
        entity_type="prospect",
        title="Title",
        body="Body",
    )

    assert note.source == "manual"
