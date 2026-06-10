from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import Settings, get_settings
from app.schemas.agent import AgentExplanation
from app.schemas.recommendation import RecommendResponse


logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "你是 DraftMind 的 GM 决策助理。"
    "你的唯一职责是把结构化评分结果用管理层语言解释清楚，禁止编造任何球员数据、"
    "球队战绩或新闻事件。给定的结构化字段包括：综合分、天赋分、适配分、签位价值分、"
    "风险扣分、推荐理由、风险提示和备选方案。请使用中文回答，结论先行，"
    "回答末尾用一句话重申「本回答不包含任何模型未给出的球员数据」。"
)


class LLMService:
    """Provider-aware LLM service for DraftMind explanations.

    Priority: hunyuan (real) > mock fallback. If the configured provider
    raises, the explanation transparently degrades to the deterministic
    mock so the demo never breaks because of quota / network issues.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # ---- public API -----------------------------------------------------

    @property
    def provider(self) -> str:
        if self.settings.llm_provider and self.settings.llm_provider != "mock":
            return self.settings.llm_provider
        return "hunyuan" if self.settings.llm_api_key else "mock"

    @property
    def model(self) -> str:
        return self.settings.llm_model

    @property
    def is_mock(self) -> bool:
        return self.provider == "mock"

    def explain_recommendation(
        self,
        recommendation: RecommendResponse,
        question: str,
        rag_context: str = "",
    ) -> AgentExplanation:
        if self.is_mock:
            return self._mock_explanation(recommendation, question, rag_context)

        try:
            return self._hunyuan_explanation(recommendation, question, rag_context)
        except Exception as exc:  # noqa: BLE001 - any provider failure falls back
            logger.warning("LLM call failed, falling back to mock: %s", exc)
            return self._mock_explanation(recommendation, question, rag_context)

    # ---- real provider: 腾讯混元 (OpenAI 兼容) -------------------------

    def _hunyuan_explanation(
        self,
        recommendation: RecommendResponse,
        question: str,
        rag_context: str,
    ) -> AgentExplanation:
        from openai import OpenAI  # local import: only needed when not in mock mode

        client = OpenAI(
            api_key=self.settings.llm_api_key,
            base_url=self.settings.llm_api_base,
            timeout=self.settings.llm_timeout,
        )

        payload = _build_payload(recommendation=recommendation, question=question, rag_context=rag_context)
        response = client.chat.completions.create(
            model=self.settings.llm_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": payload},
            ],
            temperature=0.3,
            max_tokens=900,
        )
        text = (response.choices[0].message.content or "").strip()
        parsed = _parse_json_response(text)
        if parsed is None:
            # Defensive: never let a malformed response leak raw text.
            logger.warning("Hunyuan returned non-JSON output, using mock fallback.")
            return self._mock_explanation(recommendation, question, rag_context)
        return _explanation_from_payload(parsed, recommendation, question, rag_context)

    # ---- mock fallback --------------------------------------------------

    def _mock_explanation(
        self,
        recommendation: RecommendResponse,
        question: str,
        rag_context: str,
    ) -> AgentExplanation:
        recommended = recommendation.recommended_player
        alternatives = recommendation.alternatives
        player = recommended.prospect

        alternative_lines = [
            (
                f"{item.prospect.name}: 综合分 {item.scores.final_score}, "
                f"优势是{item.reasons[0] if item.reasons else '整体评分接近'}, "
                f"但相对推荐人选的适配或风险略逊。"
            )
            for item in alternatives
        ]

        follow_up_answer = self._answer_follow_up(
            recommendation=recommendation,
            question=question,
        )

        return AgentExplanation(
            recommendation_reasons=[
                f"{player.name} 的综合分为 {recommended.scores.final_score}，在当前候选池排名第一。",
                *recommended.reasons[:3],
            ],
            risks=recommended.risks,
            alternatives=alternative_lines,
            gm_summary=(
                f"以 {recommendation.team.abbr} 在第 {recommendation.pick} 顺位的需求看，"
                f"{player.name} 同时覆盖位置缺口、技能适配和签位价值，是当前最像管理层会提交的选择。"
            ),
            follow_up_answer=follow_up_answer,
        )

    def _answer_follow_up(
        self,
        recommendation: RecommendResponse,
        question: str,
    ) -> str:
        normalized_question = question.lower()
        recommended = recommendation.recommended_player

        for alternative in recommendation.alternatives:
            alt_name = alternative.prospect.name.lower()
            alt_last_name = alternative.prospect.name.split()[-1].lower()
            asks_alt = alt_name in normalized_question or alt_last_name in normalized_question
            asks_why_not = "为什么不选" in question or "why not" in normalized_question
            if asks_alt or asks_why_not:
                return (
                    f"不优先选择 {alternative.prospect.name} 的主要原因是："
                    f"{alternative.prospect.name} 综合分 {alternative.scores.final_score}，"
                    f"低于 {recommended.prospect.name} 的 {recommended.scores.final_score}。"
                    f"推荐人选在适配分为 {recommended.scores.fit_score}，"
                    f"风险扣分为 {recommended.scores.risk_penalty}；"
                    f"{alternative.prospect.name} 的适配分为 {alternative.scores.fit_score}，"
                    f"风险扣分为 {alternative.scores.risk_penalty}。"
                )

        if "风险" in question or "risk" in normalized_question:
            return (
                f"{recommended.prospect.name} 的主要风险是："
                f"{'；'.join(recommended.risks)}。这些风险没有推翻推荐，"
                "因为他的综合分和球队适配仍领先。"
            )

        return (
            f"这次推荐不是由模型凭空生成，而是先由 ranking_engine 计算。"
            f"{recommended.prospect.name} 在天赋、适配、签位价值和风险修正后总分最高，"
            "所以 Agent 只负责把结构化结果解释成人能听懂的 GM 决策语言。"
        )


# ---------------------------------------------------------------------------
# Prompt + response helpers
# ---------------------------------------------------------------------------


def _build_payload(
    *,
    recommendation: RecommendResponse,
    question: str,
    rag_context: str,
) -> str:
    rec = recommendation.recommended_player
    alt_lines = [
        f"- {a.prospect.name}({a.prospect.position})：综合分 {a.scores.final_score}，"
        f"适配 {a.scores.fit_score}，风险扣 {a.scores.risk_penalty}，"
        f"理由: {'; '.join(a.reasons) or '无'}"
        for a in recommendation.alternatives
    ]
    reasons = "; ".join(rec.reasons) or "无"
    risks = "; ".join(rec.risks) or "无"

    return (
        "请基于以下结构化结果，回答 GM 的追问并输出 JSON。\n"
        f"球队: {recommendation.team.abbr} ({recommendation.team.name})\n"
        f"签位: 第 {recommendation.pick} 顺位\n"
        f"推荐球员: {rec.prospect.name} ({rec.prospect.position}, "
        f"{rec.prospect.school_or_league})\n"
        f"评分: 综合 {rec.scores.final_score}, 天赋 {rec.scores.talent_score}, "
        f"适配 {rec.scores.fit_score}, 签位价值 {rec.scores.pick_value_score}, "
        f"风险扣 {rec.scores.risk_penalty}\n"
        f"推荐理由: {reasons}\n"
        f"风险: {risks}\n"
        f"备选: \n" + "\n".join(alt_lines) + "\n"
        + (f"\n球探 / 新闻上下文(已确认，可引用):\n{rag_context}\n" if rag_context else "")
        + f"\nGM 追问: {question or '请解释这次推荐。'}\n\n"
        "请只输出 JSON，结构如下：\n"
        "{\n"
        '  "gm_summary": "一句话总结",\n'
        '  "recommendation_reasons": ["理由1", "理由2"],\n'
        '  "risks": ["风险1"],\n'
        '  "alternatives": ["备选说明"],\n'
        '  "follow_up_answer": "对追问的直接回答"\n'
        "}\n"
        "注意：禁止编造任何球员数据；未给出的数字请留空或写「未提供」。"
    )


def _parse_json_response(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    candidate = match.group(0) if match else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _explanation_from_payload(
    payload: dict[str, Any],
    recommendation: RecommendResponse,
    question: str,
    rag_context: str,
) -> AgentExplanation:
    fallback = LLMService()._mock_explanation(recommendation, question, rag_context)

    def _list(key: str) -> list[str]:
        value = payload.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return fallback.model_dump().get(key, [])

    summary = str(payload.get("gm_summary") or "").strip() or fallback.gm_summary
    follow_up = str(payload.get("follow_up_answer") or "").strip() or fallback.follow_up_answer

    return AgentExplanation(
        gm_summary=summary,
        recommendation_reasons=_list("recommendation_reasons"),
        risks=_list("risks"),
        alternatives=_list("alternatives"),
        follow_up_answer=follow_up,
    )
