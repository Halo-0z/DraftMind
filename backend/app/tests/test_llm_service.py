from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.schemas.prospect import ProspectRead
from app.schemas.recommendation import (
    RankedProspectRead,
    RecommendResponse,
    ScoreBreakdown,
)
from app.schemas.team import TeamRead
from app.services.llm_service import LLMService, _explanation_from_payload, _parse_json_response


@pytest.fixture()
def mock_settings(monkeypatch) -> Settings:
    return Settings(llm_provider="mock", llm_api_key="")


def _build_recommendation() -> RecommendResponse:
    prospect = ProspectRead(
        id=1,
        year=2026,
        name="AJ Dybantsa",
        position="SF",
        age=19.3,
        height="6-9",
        weight=210,
        school_or_league="BYU",
        ppg=21.6,
        rpg=7.8,
        apg=3.4,
        fg_pct=49.2,
        three_pct=35.1,
        ft_pct=78.0,
        stocks=2.2,
        archetype="Two-way wing creator",
        upside_score=96,
        risk_score=28,
    )
    team = TeamRead(
        id=1,
        name="San Antonio Spurs",
        abbr="SAS",
        nba_team_id=1610612759,
        city="San Antonio",
        conference="West",
        division="Southwest",
    )
    alternative = RankedProspectRead(
        prospect=ProspectRead(
            id=2,
            year=2026,
            name="Braylon Mullins",
            position="SG",
            age=18.9,
            height="6-5",
            weight=190,
            school_or_league="UConn",
            ppg=14.8,
            rpg=4.0,
            apg=2.7,
            fg_pct=45.9,
            three_pct=40.1,
            ft_pct=81.0,
            stocks=1.3,
            archetype="Movement shooter",
            upside_score=82,
            risk_score=24,
        ),
        scores=ScoreBreakdown(
            talent_score=80,
            fit_score=70,
            pick_value_score=75,
            risk_penalty=20,
            final_score=78,
        ),
        reasons=["稳定投射"],
        risks=["对抗不足"],
    )
    return RecommendResponse(
        year=2026,
        pick=8,
        mode="gm_decision",
        team=team,
        recommended_player=RankedProspectRead(
            prospect=prospect,
            scores=ScoreBreakdown(
                talent_score=92,
                fit_score=80,
                pick_value_score=85,
                risk_penalty=18,
                final_score=86,
            ),
            reasons=["天赋本届第一", "适配锋线缺口"],
            risks=["需要提升三分"],
        ),
        alternatives=[alternative],
    )


def test_llm_service_uses_mock_when_no_key(mock_settings: Settings) -> None:
    service = LLMService(settings=mock_settings)
    assert service.is_mock
    assert service.provider == "mock"


def test_llm_service_switches_to_hunyuan_when_key_present() -> None:
    service = LLMService(
        settings=Settings(llm_provider="mock", llm_api_key="sk-test", llm_model="hunyuan-turbos-latest"),
    )
    assert not service.is_mock
    assert service.provider == "hunyuan"


def test_hunyuan_call_falls_back_to_mock_on_failure(
    monkeypatch, mock_settings: Settings
) -> None:
    service = LLMService(settings=Settings(llm_api_key="sk-test"))

    def _raise(*_args, **_kwargs):  # noqa: ANN001
        raise RuntimeError("network down")

    monkeypatch.setattr(service, "_hunyuan_explanation", _raise)

    explanation = service.explain_recommendation(
        recommendation=_build_recommendation(),
        question="为什么不选 Braylon Mullins？",
    )
    assert "Braylon Mullins" in explanation.follow_up_answer


def test_parse_json_response_handles_markdown_fences() -> None:
    payload = "```json\n{\"a\": 1}\n```"
    parsed = _parse_json_response(payload)
    assert parsed == {"a": 1}


def test_explanation_from_payload_merges_lists() -> None:
    rec = _build_recommendation()
    payload = {
        "gm_summary": "GM 视角总结。",
        "recommendation_reasons": ["理由 1", "理由 2"],
        "risks": ["风险 1"],
        "alternatives": ["备选 1"],
        "follow_up_answer": "追问回答。",
    }
    explanation = _explanation_from_payload(
        payload,
        rec,
        question="?",
        rag_context="",
    )
    assert explanation.gm_summary == "GM 视角总结。"
    assert explanation.recommendation_reasons == ["理由 1", "理由 2"]
    assert explanation.risks == ["风险 1"]
