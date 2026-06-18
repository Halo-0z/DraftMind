"""RAG-v0-M3.1-B: Real LLM explanation service shell with safe fallback.

This module provides a guarded shell around an LLM client that converts a
``PickEvidencePackage`` into a ``PickExplanation``.  The shell is deliberately
defensive: any LLM failure, boundary violation, or unsafe output causes an
immediate fallback to the deterministic ``build_mock_pick_explanation``.

Design rules enforced here and covered by
``test_evidence_llm_explanation_service.py``:

1. ``llm_client is None`` → fallback to mock immediately (no network).
2. LLM input is a whitelist payload built by ``_build_llm_explanation_payload``
   — NOT the full ``evidence.model_dump()``.  Only explanation-relevant fields
   are included; long excerpts are truncated; internal metadata (entity_id,
   retrieval_score, freshness_days, nested citation, etc.) is excluded.
3. LLM output must parse as JSON and pass ``PickExplanation.model_validate``.
   Because ``PickExplanation`` uses ``extra="forbid"``, any dangerous extra
   field (``replacement_player``, ``rerank_score``, ...) triggers validation
   failure → fallback.
4. After schema validation, a second safety pass checks:
   - identity fields match the input evidence verbatim
   - ``decision_locked is True`` and ``llm_can_modify_decision is False``
   - ``citation_refs`` only reference existing citations
   - ``limitations`` non-empty when sufficiency is limited/insufficient
   - conflict described when ``conflict_evidence`` is present
   - ``risk_summary`` non-empty when ``risk_evidence`` has flags
5. Dangerous natural-language phrases cause immediate fallback (NOT sanitize-
   then-continue).  A real LLM that crosses the boundary is rejected wholesale.
6. Fallback always returns ``build_mock_pick_explanation(evidence)`` — never a
   hand-written explanation.
7. No real LLM provider is imported.  No ``openai`` / ``httpx`` / ``requests``
   / ``socket``.  No DB.  No ranking_engine / prediction_calibration /
   simulation_service.  No env vars.  No mutation of the input evidence.

RAG-v1-D3-B additions:
- ``_build_llm_explanation_payload`` replaces ``evidence.model_dump()`` so the
  LLM only sees a whitelist of explanation-safe fields.
- ``manual_note`` entries still enter the payload (in ``retrieved_evidence``
  and ``citations``) but carry ``evidence_only=True`` and are covered by the
  strengthened prompt contract.
- Long excerpts are truncated to ``LLM_EXCERPT_MAX_CHARS`` to bound prompt
  size and prevent prompt-stuffing via oversized note bodies.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from app.schemas.evidence import (
    EvidenceCitation,
    PickEvidencePackage,
    PickExplanation,
    RetrievedEvidence,
)
from app.services.evidence_explanation_service import (
    FORBIDDEN_PHRASES,
    build_mock_pick_explanation,
)
from app.services.evidence_prompt_contract import (
    build_pick_explanation_prompt_contract,
)


# ---------------------------------------------------------------------------
# LLM client protocol
# ---------------------------------------------------------------------------


class LLMClient(Protocol):
    """Minimal protocol for an LLM completion client.

    Real providers are NOT imported in this module.  Callers that wish to use
    a real LLM must pass an object satisfying this protocol.  In tests, a
    ``FakeLLMClient`` is used.
    """

    def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Return the LLM's text response, or raise on failure."""
        ...


# ---------------------------------------------------------------------------
# Forbidden-field set (mirrors the prompt contract and schema tests)
# ---------------------------------------------------------------------------

FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {
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
)


# ---------------------------------------------------------------------------
# RAG-v1-D3-B: LLM payload whitelist + excerpt truncation
# ---------------------------------------------------------------------------

# Maximum character length for any ``excerpt`` field sent to the LLM.
# Long manual_note bodies can be up to 8000 chars; truncating keeps the prompt
# bounded and prevents prompt-stuffing.
LLM_EXCERPT_MAX_CHARS: int = 500


def _truncate_excerpt(excerpt: str | None) -> str | None:
    """Truncate an excerpt to ``LLM_EXCERPT_MAX_CHARS``.

    Returns ``None`` unchanged.  Short excerpts are returned verbatim.  Long
    excerpts are cut to the limit and suffixed with ``"..."`` so the LLM can
    tell the text was truncated.
    """
    if excerpt is None:
        return None
    if len(excerpt) <= LLM_EXCERPT_MAX_CHARS:
        return excerpt
    return excerpt[: LLM_EXCERPT_MAX_CHARS - 3] + "..."


def _whitelist_citation(citation: EvidenceCitation) -> dict[str, Any]:
    """Project an ``EvidenceCitation`` onto the explanation-safe whitelist.

    Excludes internal metadata (``publisher``, ``retrieved_at``,
    ``freshness_days``, ``entity_id``) that the LLM does not need.
    """
    return {
        "source_type": citation.source_type,
        "source_id": citation.source_id,
        "title": citation.title,
        "url": citation.url,
        "date": citation.date,
        "excerpt": _truncate_excerpt(citation.excerpt),
        "confidence": citation.confidence,
        "evidence_source_type": citation.evidence_source_type,
        "entity_type": citation.entity_type,
        "author": citation.author,
        "relevance_reason": citation.relevance_reason,
        "evidence_only": citation.evidence_only,
    }


