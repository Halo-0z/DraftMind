from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.simulation import SimulateResponse, SimulatedPickRead


class RankingEvidence(BaseModel):
    final_score: float | None = None
    prediction_sort_score: float | None = None
    rank_in_available_pool: int | None = Field(default=None, ge=1)
    score_gap_to_next: float | None = None
    score_gap_to_previous: float | None = None
    confidence_band: str | None = None
    primary_score_drivers: list[str] = Field(default_factory=list)


class TeamFitEvidence(BaseModel):
    team_needs: list[str] = Field(default_factory=list)
    matched_needs: list[str] = Field(default_factory=list)
    unmatched_needs: list[str] = Field(default_factory=list)
    fit_strength: str | None = None
    same_team_projection_priority: bool = False
    explanation_basis: list[str] = Field(default_factory=list)


class MarketEvidence(BaseModel):
    has_market_reference: bool
    # M4-D: upper bound widened from 60 to 100 for second-round / UDFA-bubble.
    market_expected_pick: int | None = Field(default=None, ge=1, le=100)
    market_range_min: int | None = Field(default=None, ge=1, le=100)
    market_range_max: int | None = Field(default=None, ge=1, le=100)
    market_pick_delta: int | None = None
    market_alignment_label: str | None = None
    market_alignment_notes: list[str] = Field(default_factory=list)
    market_sources: list[str] = Field(default_factory=list)


class RiskEvidence(BaseModel):
    diagnostics_warnings: list[str] = Field(default_factory=list)
    market_risk_flags: list[str] = Field(default_factory=list)
    stats_risk_flags: list[str] = Field(default_factory=list)
    data_quality_flags: list[str] = Field(default_factory=list)
    overall_risk_level: str | None = None


class ConflictEvidence(BaseModel):
    type: str
    severity: str
    description: str
    related_fields: list[str] = Field(default_factory=list)


class EvidenceSufficiency(BaseModel):
    level: str
    missing_sections: list[str] = Field(default_factory=list)
    weak_sections: list[str] = Field(default_factory=list)
    explanation_limits: list[str] = Field(default_factory=list)


class EvidenceCitation(BaseModel):
    source_type: str
    source_id: str | None = None
    title: str | None = None
    url: str | None = None
    date: str | None = None
    excerpt: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_source_type: str | None = None
    entity_type: str | None = None
    entity_id: int | str | None = None
    publisher: str | None = None
    author: str | None = None
    retrieved_at: str | None = None
    freshness_days: int | None = Field(default=None, ge=0)
    relevance_reason: str | None = None
    evidence_only: Literal[True] = True


class RetrievedEvidence(BaseModel):
    source_type: str
    source_id: str | None = None
    citation: EvidenceCitation | None = None

    entity_type: str | None = None
    entity_id: int | str | None = None

    title: str | None = None
    excerpt: str
    url: str | None = None
    date: str | None = None

    confidence: float | None = Field(default=None, ge=0, le=1)
    retrieval_score: float | None = Field(default=None, ge=0)
    freshness_days: int | None = Field(default=None, ge=0)

    relevance_reason: str | None = None
    conflict_note: str | None = None
    evidence_only: Literal[True] = True


class ManualNote(BaseModel):
    note_id: int | str | None = None
    year: int = Field(ge=1900, le=2100)

    entity_type: Literal[
        "prospect",
        "team",
        "pick",
        "market_projection",
        "scouting_profile",
        "news_article",
        "simulation_context",
    ]
    entity_id: int | str | None = None

    prospect_id: int | None = None
    team_id: int | None = None
    pick_no: int | None = Field(default=None, ge=1, le=60)

    title: str = Field(min_length=1, max_length=240)
    body: str = Field(min_length=1, max_length=8000)
    summary: str | None = Field(default=None, max_length=500)

    source: str = Field(default="manual", min_length=1, max_length=80)
    author: str | None = Field(default=None, max_length=120)
    source_url: str | None = None
    source_date: str | None = None

    confidence: float | None = Field(default=None, ge=0, le=1)
    tags: list[str] = Field(default_factory=list)
    relevance_reason: str | None = Field(default=None, max_length=500)

    evidence_only: Literal[True] = True
    created_at: str | None = None
    updated_at: str | None = None


