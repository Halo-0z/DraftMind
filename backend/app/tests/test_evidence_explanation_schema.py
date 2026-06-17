"""Tests for the ``PickExplanation`` schema (RAG-v0-M3.0-A).

These tests lock down the read-only / display-only contract of the LLM
explanation output:

1. The schema can be created with valid input.
2. ``decision_locked`` defaults to ``True`` and rejects ``False``.
3. ``llm_can_modify_decision`` defaults to ``False`` and rejects ``True``.
4. ``pick_number`` must be in 1..60.
5. ``summary`` is required and non-empty.
6. List fields use ``default_factory`` and are not shared across instances.
7. None of the forbidden override / rerank / replacement fields appear in
   ``PickExplanation.model_fields``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.evidence import PickExplanation


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


def _valid_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "pick_number": 5,
        "team_abbr": "LAC",
        "selected_player_id": 101,
        "selected_player_name": "Keaton Sample",
        "summary": "DraftMind selected Keaton Sample because of his two-way wing defense and top-of-board final score.",
        "key_reasons": [
            "Highest final_score on the available board.",
            "Wing defense matches a core team need.",
        ],
        "market_context": "Market projected him around pick 7; DraftMind selected two picks earlier.",
        "risk_summary": "Low-confidence imported stats were used in ranking context.",
        "evidence_notes": [
            "manual_note: scouting summary highlights defensive versatility (read-only, not scored).",
        ],
        "citation_refs": ["manual_projection:101"],
        "limitations": [
            "evidence_sufficiency is limited; market projection has known gaps.",
        ],
    }
    base.update(overrides)
    return base


def test_pick_explanation_can_be_created_and_dumped() -> None:
    explanation = PickExplanation(**_valid_kwargs())
    dumped = explanation.model_dump()

    assert dumped["pick_number"] == 5
    assert dumped["team_abbr"] == "LAC"
    assert dumped["selected_player_id"] == 101
    assert dumped["selected_player_name"] == "Keaton Sample"
    assert dumped["decision_locked"] is True
    assert dumped["llm_can_modify_decision"] is False
    assert dumped["summary"].startswith("DraftMind selected")
    assert len(dumped["key_reasons"]) == 2
    assert dumped["market_context"] is not None
    assert dumped["risk_summary"] is not None
    assert len(dumped["evidence_notes"]) == 1
    assert dumped["citation_refs"] == ["manual_projection:101"]
    assert len(dumped["limitations"]) == 1
    assert explanation.model_dump_json()


def test_decision_locked_defaults_to_true() -> None:
    explanation = PickExplanation(**_valid_kwargs())
    assert explanation.decision_locked is True


def test_llm_can_modify_decision_defaults_to_false() -> None:
    explanation = PickExplanation(**_valid_kwargs())
    assert explanation.llm_can_modify_decision is False


def test_decision_locked_false_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PickExplanation(**_valid_kwargs(decision_locked=False))  # type: ignore[arg-type]


def test_llm_can_modify_decision_true_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PickExplanation(**_valid_kwargs(llm_can_modify_decision=True))  # type: ignore[arg-type]


@pytest.mark.parametrize("pick_number", [0, 61, -1, 100])
def test_pick_number_must_be_in_1_to_60(pick_number: int) -> None:
    with pytest.raises(ValidationError):
        PickExplanation(**_valid_kwargs(pick_number=pick_number))


@pytest.mark.parametrize("pick_number", [1, 30, 60])
def test_pick_number_accepts_valid_range(pick_number: int) -> None:
    explanation = PickExplanation(**_valid_kwargs(pick_number=pick_number))
    assert explanation.pick_number == pick_number


def test_summary_is_required() -> None:
    kwargs = _valid_kwargs()
    kwargs.pop("summary")
    with pytest.raises(ValidationError):
        PickExplanation(**kwargs)


def test_summary_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        PickExplanation(**_valid_kwargs(summary=""))


def test_summary_has_max_length() -> None:
    with pytest.raises(ValidationError):
        PickExplanation(**_valid_kwargs(summary="x" * 1201))


def test_list_fields_use_default_factory_and_are_not_shared() -> None:
    first = PickExplanation(
        pick_number=1,
        selected_player_name="Player A",
        summary="Summary A.",
    )
    second = PickExplanation(
        pick_number=2,
        selected_player_name="Player B",
        summary="Summary B.",
    )

    # Defaults are independent per-instance.
    assert first.key_reasons == []
    assert second.key_reasons == []
    first.key_reasons.append("shared?")
    assert second.key_reasons == []
    assert first.key_reasons == ["shared?"]

    # Same guarantee for the other list fields.
    for field in ("evidence_notes", "citation_refs", "limitations"):
        first_list = getattr(first, field)
        second_list = getattr(second, field)
        assert first_list == []
        assert second_list == []
        first_list.append("marker")
        assert second_list == []
        assert first_list == ["marker"]


def test_forbidden_fields_are_absent_from_model_fields() -> None:
    model_fields = set(PickExplanation.model_fields.keys())
    offending = model_fields & FORBIDDEN_FIELDS
    assert not offending, f"Forbidden fields leaked into PickExplanation: {offending}"


def test_forbidden_fields_cannot_be_set_via_extra() -> None:
    # extra="forbid" turns any unknown field — including dangerous override /
    # rerank / replacement fields — into a ValidationError rather than a
    # silently-ignored extra.
    with pytest.raises(ValidationError):
        PickExplanation(
            **_valid_kwargs(),
            replacement_player="Someone Else",  # type: ignore[call-arg]
        )


def test_unknown_extra_field_is_rejected() -> None:
    # Any unknown field, even an innocuous-looking one, must raise under
    # extra="forbid".  This is the strict boundary that prevents an LLM from
    # smuggling new keys through the output.
    with pytest.raises(ValidationError):
        PickExplanation(
            **_valid_kwargs(),
            unknown_field="anything",  # type: ignore[call-arg]
        )


def test_extra_forbid_does_not_accept_multiple_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PickExplanation(
            **_valid_kwargs(),
            foo="bar",  # type: ignore[call-arg]
            baz=123,  # type: ignore[call-arg]
        )


def test_optional_fields_accept_none() -> None:
    explanation = PickExplanation(
        pick_number=10,
        team_abbr=None,
        selected_player_id=None,
        selected_player_name="Anonymous Prospect",
        summary="Minimal explanation with optional fields set to None.",
        market_context=None,
        risk_summary=None,
    )
    assert explanation.team_abbr is None
    assert explanation.selected_player_id is None
    assert explanation.market_context is None
    assert explanation.risk_summary is None


def test_list_fields_enforce_max_length() -> None:
    with pytest.raises(ValidationError):
        PickExplanation(**_valid_kwargs(key_reasons=[f"reason {i}" for i in range(6)]))
    with pytest.raises(ValidationError):
        PickExplanation(
            **_valid_kwargs(evidence_notes=[f"note {i}" for i in range(7)])
        )
    with pytest.raises(ValidationError):
        PickExplanation(
            **_valid_kwargs(citation_refs=[f"ref {i}" for i in range(11)])
        )
    with pytest.raises(ValidationError):
        PickExplanation(
            **_valid_kwargs(limitations=[f"limit {i}" for i in range(6)])
        )