def _whitelist_retrieved_evidence(item: RetrievedEvidence) -> dict[str, Any]:
    """Project a ``RetrievedEvidence`` onto the explanation-safe whitelist.

    Excludes the nested ``citation`` (redundant with the top-level
    ``citations`` list), ``entity_id``, ``retrieval_score``,
    ``freshness_days``, and ``conflict_note``.
    """
    return {
        "source_type": item.source_type,
        "source_id": item.source_id,
        "entity_type": item.entity_type,
        "title": item.title,
        "excerpt": _truncate_excerpt(item.excerpt),
        "url": item.url,
        "date": item.date,
        "confidence": item.confidence,
        "relevance_reason": item.relevance_reason,
        "evidence_only": item.evidence_only,
    }


def _build_llm_explanation_payload(evidence: PickEvidencePackage) -> dict[str, Any]:
    """Build a whitelist payload for the LLM explanation prompt.

    RAG-v1-D3-B: replaces the previous ``evidence.model_dump()`` call so the
    LLM only receives explanation-relevant fields.  This is defense in depth
    — even if the schema later grows dangerous fields, the whitelist will not
    accidentally include them.

    The payload includes:
    - identity fields (pick_number, team_abbr, selected_player_*)
    - decision locks (decision_locked, decision_source, llm_can_modify_decision)
    - ranking_evidence / team_fit_evidence / market_evidence / risk_evidence /
      conflict_evidence / evidence_sufficiency (all fields, all read-only)
    - citations (whitelist, excerpt truncated)
    - retrieved_evidence (whitelist, excerpt truncated — manual_note lives here)
    - narrative_explanation (if present)

    The payload excludes (by omission):
    - candidate_board / alternatives / simulation / replacement_player /
      score_adjustment / selection_override (not in schema; regression guard)
    - citation nested object inside retrieved_evidence (redundant)
    - entity_id / retrieval_score / freshness_days / conflict_note /
      publisher / retrieved_at (internal metadata)

    This function does NOT mutate the original ``PickEvidencePackage``.
    """
    payload: dict[str, Any] = {
        "pick_number": evidence.pick_number,
        "team_abbr": evidence.team_abbr,
        "selected_player_id": evidence.selected_player_id,
        "selected_player_name": evidence.selected_player_name,
        "decision_locked": evidence.decision_locked,
        "decision_source": evidence.decision_source,
        "llm_can_modify_decision": evidence.llm_can_modify_decision,
    }

    if evidence.ranking_evidence is not None:
        payload["ranking_evidence"] = evidence.ranking_evidence.model_dump()
    if evidence.team_fit_evidence is not None:
        payload["team_fit_evidence"] = evidence.team_fit_evidence.model_dump()
    if evidence.market_evidence is not None:
        payload["market_evidence"] = evidence.market_evidence.model_dump()
    if evidence.risk_evidence is not None:
        payload["risk_evidence"] = evidence.risk_evidence.model_dump()

    payload["conflict_evidence"] = [
        c.model_dump() for c in evidence.conflict_evidence
    ]
    payload["evidence_sufficiency"] = evidence.evidence_sufficiency.model_dump()
    payload["citations"] = [
        _whitelist_citation(c) for c in evidence.citations
    ]
    payload["retrieved_evidence"] = [
        _whitelist_retrieved_evidence(r) for r in evidence.retrieved_evidence
    ]

    if evidence.narrative_explanation is not None:
        payload["narrative_explanation"] = evidence.narrative_explanation

    return payload


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_llm_pick_explanation(
    evidence: PickEvidencePackage,
    llm_client: object | None = None,
) -> PickExplanation:
    """Convert ``evidence`` into a ``PickExplanation`` via an optional LLM.

    - If ``llm_client is None``, immediately returns the deterministic mock
      explanation (no network, no provider).
    - If ``llm_client`` is provided, the shell:
        1. Builds the prompt contract messages.
        2. Sends ONLY the whitelist payload (``_build_llm_explanation_payload``)
           as the user payload — never the full ``evidence.model_dump()``.
        3. Parses the LLM response as JSON.
        4. Validates via ``PickExplanation.model_validate`` (extra="forbid").
        5. Runs a second safety pass (identity, decision locks, citations,
           limitations, conflict, risk, forbidden phrases).
        6. Returns the validated explanation on success.
    - On ANY failure (exception, invalid JSON, schema error, boundary
      violation, dangerous phrase), falls back to
      ``build_mock_pick_explanation(evidence)``.
    """
    if llm_client is None:
        return build_mock_pick_explanation(evidence)

    try:
        raw_response = _call_llm(llm_client, evidence)
    except Exception:
        # LLM timeout, exception, network error, etc. → fallback.
        return build_mock_pick_explanation(evidence)

    try:
        parsed = _parse_json(raw_response)
    except Exception:
        # Invalid JSON → fallback.
        return build_mock_pick_explanation(evidence)

    try:
        explanation = PickExplanation.model_validate(parsed)
    except Exception:
        # Schema validation failed (including extra="forbid" for dangerous
        # fields) → fallback.
        return build_mock_pick_explanation(evidence)

    if not _passes_safety_checks(explanation, evidence):
        # Second-pass safety check failed → fallback.
        return build_mock_pick_explanation(evidence)

    return explanation


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def _call_llm(llm_client: object, evidence: PickEvidencePackage) -> str:
    """Build messages from the prompt contract and call the LLM.

    RAG-v1-D3-B: the user message contains ONLY the whitelist payload built
    by ``_build_llm_explanation_payload`` — NOT ``evidence.model_dump()``.
    No ``candidate_board``, ``alternatives``, ``simulation``, DB, or ranking
    data is attached.
    """
    contract = build_pick_explanation_prompt_contract()
    payload = _build_llm_explanation_payload(evidence)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": contract["system"]},
        {"role": "developer", "content": contract["developer"]},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False),
        },
    ]
    # The client is expected to satisfy the LLMClient protocol.
    return llm_client.complete(messages)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def _parse_json(raw: str) -> dict[str, Any]:
    """Parse the LLM response as a JSON object.

    Strips leading/trailing whitespace and handles the common case where the
    LLM wraps the JSON in ```json ... ``` fences.
    """
    text = raw.strip()
    # Strip markdown code fences if present.
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        # Remove closing fence
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return json.loads(text)


