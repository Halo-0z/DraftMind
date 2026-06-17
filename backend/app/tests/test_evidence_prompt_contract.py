"""Tests for the pick explanation prompt contract (RAG-v0-M3.0-A).

These tests lock down the *string contract* that governs LLM pick
explanations.  No LLM is called — we only assert on the prompt text produced
by ``app.services.evidence_prompt_contract``.

Coverage:

1. Prompt says the LLM may only use ``PickEvidencePackage``.
2. Prompt says the LLM may only explain ``selected_player``.
3. Prompt forbids recommending a replacement.
4. Prompt forbids reranking and adjusting scores.
5. Prompt forbids changing ``selected_player`` / ``final_score`` /
   ``prediction_sort_score``.
6. Prompt requires referencing ``citations`` / ``retrieved_evidence``.
7. Prompt requires stating ``evidence_sufficiency``.
8. Prompt requires describing ``conflict_evidence`` when present.
9. Prompt requires describing ``risk_evidence`` when present.
10. Prompt states ``manual_note`` is read-only evidence, not scored.
11. Prompt never shows forbidden field names as output-schema examples
    (they may only appear in the explicit forbidden-fields block).
"""

from __future__ import annotations

import re

from app.services.evidence_prompt_contract import (
    EVIDENCE_EXPLANATION_DEVELOPER_PROMPT,
    EVIDENCE_EXPLANATION_SYSTEM_PROMPT,
    FORBIDDEN_OUTPUT_FIELDS,
    OUTPUT_SCHEMA_EXAMPLE,
    build_pick_explanation_prompt_contract,
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


def _full_contract() -> str:
    return EVIDENCE_EXPLANATION_SYSTEM_PROMPT + "\n" + EVIDENCE_EXPLANATION_DEVELOPER_PROMPT


def _extract_output_schema_block(prompt: str) -> str:
    """Extract the JSON output-schema example block from the developer prompt.

    The block is delimited by ```json ... ```.  We assert that exactly one such
    block exists and that it equals ``OUTPUT_SCHEMA_EXAMPLE``.
    """
    matches = re.findall(r"```json\n(.*?)\n```", prompt, flags=re.DOTALL)
    assert len(matches) == 1, f"Expected exactly one json block, found {len(matches)}"
    return matches[0]


def _extract_forbidden_block(prompt: str) -> str:
    """Extract the forbidden-output-fields section from the developer prompt.

    The section starts after the heading "Forbidden output fields" and ends at
    the next "## " heading or the "Final reminders" section.
    """
    match = re.search(
        r"Forbidden output fields\s*\n(.*?)(?:\n## |\Z)",
        prompt,
        flags=re.DOTALL,
    )
    assert match is not None, "Forbidden output fields section not found"
    return match.group(1)


# ---------------------------------------------------------------------------
# Builder / structure
# ---------------------------------------------------------------------------


def test_builder_returns_system_and_developer_prompts() -> None:
    contract = build_pick_explanation_prompt_contract()
    assert set(contract.keys()) == {"system", "developer"}
    assert contract["system"] == EVIDENCE_EXPLANATION_SYSTEM_PROMPT
    assert contract["developer"] == EVIDENCE_EXPLANATION_DEVELOPER_PROMPT
    assert contract["system"]
    assert contract["developer"]


def test_forbidden_output_fields_constant_matches_spec() -> None:
    # Sanity: the constant itself must contain every spec-required forbidden
    # field name, so the prompt can reference them.
    assert set(FORBIDDEN_OUTPUT_FIELDS) == FORBIDDEN_FIELDS


# ---------------------------------------------------------------------------
# Guardrail 1: only based on PickEvidencePackage
# ---------------------------------------------------------------------------


def test_prompt_says_only_based_on_pick_evidence_package() -> None:
    text = _full_contract().lower()
    assert "pickevidencepackage" in text
    assert "sole source of truth" in EVIDENCE_EXPLANATION_SYSTEM_PROMPT.lower()
    assert "pickEvidencePackage".lower() in EVIDENCE_EXPLANATION_DEVELOPER_PROMPT.lower()


# ---------------------------------------------------------------------------
# Guardrail 2: only explain selected_player
# ---------------------------------------------------------------------------


def test_prompt_says_only_explain_selected_player() -> None:
    text = _full_contract().lower()
    assert "selected_player" in text
    assert "only explain the already-locked" in text


# ---------------------------------------------------------------------------
# Guardrail 3: no replacement
# ---------------------------------------------------------------------------


def test_prompt_forbids_recommending_replacement() -> None:
    text = _full_contract().lower()
    assert "do not recommend a replacement" in text
    assert "should have selected another player" in text


# ---------------------------------------------------------------------------
# Guardrail 4: no rerank / no score adjustment
# ---------------------------------------------------------------------------


def test_prompt_forbids_rerank_and_score_adjustment() -> None:
    text = _full_contract().lower()
    assert "do not rerank" in text
    assert "do not adjust any score" in text


# ---------------------------------------------------------------------------
# Guardrail 5: no changing selected_player / final_score / prediction_sort_score
# ---------------------------------------------------------------------------


def test_prompt_forbids_changing_core_decision_fields() -> None:
    text = _full_contract().lower()
    assert "do not change ``selected_player``" in text
    assert "do not change ``final_score``" in text
    assert "do not change ``prediction_sort_score``" in text


# ---------------------------------------------------------------------------
# Guardrail 6: must reference citations / retrieved_evidence
# ---------------------------------------------------------------------------


def test_prompt_requires_referencing_citations() -> None:
    text = _full_contract().lower()
    assert "citation_refs" in text
    assert "citations" in text
    assert "source_id" in text
    # The prompt must explicitly forbid fabricating citations.
    assert "must not fabricate citations" in text


# ---------------------------------------------------------------------------
# Guardrail 7: must state evidence_sufficiency
# ---------------------------------------------------------------------------


def test_prompt_requires_stating_evidence_sufficiency() -> None:
    text = _full_contract().lower()
    assert "evidence_sufficiency" in text
    assert "you must state the ``evidence_sufficiency`` level" in text


def test_prompt_requires_describing_limited_or_insufficient_sufficiency() -> None:
    text = _full_contract().lower()
    assert "limited" in text
    assert "insufficient" in text
    assert "limitations" in text


# ---------------------------------------------------------------------------
# Guardrail 8: must describe conflict_evidence
# ---------------------------------------------------------------------------


def test_prompt_requires_describing_conflict_evidence() -> None:
    text = _full_contract().lower()
    assert "conflict_evidence" in text
    assert "conflict" in text


# ---------------------------------------------------------------------------
# Guardrail 9: must describe risk_evidence
# ---------------------------------------------------------------------------


def test_prompt_requires_describing_risk_evidence() -> None:
    text = _full_contract().lower()
    assert "risk_evidence" in text
    assert "risk_summary" in text


# ---------------------------------------------------------------------------
# Guardrail 10: manual_note is read-only, not scored
# ---------------------------------------------------------------------------


def test_prompt_states_manual_note_is_read_only_and_not_scored() -> None:
    text = _full_contract().lower()
    assert "manual_note" in text
    assert "retrieved_evidence" in text
    assert "read-only" in text
    assert "never participate in scoring" in text


# ---------------------------------------------------------------------------
# Guardrail 11: forbidden field names never appear as output-schema examples
# ---------------------------------------------------------------------------


def test_output_schema_example_does_not_contain_forbidden_fields() -> None:
    schema_block = _extract_output_schema_block(EVIDENCE_EXPLANATION_DEVELOPER_PROMPT)
    assert schema_block == OUTPUT_SCHEMA_EXAMPLE
    for name in FORBIDDEN_FIELDS:
        assert name not in schema_block, (
            f"Forbidden field '{name}' leaked into output schema example."
        )


def test_output_schema_example_contains_required_pick_explanation_fields() -> None:
    schema_block = _extract_output_schema_block(EVIDENCE_EXPLANATION_DEVELOPER_PROMPT)
    required = {
        "pick_number",
        "team_abbr",
        "selected_player_id",
        "selected_player_name",
        "decision_locked",
        "llm_can_modify_decision",
        "summary",
        "key_reasons",
        "market_context",
        "risk_summary",
        "evidence_notes",
        "citation_refs",
        "limitations",
    }
    for field in required:
        assert field in schema_block, (
            f"Required field '{field}' missing from output schema example."
        )


def test_forbidden_fields_appear_only_in_forbidden_block() -> None:
    """Forbidden field names may appear in the explicit forbidden-fields
    section, but must NOT appear anywhere else in the developer prompt
    (in particular, not in the output schema example)."""
    forbidden_block = _extract_forbidden_block(EVIDENCE_EXPLANATION_DEVELOPER_PROMPT)
    for name in FORBIDDEN_FIELDS:
        assert name in forbidden_block, (
            f"Forbidden field '{name}' missing from forbidden-fields block."
        )

    # Remove the forbidden block from the prompt; none of the forbidden names
    # should remain in the rest of the prompt.
    prompt_without_forbidden_block = EVIDENCE_EXPLANATION_DEVELOPER_PROMPT.replace(
        forbidden_block, ""
    )
    for name in FORBIDDEN_FIELDS:
        assert name not in prompt_without_forbidden_block, (
            f"Forbidden field '{name}' appears outside the forbidden-fields block."
        )


def test_prompt_states_decision_locked_and_llm_cannot_modify() -> None:
    text = _full_contract().lower()
    assert "decision_locked" in text
    assert "llm_can_modify_decision" in text
    assert "always ``true``" in text or "always `true`" in text
    assert "always ``false``" in text or "always `false`" in text


def test_prompt_states_output_must_conform_to_pick_explanation() -> None:
    text = _full_contract().lower()
    assert "pickexplanation" in text
    assert "must be a single json object" in text or "single json object" in text


def test_prompt_does_not_call_real_llm() -> None:
    # The contract module must not import any LLM client or network module.
    # This is a lightweight guard; deeper isolation is enforced by the
    # milestone boundary.
    from app.services import evidence_prompt_contract as module

    source = open(module.__file__, encoding="utf-8").read().lower()
    assert "openai" not in source
    assert "anthropic" not in source
    assert "requests.post" not in source
    assert "httpx" not in source
    assert "socket" not in source