class PickEvidencePackage(BaseModel):
    pick_number: int = Field(ge=1, le=60)
    team_abbr: str | None = None
    selected_player_id: int | None = None
    selected_player_name: str
    decision_locked: Literal[True] = True
    decision_source: Literal["structured_simulation"] = "structured_simulation"
    llm_can_modify_decision: Literal[False] = False

    ranking_evidence: RankingEvidence | None = None
    team_fit_evidence: TeamFitEvidence | None = None
    market_evidence: MarketEvidence | None = None
    risk_evidence: RiskEvidence | None = None
    conflict_evidence: list[ConflictEvidence] = Field(default_factory=list)
    evidence_sufficiency: EvidenceSufficiency
    citations: list[EvidenceCitation] = Field(default_factory=list)
    retrieved_evidence: list[RetrievedEvidence] = Field(default_factory=list)
    narrative_explanation: str | None = None


class PickEvidenceRequest(BaseModel):
    simulation: SimulateResponse
    pick: SimulatedPickRead
    manual_notes: list[ManualNote] = Field(default_factory=list, max_length=10)


# RAG-v0-M3.0-A: PickExplanation schema.
#
# This schema is the *only* shape an LLM is allowed to emit when explaining a
# pick.  It is deliberately display-only:
#
# - ``decision_locked`` / ``llm_can_modify_decision`` are Literal-locked so the
#   LLM cannot express "I changed the pick" in a type-carrying way.
# - There are no fields for replacement players, reranking, score overrides, or
#   selection overrides.  ``citation_refs`` may only reference existing
#   citations; the LLM cannot invent new evidence.
# - ``summary`` / ``key_reasons`` / ``market_context`` / ``risk_summary`` /
#   ``evidence_notes`` / ``limitations`` are bounded by max_length so the LLM
#   cannot smuggle a full alternative draft board through free text.


class PickExplanation(BaseModel):
    # RAG-v0-M3.0-A: extra="forbid" ensures any unknown field — including any
    # dangerous override / rerank / replacement field — raises ValidationError
    # instead of being silently ignored.  This is the strict boundary for LLM
    # output: the model may only emit the fields listed below.
    model_config = ConfigDict(extra="forbid")

    pick_number: int = Field(ge=1, le=60)
    team_abbr: str | None = None
    selected_player_id: int | None = None
    selected_player_name: str

    decision_locked: Literal[True] = True
    llm_can_modify_decision: Literal[False] = False

    summary: str = Field(min_length=1, max_length=1200)
    key_reasons: list[str] = Field(default_factory=list, max_length=5)
    market_context: str | None = Field(default=None, max_length=800)
    risk_summary: str | None = Field(default=None, max_length=800)
    evidence_notes: list[str] = Field(default_factory=list, max_length=6)
    citation_refs: list[str] = Field(default_factory=list, max_length=10)
    limitations: list[str] = Field(default_factory=list, max_length=5)


# RAG-v1-B1: EvidenceDocumentRead — read-only knowledge source contract.
#
# This schema is the unified read shape for future knowledge sources
# (ScoutingReport / NewsArticle / ManualNote DB rows).  It is deliberately
# display-only and retrieval-only:
#
# - ``evidence_only`` is Literal-locked to ``True`` so any consumer can tell
#   at the type level that this document must never feed back into scoring,
#   selection, or ranking.
# - There are no fields for replacement players, reranking, score overrides,
#   or selection overrides.
# - ``excerpt`` is required (mirrors ``RetrievedEvidence.excerpt``) so the
#   document always carries a human-readable snippet for the evidence panel.
# - ``title`` is optional because some sources (e.g. raw ScoutingReport rows)
#   may not have a dedicated title column; callers can derive one.
#
# This schema does NOT touch ``PickEvidencePackage`` / ``PickExplanation``
# behavior.  It is only consumed by ``evidence_document_mapper`` to produce
# ``RetrievedEvidence`` / ``EvidenceCitation`` instances.


