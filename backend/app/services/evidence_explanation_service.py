"""RAG-v0-M3.0-B: Deterministic mock pick explanation service.

This module contains a single pure function:

    build_mock_pick_explanation(evidence: PickEvidencePackage) -> PickExplanation

It converts an already-locked ``PickEvidencePackage`` into a read-only
``PickExplanation`` using deterministic rules — no LLM, no DB, no network.

Design rules enforced here and covered by
``test_evidence_explanation_service.py``:

1. The function is pure: it reads ``evidence`` and returns a new
   ``PickExplanation``.  It never mutates the input.
2. Identity fields (``pick_number`` / ``team_abbr`` / ``selected_player_id`` /
   ``selected_player_name``) are copied verbatim.
3. ``decision_locked`` is always ``True`` and ``llm_can_modify_decision`` is
   always ``False`` — these come from the ``PickExplanation`` schema defaults.
4. No forbidden override / rerank / replacement field is ever emitted.
5. No dangerous natural-language phrase ("应该选别人", "rerank",
   "replacement player", ...) is ever emitted.
6. ``manual_note`` retrieved evidence is tagged as read-only and never
   described as a scoring factor.
7. ``citation_refs`` only reference ``source_id`` / ``title`` / ``url``
   already present in ``evidence.citations``.
8. ``limitations`` always reflects ``evidence_sufficiency`` and any
   ``conflict_evidence``.
"""

from __future__ import annotations

import re

from app.schemas.evidence import (
    EvidenceCitation,
    PickEvidencePackage,
    PickExplanation,
    RetrievedEvidence,
)


# ---------------------------------------------------------------------------
# Forbidden natural-language phrases.
#
# These must never appear in any text field of the generated
# ``PickExplanation``.  Tests assert that the dumped JSON does not contain
# any of them (case-insensitive).
# ---------------------------------------------------------------------------
FORBIDDEN_PHRASES: tuple[str, ...] = (
    # Chinese
    "应该选别人",
    "更好的选择",
    "建议改选",
    "应当重新排序",
    "重新排序候选人",
    "重新排序",
    "根据 manual note 提升分数",
    "提升分数",
    "加权",
    "替代人选",
    # English
    "better pick",
    "replacement player",
    "should have selected",
    "rerank",
    "adjust score",
    "score boost",
    "manual note boost",
)


def _format_score(score: float | None) -> str:
    if score is None:
        return "N/A"
    return f"{score:.1f}"


# Pre-compile a case-insensitive regex that matches any forbidden phrase.
# This is used by ``_sanitize_text`` to scrub input-derived text before it
# enters the explanation output, so a malicious / poisoned evidence package
# cannot smuggle dangerous phrases (e.g. "建议改选", "replacement player",
# "rerank") through the mock explanation.
_FORBIDDEN_PHRASES_PATTERN = re.compile(
    "|".join(re.escape(phrase) for phrase in FORBIDDEN_PHRASES),
    flags=re.IGNORECASE,
)


def _sanitize_text(text: str | None) -> str:
    """Return ``text`` with every forbidden phrase replaced by ``[redacted]``.

    If ``text`` is ``None`` or empty, returns an empty string.  The comparison
    is case-insensitive so English phrases like ``"Rerank"`` or ``"BETTER PICK"``
    are also caught.
    """
    if not text:
        return ""
    return _FORBIDDEN_PHRASES_PATTERN.sub("[redacted]", text)


def _sanitize_optional(text: str | None) -> str | None:
    """Like ``_sanitize_text`` but preserves ``None`` for optional fields."""
    if text is None:
        return None
    return _sanitize_text(text)


def _build_summary(evidence: PickEvidencePackage) -> str:
    """Build a short, safe summary string.

    Never mentions replacements, "should", "better pick", reranking, or score
    adjustments.
    """
    parts: list[str] = []
    parts.append(f"第 {evidence.pick_number} 顺位")
    if evidence.team_abbr:
        parts.append(f"由 {evidence.team_abbr} 选择")
    parts.append(f"{evidence.selected_player_name}")

    ranking = evidence.ranking_evidence
    if ranking is not None and ranking.final_score is not None:
        parts.append(f"（final_score {_format_score(ranking.final_score)}）")

    market = evidence.market_evidence
    if market is not None and market.has_market_reference:
        if market.market_alignment_label:
            parts.append(f"市场参考：{_sanitize_text(market.market_alignment_label)}")
        if market.market_pick_delta is not None:
            parts.append(f"市场偏差 {market.market_pick_delta:+d}")

    summary = "，".join(parts) + "。"
    return summary[:1200]


