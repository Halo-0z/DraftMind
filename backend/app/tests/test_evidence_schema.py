import pytest
from pydantic import ValidationError

from app.schemas.evidence import (
    ConflictEvidence,
    EvidenceCitation,
    EvidenceSufficiency,
    MarketEvidence,
    PickEvidencePackage,
    RankingEvidence,
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