# ---------------------------------------------------------------------------
# Second-pass safety checks
# ---------------------------------------------------------------------------


def _passes_safety_checks(
    explanation: PickExplanation,
    evidence: PickEvidencePackage,
) -> bool:
    """Run all post-schema safety checks.  Returns ``False`` on any violation."""
    if not _check_identity(explanation, evidence):
        return False
    if not _check_decision_locks(explanation):
        return False
    if not _check_citation_refs(explanation, evidence):
        return False
    if not _check_sufficiency_limitations(explanation, evidence):
        return False
    if not _check_conflict_disclosure(explanation, evidence):
        return False
    if not _check_risk_disclosure(explanation, evidence):
        return False
    if not _check_no_forbidden_phrases(explanation):
        return False
    return True


def _check_identity(
    explanation: PickExplanation,
    evidence: PickEvidencePackage,
) -> bool:
    return (
        explanation.pick_number == evidence.pick_number
        and explanation.team_abbr == evidence.team_abbr
        and explanation.selected_player_id == evidence.selected_player_id
        and explanation.selected_player_name == evidence.selected_player_name
    )


def _check_decision_locks(explanation: PickExplanation) -> bool:
    return (
        explanation.decision_locked is True
        and explanation.llm_can_modify_decision is False
    )


def _check_citation_refs(
    explanation: PickExplanation,
    evidence: PickEvidencePackage,
) -> bool:
    """``citation_refs`` may only reference existing citation fields."""
    valid_refs: set[str] = set()
    for citation in evidence.citations or []:
        if citation.source_id:
            valid_refs.add(citation.source_id)
        if citation.title:
            valid_refs.add(citation.title)
        if citation.url:
            valid_refs.add(citation.url)
    for ref in explanation.citation_refs:
        if ref not in valid_refs:
            return False
    return True


def _check_sufficiency_limitations(
    explanation: PickExplanation,
    evidence: PickEvidencePackage,
) -> bool:
    """If sufficiency is limited/insufficient, ``limitations`` must be non-empty."""
    level = (evidence.evidence_sufficiency.level or "").lower()
    if level in ("limited", "insufficient"):
        if not explanation.limitations:
            return False
    return True


def _check_conflict_disclosure(
    explanation: PickExplanation,
    evidence: PickEvidencePackage,
) -> bool:
    """If ``conflict_evidence`` is present, the output must mention conflict."""
    if not evidence.conflict_evidence:
        return True
    combined = " ".join(explanation.limitations) + " " + " ".join(
        explanation.evidence_notes
    )
    if explanation.summary:
        combined += " " + explanation.summary
    return "冲突" in combined or "conflict" in combined.lower()


def _check_risk_disclosure(
    explanation: PickExplanation,
    evidence: PickEvidencePackage,
) -> bool:
    """If ``risk_evidence`` has flags, ``risk_summary`` must be non-empty."""
    risk = evidence.risk_evidence
    if risk is None:
        return True
    has_flags = bool(
        (risk.diagnostics_warnings)
        or (risk.market_risk_flags)
        or (risk.stats_risk_flags)
        or (risk.data_quality_flags)
    )
    if has_flags and not explanation.risk_summary:
        return False
    return True


def _check_no_forbidden_phrases(explanation: PickExplanation) -> bool:
    """Reject (not sanitize) any output containing a forbidden phrase."""
    dumped = json.dumps(explanation.model_dump(), ensure_ascii=False).lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in dumped:
            return False
    return True