def _build_key_reasons(evidence: PickEvidencePackage) -> list[str]:
    """Extract up to 5 deterministic key reasons from the evidence package."""
    reasons: list[str] = []

    ranking = evidence.ranking_evidence
    if ranking is not None:
        if ranking.final_score is not None:
            reasons.append(
                f"final_score 为 {_format_score(ranking.final_score)}，"
                "为候选池中的结构化评分依据。"
            )
        if ranking.prediction_sort_score is not None:
            reasons.append(
                f"prediction_sort_score 为 "
                f"{_format_score(ranking.prediction_sort_score)}，"
                "为预测辅助分（只读展示，不改变原始评分）。"
            )
        if ranking.rank_in_available_pool is not None:
            reasons.append(
                f"候选池排名 #{ranking.rank_in_available_pool}。"
            )

    team_fit = evidence.team_fit_evidence
    if team_fit is not None and team_fit.matched_needs:
        sanitized_needs = [
            _sanitize_text(need) for need in team_fit.matched_needs[:3] if need
        ]
        sanitized_needs = [need for need in sanitized_needs if need]
        if sanitized_needs:
            reasons.append(
                "匹配球队需求：" + "、".join(sanitized_needs) + "。"
            )

    market = evidence.market_evidence
    if market is not None and market.market_alignment_notes:
        sanitized_note = _sanitize_text(market.market_alignment_notes[0])
        if sanitized_note:
            reasons.append(sanitized_note)

    return reasons[:5]


def _build_market_context(evidence: PickEvidencePackage) -> str | None:
    market = evidence.market_evidence
    if market is None or not market.has_market_reference:
        return "市场证据有限。"

    parts: list[str] = []
    if market.market_expected_pick is not None:
        parts.append(f"市场预计第 {market.market_expected_pick} 顺位")
    if market.market_range_min is not None and market.market_range_max is not None:
        parts.append(
            f"选秀区间 {market.market_range_min}-{market.market_range_max}"
        )
    parts.append(f"实际选择第 {evidence.pick_number} 顺位")
    if market.market_pick_delta is not None:
        parts.append(f"偏差 {market.market_pick_delta:+d}")
    if market.market_alignment_label:
        parts.append(f"一致性：{_sanitize_text(market.market_alignment_label)}")

    return "；".join(parts) + "。"


def _build_risk_summary(evidence: PickEvidencePackage) -> str | None:
    risk = evidence.risk_evidence
    if risk is None:
        return None

    raw_flags: list[str] = []
    raw_flags.extend(risk.diagnostics_warnings or [])
    raw_flags.extend(risk.market_risk_flags or [])
    raw_flags.extend(risk.stats_risk_flags or [])
    raw_flags.extend(risk.data_quality_flags or [])

    flags = [_sanitize_text(flag) for flag in raw_flags]
    flags = [flag for flag in flags if flag]

    if not flags:
        if risk.overall_risk_level:
            sanitized_level = _sanitize_text(risk.overall_risk_level)
            if sanitized_level:
                return f"整体风险等级：{sanitized_level}。"
        return None

    summary = "风险提示：" + "；".join(flags[:5]) + "。"
    return summary[:800]


def _build_evidence_notes(evidence: PickEvidencePackage) -> list[str]:
    notes: list[str] = []
    for item in evidence.retrieved_evidence or []:
        note = _format_retrieved_evidence_note(item)
        if note:
            notes.append(note)
        if len(notes) >= 6:
            break
    return notes[:6]


def _format_retrieved_evidence_note(item: RetrievedEvidence) -> str:
    source_type = item.source_type or "unknown"
    is_manual = source_type == "manual_note"

    parts: list[str] = []
    if is_manual:
        parts.append("人工备注（只读证据，不参与评分）")
    else:
        parts.append(f"source_type={_sanitize_text(source_type)}")

    if item.title:
        sanitized_title = _sanitize_text(item.title)
        if sanitized_title:
            parts.append(f"标题：{sanitized_title}")

    excerpt = _sanitize_text((item.excerpt or "").strip())
    if excerpt:
        # Truncate to keep the note readable and within reason.
        parts.append(excerpt[:200])

    if item.relevance_reason:
        sanitized_reason = _sanitize_text(item.relevance_reason)
        if sanitized_reason:
            parts.append(f"相关性：{sanitized_reason}")

    if is_manual:
        parts.append("人工备注为只读证据，不参与评分。")

    return " | ".join(parts)