class EvidenceDocumentRead(BaseModel):
    source_type: str
    source_id: str | None = None

    entity_type: str | None = None
    entity_id: int | str | None = None

    prospect_id: int | None = None
    prospect_name: str | None = None
    team_id: int | None = None
    team_abbr: str | None = None
    year: int | None = Field(default=None, ge=1900, le=2100)

    title: str | None = None
    excerpt: str
    url: str | None = None

    source_name: str | None = None
    publisher: str | None = None
    author: str | None = None
    published_at: str | None = None

    confidence: float | None = Field(default=None, ge=0, le=1)
    retrieval_score: float | None = Field(default=None, ge=0)
    freshness_days: int | None = Field(default=None, ge=0)

    relevance_reason: str | None = None
    conflict_note: str | None = None
    tags: list[str] = Field(default_factory=list)

    evidence_only: Literal[True] = True


# RAG-v2-M1-B: EvidenceChunk — a semantic retrieval unit.
#
# An EvidenceChunk represents a slice of a knowledge source document (e.g. a
# ManualNote body split into 200-500 char segments).  It is the granular unit
# that future semantic retrieval (M2) will embed and search.
#
# Safety design (mirrors EvidenceDocumentRead):
#
# - ``evidence_only`` is Literal-locked to ``True`` so any consumer can tell
#   at the type level that this chunk must never feed back into scoring,
#   selection, or ranking.
# - ``extra="forbid"`` ensures no dangerous override / rerank / replacement
#   field can sneak in via construction.
# - ``retrieval_score`` is bounded to [0, 1] and is display-only — it never
#   participates in decision logic.
# - ``content`` is required and non-empty so every chunk carries meaningful
#   text for explanation.
# - ``chunk_index`` must be < ``chunk_count`` (validated via model_validator).
#
# This schema does NOT touch ``PickEvidencePackage`` / ``PickExplanation``
# behavior.  It is only consumed by ``evidence_chunk_mapper`` to produce an
# ``EvidenceDocumentRead``, which then flows through the existing
# ``map_evidence_document`` pipeline.


class EvidenceChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Identity
    chunk_id: str
    source_type: str
    source_id: str
    chunk_index: int = Field(ge=0)
    chunk_count: int = Field(ge=1)

    # Content
    title: str | None = None
    content: str = Field(min_length=1)
    excerpt: str | None = None

    # Entity linkage
    entity_type: str | None = None
    entity_id: int | str | None = None
    prospect_id: int | None = None
    prospect_name: str | None = None
    team_id: int | None = None
    team_abbr: str | None = None
    pick_no: int | None = Field(default=None, ge=1, le=60)
    year: int | None = Field(default=None, ge=1900, le=2100)

    # Source metadata
    url: str | None = None
    source_name: str | None = None
    publisher: str | None = None
    author: str | None = None
    published_at: datetime | None = None

    # Retrieval metadata
    confidence: float | None = Field(default=None, ge=0, le=1)
    retrieval_score: float | None = Field(default=None, ge=0, le=1)
    relevance_reason: str | None = None
    conflict_note: str | None = None
    tags: list[str] = Field(default_factory=list)

    # Safety lock
    evidence_only: Literal[True] = True

    @field_validator("content")
    @classmethod
    def _content_must_be_non_whitespace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be empty or whitespace-only")
        return value

    @model_validator(mode="after")
    def _validate_chunk_index_range(self) -> "EvidenceChunk":
        if self.chunk_index >= self.chunk_count:
            raise ValueError(
                f"chunk_index ({self.chunk_index}) must be < "
                f"chunk_count ({self.chunk_count})"
            )
        return self
