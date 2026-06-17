"""RAG-v0-M3.1-B: Real LLM explanation service shell with safe fallback.

This module provides a guarded shell around an LLM client that converts a
``PickEvidencePackage`` into a ``PickExplanation``.  The shell is deliberately
defensive: any LLM failure, boundary violation, or unsafe output causes an
immediate fallback to the deterministic ``build_mock_pick_explanation``.

Design rules enforced here and covered by
``test_evidence_llm_explanation_service.py``:

1. ``llm_client is None`` → fallback to mock immediately (no network).
2. LLM input is ONLY ``PickEvidencePackage.model_dump()`` — no
   ``candidate_board``, ``alternatives``, ``simulation``, DB, or ranking data.
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
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from app.schemas.evidence import PickEvidencePackage, PickExplanation
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
        2. Sends ONLY ``evidence.model_dump()`` as the user payload.
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

    The user message contains ONLY ``evidence.model_dump()`` — no
    ``candidate_board``, ``alternatives``, ``simulation``, DB, or ranking
    data is attached.
    """
    contract = build_pick_explanation_prompt_contract()
    messages: list[dict[str, str]] = [
        {"role": "system", "content": contract["system"]},
        {"role": "developer", "content": contract["developer"]},
        {
            "role": "user",
            "content": json.dumps(evidence.model_dump(), ensure_ascii=False),
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