def _build_citation_refs(evidence: PickEvidencePackage) -> list[str]:
    """Return citation refs drawn ONLY from existing citations.

    Each ref is the first available of ``source_id`` / ``title`` / ``url``.
    Never fabricates a citation.
    """
    refs: list[str] = []
    for citation in evidence.citations or []:
        ref = _citation_ref(citation)
        if ref:
            refs.append(ref)
        if len(refs) >= 10:
            break
    return refs[:10]


def _citation_ref(citation: EvidenceCitation) -> str | None:
    """Return the first available of ``source_id`` / ``title`` / ``url``,
    sanitized so forbidden phrases cannot leak into ``citation_refs``.

    The ref still originates from the input citation — no citation is
    fabricated.  Only dangerous phrases are redacted.
    """
    if citation.source_id:
        return _sanitize_text(citation.source_id) or None
    if citation.title:
        return _sanitize_text(citation.title) or None
    if citation.url:
        return _sanitize_text(citation.url) or None
    return None


def _build_limitations(evidence: PickEvidencePackage) -> list[str]:
    limitations: list[str] = []

    sufficiency = evidence.evidence_sufficiency
    level = (sufficiency.level or "").lower() if sufficiency.level else ""
    if level in ("limited", "insufficient"):
        # Use the raw level for the logic check, but sanitize for display
        # in case a future caller injects a poisoned level string.
        sanitized_level = _sanitize_text(sufficiency.level) or sufficiency.level
        limitations.append(
            f"evidence_sufficiency 为 {sanitized_level}，"
            "解释能力受限。"
        )
    if sufficiency.missing_sections:
        sanitized_missing = [
            _sanitize_text(s) for s in sufficiency.missing_sections[:3] if s
        ]
        sanitized_missing = [s for s in sanitized_missing if s]
        if sanitized_missing:
            limitations.append(
                "缺失证据区块：" + "、".join(sanitized_missing) + "。"
            )
    if sufficiency.weak_sections:
        sanitized_weak = [
            _sanitize_text(s) for s in sufficiency.weak_sections[:3] if s
        ]
        sanitized_weak = [s for s in sanitized_weak if s]
        if sanitized_weak:
            limitations.append(
                "薄弱证据区块：" + "、".join(sanitized_weak) + "。"
            )
    if sufficiency.explanation_limits:
        sanitized_limits = [
            _sanitize_text(s)
            for s in sufficiency.explanation_limits[:2]
            if s
        ]
        sanitized_limits = [s for s in sanitized_limits if s]
        limitations.extend(sanitized_limits)

    for conflict in evidence.conflict_evidence or []:
        sanitized_type = _sanitize_text(conflict.type) or conflict.type
        sanitized_severity = _sanitize_text(conflict.severity) or conflict.severity
        sanitized_desc = _sanitize_text(conflict.description)
        limitations.append(
            f"冲突证据（{sanitized_type}，{sanitized_severity}）："
            f"{sanitized_desc}"
        )

    return limitations[:5]


def build_mock_pick_explanation(
    evidence: PickEvidencePackage,
) -> PickExplanation:
    """Convert a ``PickEvidencePackage`` into a read-only ``PickExplanation``.

    This function is deterministic and pure:
    - No LLM, no DB, no network, no ranking_engine call.
    - Does not mutate ``evidence``.
    - Does not change ``selected_player`` / ``final_score`` /
      ``prediction_sort_score`` — those are only read for display.
    - Never emits forbidden override / rerank / replacement fields.
    - Never emits forbidden natural-language phrases.
    """
    return PickExplanation(
        pick_number=evidence.pick_number,
        team_abbr=evidence.team_abbr,
        selected_player_id=evidence.selected_player_id,
        selected_player_name=evidence.selected_player_name,
        # decision_locked / llm_can_modify_decision use schema defaults
        # (True / False), which are Literal-locked.
        summary=_build_summary(evidence),
        key_reasons=_build_key_reasons(evidence),
        market_context=_build_market_context(evidence),
        risk_summary=_build_risk_summary(evidence),
        evidence_notes=_build_evidence_notes(evidence),
        citation_refs=_build_citation_refs(evidence),
        limitations=_build_limitations(evidence),
    )
