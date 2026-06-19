from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.schemas.evidence import (
    ConflictEvidence,
    EvidenceChunk,
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
from app.schemas.recommendation import RankedProspectRead
from app.schemas.simulation import SimulateResponse, SimulatedPickRead
from app.services.evidence_chunker import chunk_text
from app.services.evidence_document_mapper import map_evidence_document
from app.services.embedding_service import embed_chunks
from app.services.manual_note_mapper import manual_note_to_evidence_pair
from app.services.manual_note_retrieval_service import (
    retrieve_manual_note_documents,
)
from app.services.semantic_retrieval_service import retrieve_semantic
from app.services.vector_store_service import InMemoryVectorStore


logger = logging.getLogger(__name__)


MARKET_DELTA_CONFLICT_THRESHOLD = 8

# RAG-v1-D1-A: max persisted manual notes to attach per pick when retrieval
# is enabled.  Kept small to avoid flooding the evidence panel.
PERSISTED_MANUAL_NOTE_LIMIT = 5


def build_pick_evidence(
    simulation: SimulateResponse,
    pick: SimulatedPickRead,
    *,
    manual_notes: list[ManualNote] | None = None,
    db: Session | None = None,
    retrieve_knowledge: bool = False,
) -> PickEvidencePackage:
    selected = pick.selected_player
    ranking_evidence = _build_ranking_evidence(pick)
    team_fit_evidence = _build_team_fit_evidence(selected)
    market_evidence = _build_market_evidence(selected)
    risk_evidence = _build_risk_evidence(
        selected,
        market_top30_missing_warnings=simulation.market_top30_missing_warnings,
    )
    conflict_evidence = _build_conflict_evidence(
        selected,
        market_evidence=market_evidence,
        diagnostics_warnings=risk_evidence.diagnostics_warnings,
        market_top30_missing_warnings=simulation.market_top30_missing_warnings,
    )

    citations = _build_citations(selected)
    retrieved_evidence: list[RetrievedEvidence] = []
    matched_notes = _manual_notes_for_pick(manual_notes, pick)
    for note in matched_notes:
        retrieved, citation = manual_note_to_evidence_pair(note)
        retrieved_evidence.append(retrieved)
        citations.append(citation)

    # RAG-v1-D1-A: optionally attach persisted ManualNote knowledge sources.
    # Default is OFF (db=None, retrieve_knowledge=False) so existing callers
    # are unaffected.  When enabled, retrieval is read-only and evidence-only;
    # it only appends to retrieved_evidence / citations and never touches
    # decision / scoring / ranking fields.  Failures are swallowed so the
    # evidence package still builds without the persisted notes.
    if db is not None and retrieve_knowledge:
        _append_persisted_manual_notes(
            retrieved_evidence=retrieved_evidence,
            citations=citations,
            db=db,
            year=simulation.year,
            prospect_id=selected.prospect.id,
            team_id=pick.team.id,
            pick_no=pick.pick,
        )

    # RAG-v2-M2-E: config-gated semantic retrieval over manual notes.
    # Default is OFF (evidence_retrieve_semantic=False) so existing callers
    # are unaffected.  When enabled, manual notes are chunked, embedded,
    # indexed, and semantically retrieved; results are appended to
    # retrieved_evidence / citations only — never to decision / scoring /
    # ranking fields.  Any failure is swallowed so the semantic path is
    # never a hard dependency.
    _append_semantic_retrieval_evidence(
        retrieved_evidence=retrieved_evidence,
        citations=citations,
        manual_notes=manual_notes,
        pick=pick,
        simulation=simulation,
    )

    return PickEvidencePackage(
        pick_number=pick.pick,
        team_abbr=pick.team.abbr,
        selected_player_id=selected.prospect.id,
        selected_player_name=selected.prospect.name,
        ranking_evidence=ranking_evidence,
        team_fit_evidence=team_fit_evidence,
        market_evidence=market_evidence,
        risk_evidence=risk_evidence,
        conflict_evidence=conflict_evidence,
        evidence_sufficiency=_build_evidence_sufficiency(
            ranking_evidence=ranking_evidence,
            market_evidence=market_evidence,
            risk_evidence=risk_evidence,
            conflict_evidence=conflict_evidence,
        ),
        citations=citations,
        retrieved_evidence=retrieved_evidence,
    )


def _append_persisted_manual_notes(
    *,
    retrieved_evidence: list[RetrievedEvidence],
    citations: list[EvidenceCitation],
    db: Session,
    year: int,
    prospect_id: int,
    team_id: int,
    pick_no: int,
) -> None:
    """Retrieve persisted ManualNote rows and append them as evidence.

    Safety:
    - Read-only: retrieval never commits/flushes.
    - Evidence-only: output is Literal-locked to ``evidence_only=True``.
    - Failure-isolated: any exception is logged at WARNING level then
      swallowed so the caller's evidence package still builds without the
      persisted notes.

    Retrieval strategy: the retrieval service uses AND logic for its filters,
    but a manual note about a prospect typically only carries ``prospect_id``
    (not ``team_id`` / ``pick_no``).  To match the OR semantics of the
    request-level ``_manual_notes_for_pick`` helper, we issue up to three
    separate retrieval calls — by prospect, by team, by pick — and
    deduplicate by ``source_id`` (which is ``str(record.id)``).

    Logging (RAG-v1-D1-E1):
    - On success, logs INFO with the final ``attached_count`` (the number of
      persisted notes actually appended to retrieved_evidence / citations).
      A zero ``attached_count`` is logged at DEBUG to avoid noise.
    - On failure, logs WARNING with the failing filter set and the exception
      type / message.  Sensitive note fields (body / summary / tags / author
      / source_url / relevance_reason / excerpt / content) are NEVER logged.
    """
    seen_source_ids: set[str] = set()

    retrieval_calls: list[dict[str, Any]] = [
        {"prospect_id": prospect_id},
        {"team_id": team_id},
        {"pick_no": pick_no},
    ]

    for filters in retrieval_calls:
        # Global cap: stop once we have appended PERSISTED_MANUAL_NOTE_LIMIT
        # documents across all retrieval calls.  This guarantees the total
        # persisted manual notes per PickEvidencePackage never exceeds the
        # limit, regardless of how many matches each retrieval call returns.
        if len(seen_source_ids) >= PERSISTED_MANUAL_NOTE_LIMIT:
            break

        try:
            documents = retrieve_manual_note_documents(
                db,
                year=year,
                limit=PERSISTED_MANUAL_NOTE_LIMIT,
                **filters,
            )
        except Exception as exc:
            # Log the failure at WARNING, then continue so the evidence
            # package still builds.  Only non-sensitive context is logged.
            logger.warning(
                "ManualNote retrieval failed: "
                "year=%s prospect_id=%s team_id=%s pick_no=%s "
                "filters=%s exc_type=%s exc_msg=%s",
                year,
                prospect_id,
                team_id,
                pick_no,
                filters,
                type(exc).__name__,
                str(exc),
            )
            continue

        for document in documents:
            if len(seen_source_ids) >= PERSISTED_MANUAL_NOTE_LIMIT:
                break
            if document.source_id in seen_source_ids:
                continue
            seen_source_ids.add(document.source_id)
            retrieved, citation = map_evidence_document(document)
            retrieved_evidence.append(retrieved)
            citations.append(citation)

    attached_count = len(seen_source_ids)
    if attached_count > 0:
        logger.info(
            "ManualNote retrieval attached: "
            "year=%s prospect_id=%s team_id=%s pick_no=%s attached_count=%d",
            year,
            prospect_id,
            team_id,
            pick_no,
            attached_count,
        )
    else:
        logger.debug(
            "ManualNote retrieval attached zero notes: "
            "year=%s prospect_id=%s team_id=%s pick_no=%s",
            year,
            prospect_id,
            team_id,
            pick_no,
        )


def _append_semantic_retrieval_evidence(
    *,
    retrieved_evidence: list[RetrievedEvidence],
    citations: list[EvidenceCitation],
    manual_notes: list[ManualNote] | None,
    pick: SimulatedPickRead,
    simulation: SimulateResponse,
) -> None:
    """Config-gated semantic retrieval over manual notes (RAG-v2-M2-E).

    When ``evidence_retrieve_semantic`` is True, this function:

    1. Chunks each manual note's ``title + summary + body`` via
       :func:`chunk_text` (M2-B).
    2. Embeds the chunks via :func:`embed_chunks` (M2-C1 fake deterministic
       embedding).
    3. Builds an :class:`InMemoryVectorStore` index (M2-D1).
    4. Constructs a ``query_text`` from the pick context.
    5. Calls :func:`retrieve_semantic` (M2-D2) to get
       ``(RetrievedEvidence, EvidenceCitation)`` pairs.
    6. Appends the pairs to ``retrieved_evidence`` / ``citations``.

    Safety:
    - Config-gated: no-op when ``evidence_retrieve_semantic=False``.
    - Evidence-only: results are appended to evidence lists only; they
      never touch ``selected_player`` / ``final_score`` /
      ``prediction_sort_score`` / ranking / simulation / prediction.
    - ``retrieval_score`` enters ``RetrievedEvidence`` (for sorting) but
      is excluded from ``EvidenceCitation`` and the LLM payload whitelist.
    - Failure-isolated: any exception is logged at WARNING (without
      sensitive note content) and swallowed so the evidence package
      still builds without semantic results.
    - No hard dependency: if there are no manual notes, no chunks can be
      built, or any step fails, the caller's evidence package is
      unaffected.
    """
    settings = get_settings()
    if not settings.evidence_retrieve_semantic:
        return

    if not manual_notes:
        return

    try:
        # 1. Build EvidenceChunks from manual notes.
        chunks: list[EvidenceChunk] = []
        for index, note in enumerate(manual_notes):
            note_source_id = (
                str(note.note_id)
                if note.note_id is not None
                else f"note-{index}"
            )
            # Compose chunking text from title + optional summary + body.
            text_parts = [note.title, note.body]
            if note.summary:
                text_parts.insert(1, note.summary)
            note_text = "\n".join(text_parts)

            note_chunks = chunk_text(
                note_text,
                source_type="manual_note",
                source_id=note_source_id,
                title=note.title,
                entity_type=note.entity_type,
                entity_id=note.entity_id,
                prospect_id=note.prospect_id,
                team_id=note.team_id,
                pick_no=note.pick_no,
                year=note.year,
                url=note.source_url,
                source_name=note.source,
                author=note.author,
                confidence=note.confidence,
                relevance_reason=note.relevance_reason,
                tags=note.tags,
            )
            chunks.extend(note_chunks)

        if not chunks:
            return

        # 2. Embed chunks (M2-C1 fake deterministic embedding).
        embeddings = embed_chunks(chunks)

        # 3. Build in-memory vector index (M2-D1).
        vector_store = InMemoryVectorStore()
        vector_store.build_index(chunks, embeddings)

        # 4. Construct query_text from pick context.
        query_text = _build_semantic_query_text(pick, simulation)
        if not query_text or not query_text.strip():
            return

        # 5. Retrieve semantic evidence (M2-D2).
        semantic_retrieved, semantic_citations = retrieve_semantic(
            query_text=query_text,
            chunks=chunks,
            vector_store=vector_store,
            top_k=settings.evidence_semantic_top_k,
            min_score=settings.evidence_semantic_min_score,
        )

        # 6. Append results to the evidence package.
        retrieved_evidence.extend(semantic_retrieved)
        citations.extend(semantic_citations)

        if semantic_retrieved:
            logger.info(
                "Semantic retrieval attached: "
                "year=%s pick_no=%s attached_count=%d",
                simulation.year,
                pick.pick,
                len(semantic_retrieved),
            )
        else:
            logger.debug(
                "Semantic retrieval attached zero results: "
                "year=%s pick_no=%s",
                simulation.year,
                pick.pick,
            )
    except Exception as exc:
        # Log the failure at WARNING, then swallow so the evidence
        # package still builds.  Only non-sensitive context is logged.
        logger.warning(
            "Semantic retrieval failed, falling back: "
            "year=%s pick_no=%s exc_type=%s exc_msg=%s",
            simulation.year,
            pick.pick,
            type(exc).__name__,
            str(exc),
        )


def _build_semantic_query_text(
    pick: SimulatedPickRead,
    simulation: SimulateResponse,
) -> str:
    """Build a stable ``query_text`` for semantic retrieval.

    Combines team abbreviation, selected player name, pick number,
    position, and a few evidence summary fields (scouting fit positives,
    top reasons).  All fields are stable and read-only — none of them
    are decision / scoring / ranking fields.

    The query text is used only to find relevant evidence chunks; it
    never influences selection.
    """
    selected = pick.selected_player
    parts: list[str] = [
        pick.team.abbr,
        selected.prospect.name,
        f"pick {pick.pick}",
        selected.prospect.position,
    ]
    # Add a few evidence summary fields for richer query context.
    if selected.scouting_fit_positives:
        parts.extend(selected.scouting_fit_positives[:3])
    if selected.reasons:
        parts.extend(selected.reasons[:2])
    return " ".join(str(part) for part in parts if part)


def _manual_notes_for_pick(
    manual_notes: list[ManualNote] | None,
    pick: SimulatedPickRead,
) -> list[ManualNote]:
    """Filter manual notes that are relevant to this pick.

    Manual notes are evidence-only. Matching is by entity identity only and
    never influences scoring, selection, or ranking. Irrelevant notes are
    silently ignored.
    """
    if not manual_notes:
        return []

    selected_prospect_id = pick.selected_player.prospect.id
    selected_prospect_name = pick.selected_player.prospect.name
    team_id = pick.team.id
    team_abbr = pick.team.abbr
    pick_no = pick.pick

    matched: list[ManualNote] = []
    for note in manual_notes:
        if _note_matches_pick(
            note,
            selected_prospect_id=selected_prospect_id,
            selected_prospect_name=selected_prospect_name,
            team_id=team_id,
            team_abbr=team_abbr,
            pick_no=pick_no,
        ):
            matched.append(note)
    return matched


def _note_matches_pick(
    note: ManualNote,
    *,
    selected_prospect_id: int,
    selected_prospect_name: str,
    team_id: int,
    team_abbr: str,
    pick_no: int,
) -> bool:
    entity_type = note.entity_type

    if entity_type == "prospect":
        return (
            note.prospect_id == selected_prospect_id
            or note.entity_id == selected_prospect_id
            or note.entity_id == selected_prospect_name
        )

    if entity_type == "team":
        return (
            note.team_id == team_id
            or note.entity_id == team_id
            or note.entity_id == team_abbr
        )

    if entity_type == "pick":
        return note.pick_no == pick_no or note.entity_id == pick_no

    if entity_type == "simulation_context":
        return (
            note.pick_no is None
            and note.prospect_id is None
            and note.team_id is None
        )

    # market_projection / scouting_profile / news_article: only allow when an
    # auxiliary field matches the current pick context.
    if entity_type in {
        "market_projection",
        "scouting_profile",
        "news_article",
    }:
        return (
            note.prospect_id == selected_prospect_id
            or note.team_id == team_id
            or note.pick_no == pick_no
        )

    return False


def _build_ranking_evidence(pick: SimulatedPickRead) -> RankingEvidence:
    selected = pick.selected_player
    selected_index = _selected_index_in_candidate_board(pick)
    score_gap_to_next = None
    score_gap_to_previous = None
    if selected_index is not None:
        score_gap_to_next = _score_gap(
            pick.candidate_board,
            selected_index,
            selected_index + 1,
        )
        score_gap_to_previous = _score_gap(
            pick.candidate_board,
            selected_index - 1,
            selected_index,
        )

    return RankingEvidence(
        final_score=selected.scores.final_score,
        prediction_sort_score=selected.prediction_sort_score,
        rank_in_available_pool=(
            selected_index + 1 if selected_index is not None else None
        ),
        score_gap_to_next=score_gap_to_next,
        score_gap_to_previous=score_gap_to_previous,
        primary_score_drivers=_primary_score_drivers(selected),
    )


def _build_team_fit_evidence(selected: RankedProspectRead) -> TeamFitEvidence:
    basis: list[str] = []
    matched_needs = list(selected.scouting_fit_positives or [])
    unmatched_needs = list(selected.scouting_fit_risks or [])
    if selected.scouting_fit_score is not None:
        basis.append(f"scouting_fit_score={selected.scouting_fit_score}")
    if selected.team_projection_type:
        basis.append(f"team_projection_type={selected.team_projection_type}")
    if selected.team_projection_notes:
        basis.append(selected.team_projection_notes)

    same_team_priority = any(
        "Same-team TeamPickProjection priority applied." in note
        for note in selected.prediction_selection_notes or []
    )

    return TeamFitEvidence(
        matched_needs=matched_needs,
        unmatched_needs=unmatched_needs,
        fit_strength=_fit_strength(selected.scouting_fit_score),
        same_team_projection_priority=same_team_priority,
        explanation_basis=basis,
    )


def _build_market_evidence(selected: RankedProspectRead) -> MarketEvidence:
    expected_pick = selected.market_expected_pick or selected.projection_expected_pick
    range_min = selected.projection_draft_range_min
    range_max = selected.projection_draft_range_max
    has_market_reference = any(
        value is not None
        for value in (
            expected_pick,
            range_min,
            range_max,
            selected.projection_source,
        )
    )
    if selected.market_alignment_label == "无市场参考":
        has_market_reference = False

    market_sources = [
        source
        for source in (
            selected.projection_source,
            selected.team_projection_type,
        )
        if source
    ]

    return MarketEvidence(
        has_market_reference=has_market_reference,
        market_expected_pick=expected_pick,
        market_range_min=range_min,
        market_range_max=range_max,
        market_pick_delta=selected.market_pick_delta,
        market_alignment_label=selected.market_alignment_label,
        market_alignment_notes=list(selected.market_alignment_notes or []),
        market_sources=market_sources,
    )


def _build_risk_evidence(
    selected: RankedProspectRead,
    *,
    market_top30_missing_warnings: list[str],
) -> RiskEvidence:
    diagnostics_warnings = list(selected.diagnostics_warnings or [])
    selected_market_top30_warnings = _warnings_for_selected_player(
        selected,
        market_top30_missing_warnings,
    )
    market_risk_flags = [
        warning
        for warning in diagnostics_warnings
        if "market" in warning.lower()
    ]
    market_risk_flags.extend(selected_market_top30_warnings)
    stats_risk_flags = [
        warning
        for warning in diagnostics_warnings
        if "stats" in warning.lower()
    ]
    data_quality_flags = [
        warning
        for warning in diagnostics_warnings
        if any(token in warning.lower() for token in ("data", "heuristic", "confidence"))
    ]

    return RiskEvidence(
        diagnostics_warnings=diagnostics_warnings,
        market_risk_flags=market_risk_flags,
        stats_risk_flags=stats_risk_flags,
        data_quality_flags=data_quality_flags,
        overall_risk_level=_overall_risk_level(
            diagnostics_warnings=diagnostics_warnings,
            market_top30_missing_warnings=selected_market_top30_warnings,
        ),
    )


def _build_conflict_evidence(
    selected: RankedProspectRead,
    *,
    market_evidence: MarketEvidence,
    diagnostics_warnings: list[str],
    market_top30_missing_warnings: list[str],
) -> list[ConflictEvidence]:
    conflicts: list[ConflictEvidence] = []
    delta = market_evidence.market_pick_delta
    if delta is not None and abs(delta) >= MARKET_DELTA_CONFLICT_THRESHOLD:
        conflicts.append(
            ConflictEvidence(
                type="market_model_delta",
                severity="high",
                description=(
                    "DraftMind selected this player "
                    f"{abs(delta)} picks {'earlier' if delta < 0 else 'later'} "
                    "than the market reference."
                ),
                related_fields=["market_pick_delta", "market_expected_pick"],
            )
        )

    if not market_evidence.has_market_reference:
        conflicts.append(
            ConflictEvidence(
                type="missing_market_reference",
                severity="medium",
                description="No market reference is available for this selected player.",
                related_fields=[
                    "market_expected_pick",
                    "projection_expected_pick",
                    "market_alignment_label",
                ],
            )
        )

    for warning in diagnostics_warnings:
        conflicts.append(
            ConflictEvidence(
                type="diagnostics_warning",
                severity="medium",
                description=warning,
                related_fields=["diagnostics_warnings"],
            )
        )

    selected_name = selected.prospect.name.lower()
    for warning in market_top30_missing_warnings:
        warning_lower = warning.lower()
        if selected_name in warning_lower:
            conflicts.append(
                ConflictEvidence(
                    type="market_top30_missing_warning",
                    severity="medium",
                    description=warning,
                    related_fields=["market_top30_missing_warnings"],
                )
            )

    return conflicts


def _warnings_for_selected_player(
    selected: RankedProspectRead,
    warnings: list[str],
) -> list[str]:
    selected_name = selected.prospect.name.lower()
    return [
        warning
        for warning in warnings
        if selected_name in warning.lower()
    ]


def _build_evidence_sufficiency(
    *,
    ranking_evidence: RankingEvidence,
    market_evidence: MarketEvidence,
    risk_evidence: RiskEvidence,
    conflict_evidence: list[ConflictEvidence],
) -> EvidenceSufficiency:
    missing_sections: list[str] = []
    weak_sections: list[str] = []
    explanation_limits: list[str] = []

    if ranking_evidence.final_score is None:
        missing_sections.append("ranking_evidence")
        explanation_limits.append("Selected player ranking evidence is incomplete.")
    if not market_evidence.has_market_reference:
        missing_sections.append("market_evidence")
        explanation_limits.append("No stable market reference is available.")
    if risk_evidence.diagnostics_warnings:
        weak_sections.append("risk_evidence")
        explanation_limits.append("Diagnostics warnings should be shown as caveats.")

    if "ranking_evidence" in missing_sections:
        level = "insufficient"
    elif (
        not market_evidence.has_market_reference
        or risk_evidence.diagnostics_warnings
        or any(conflict.severity == "high" for conflict in conflict_evidence)
    ):
        level = "limited"
    elif missing_sections or weak_sections:
        level = "moderate"
    else:
        level = "strong"

    return EvidenceSufficiency(
        level=level,
        missing_sections=missing_sections,
        weak_sections=weak_sections,
        explanation_limits=explanation_limits,
    )


def _build_citations(selected: RankedProspectRead) -> list[EvidenceCitation]:
    citations: list[EvidenceCitation] = []
    if selected.projection_source:
        citations.append(
            EvidenceCitation(
                source_type="market_projection",
                source_id=selected.projection_source,
                title="Prospect draft projection",
                confidence=selected.projection_confidence,
            )
        )
    if selected.team_projection_type:
        citations.append(
            EvidenceCitation(
                source_type="team_projection",
                source_id=selected.team_projection_type,
                title="Team pick projection",
                excerpt=selected.team_projection_notes,
                confidence=selected.team_projection_confidence,
            )
        )
    return citations


def _selected_index_in_candidate_board(pick: SimulatedPickRead) -> int | None:
    selected_id = pick.selected_player.prospect.id
    selected_name = pick.selected_player.prospect.name
    for index, candidate in enumerate(pick.candidate_board):
        if candidate.prospect.id == selected_id:
            return index
        if candidate.prospect.name == selected_name:
            return index
    return None


def _score_gap(
    candidate_board: list[RankedProspectRead],
    left_index: int,
    right_index: int,
) -> float | None:
    if left_index < 0 or right_index >= len(candidate_board):
        return None
    left = candidate_board[left_index].scores.final_score
    right = candidate_board[right_index].scores.final_score
    return round(left - right, 3)


def _primary_score_drivers(selected: RankedProspectRead) -> list[str]:
    drivers = list(selected.reasons[:3])
    if selected.prediction_selection_notes:
        drivers.extend(selected.prediction_selection_notes[:2])
    if selected.prediction_sort_score is not None:
        drivers.append("prediction_sort_score available for explanation context")
    return drivers


def _fit_strength(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 8:
        return "strong"
    if score >= 6:
        return "moderate"
    return "limited"


def _overall_risk_level(
    *,
    diagnostics_warnings: list[str],
    market_top30_missing_warnings: list[str],
) -> str:
    if len(diagnostics_warnings) >= 2:
        return "high"
    if diagnostics_warnings or market_top30_missing_warnings:
        return "moderate"
    return "low"
