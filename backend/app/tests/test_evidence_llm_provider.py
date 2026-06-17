"""Tests for the evidence LLM provider adapter (RAG-v0-M3.1-D).

These tests lock down the provider adapter safety layer:

1. Factory returns ``None`` when ``enable_real_llm_explanation=False``.
2. Factory returns ``None`` even with an API key when the flag is off.
3. Factory returns ``None`` when the flag is on but no API key.
4. Factory creates an adapter when flag+key are present (using fake transport).
5. ``.complete()`` returns provider content on success.
6. Empty content raises ``EvidenceLLMProviderError``.
7. Provider timeout/exception raises ``EvidenceLLMProviderError``.
8. Adapter does not receive ``PickEvidencePackage``.
9. Adapter does not call ``build_pick_explanation_prompt_contract()``.
10. Adapter does not import DB modules.
11. Adapter does not import ranking/prediction/simulation.
12. Adapter does not call build_pick_evidence / build_mock_pick_explanation /
    build_llm_pick_explanation.
13. Adapter does not read candidate_board / alternatives / simulation.
14. Adapter does not log API key / full messages / raw output.
15. Config defaults are correct.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.services.evidence_llm_provider import (
    EvidenceLLMProviderError,
    OpenAICompatibleEvidenceLLMClient,
    build_evidence_llm_client,
)


# ---------------------------------------------------------------------------
# Fake transport
# ---------------------------------------------------------------------------


class FakeTransport:
    """Fake OpenAI-compatible transport for testing."""

    def __init__(self, response: dict[str, Any] | Exception):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def chat_completions(
        self,
        *,
        api_key: str,
        api_base: str,
        model: str,
        messages: list[dict[str, str]],
        timeout: float,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "api_key": api_key,
                "api_base": api_base,
                "model": model,
                "messages": messages,
                "timeout": timeout,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _ok_response(content: str = "hello world") -> dict[str, Any]:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": content}}
        ]
    }


def _make_client(
    transport: FakeTransport,
    *,
    api_key: str = "sk-test",
    model: str = "test-model",
    api_base: str = "https://fake.example.com/v1",
    timeout: float = 10.0,
    max_tokens: int = 900,
    temperature: float = 0.0,
) -> OpenAICompatibleEvidenceLLMClient:
    return OpenAICompatibleEvidenceLLMClient(
        api_key=api_key,
        model=model,
        api_base=api_base,
        timeout=timeout,
        max_tokens=max_tokens,
        temperature=temperature,
        transport=transport,
    )


def _make_settings(
    *,
    enable: bool = False,
    api_key: str = "",
) -> Settings:
    return Settings(
        enable_real_llm_explanation=enable,
        llm_api_key=api_key,
        llm_model="test-model",
        llm_api_base="https://fake.example.com/v1",
    )


# ---------------------------------------------------------------------------
# 1-3. Factory default-off logic
# ---------------------------------------------------------------------------


def test_factory_returns_none_when_disabled() -> None:
    settings = _make_settings(enable=False, api_key="")
    assert build_evidence_llm_client(settings) is None


def test_factory_returns_none_when_disabled_even_with_key() -> None:
    settings = _make_settings(enable=False, api_key="sk-real-key")
    assert build_evidence_llm_client(settings) is None


def test_factory_returns_none_when_enabled_but_no_key() -> None:
    settings = _make_settings(enable=True, api_key="")
    assert build_evidence_llm_client(settings) is None


# ---------------------------------------------------------------------------
# 4. Factory creates adapter when enabled + key present
# ---------------------------------------------------------------------------


def test_factory_creates_adapter_when_enabled_and_key_present() -> None:
    settings = _make_settings(enable=True, api_key="sk-real-key")
    client = build_evidence_llm_client(settings)
    assert client is not None
    assert isinstance(client, OpenAICompatibleEvidenceLLMClient)


# ---------------------------------------------------------------------------
# 5. .complete() returns content on success
# ---------------------------------------------------------------------------


def test_complete_returns_content_on_success() -> None:
    transport = FakeTransport(_ok_response("explanation text"))
    client = _make_client(transport)
    result = client.complete([{"role": "user", "content": "hi"}])
    assert result == "explanation text"
    assert len(transport.calls) == 1


# ---------------------------------------------------------------------------
# 6. Empty content raises EvidenceLLMProviderError
# ---------------------------------------------------------------------------


def test_empty_content_raises_provider_error() -> None:
    transport = FakeTransport(_ok_response(""))
    client = _make_client(transport)
    with pytest.raises(EvidenceLLMProviderError, match="empty content"):
        client.complete([{"role": "user", "content": "hi"}])


def test_whitespace_only_content_raises_provider_error() -> None:
    transport = FakeTransport(_ok_response("   \n  "))
    client = _make_client(transport)
    with pytest.raises(EvidenceLLMProviderError, match="empty content"):
        client.complete([{"role": "user", "content": "hi"}])


def test_no_choices_raises_provider_error() -> None:
    transport = FakeTransport({"choices": []})
    client = _make_client(transport)
    with pytest.raises(EvidenceLLMProviderError, match="empty content"):
        client.complete([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# 7. Provider timeout / exception raises EvidenceLLMProviderError
# ---------------------------------------------------------------------------


def test_provider_timeout_raises_provider_error() -> None:
    transport = FakeTransport(TimeoutError("request timed out"))
    client = _make_client(transport)
    with pytest.raises(EvidenceLLMProviderError, match="provider call failed"):
        client.complete([{"role": "user", "content": "hi"}])


def test_provider_exception_raises_provider_error() -> None:
    transport = FakeTransport(ConnectionError("connection refused"))
    client = _make_client(transport)
    with pytest.raises(EvidenceLLMProviderError, match="provider call failed"):
        client.complete([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# 8. Adapter does not receive PickEvidencePackage
# ---------------------------------------------------------------------------


def test_adapter_does_not_receive_pick_evidence_package() -> None:
    from app.services import evidence_llm_provider as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "PickEvidencePackage" not in source


# ---------------------------------------------------------------------------
# 9. Adapter does not call build_pick_explanation_prompt_contract
# ---------------------------------------------------------------------------


def test_adapter_does_not_call_prompt_contract() -> None:
    from app.services import evidence_llm_provider as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "build_pick_explanation_prompt_contract" not in source
    assert "evidence_prompt_contract" not in source


# ---------------------------------------------------------------------------
# 10. Adapter does not import DB modules
# ---------------------------------------------------------------------------


def test_adapter_does_not_import_db_modules() -> None:
    from app.services import evidence_llm_provider as module

    forbidden = {
        "SessionLocal",
        "get_session",
        "sessionmaker",
        "create_engine",
        "Session",
        "get_db",
    }
    attrs = set(vars(module).keys())
    assert not (attrs & forbidden)

    source = open(module.__file__, encoding="utf-8").read().lower()
    assert "sessionlocal" not in source
    assert "get_db" not in source
    assert "get_session" not in source


# ---------------------------------------------------------------------------
# 11. Adapter does not import ranking/prediction/simulation
# ---------------------------------------------------------------------------


def test_adapter_does_not_import_ranking_prediction_simulation() -> None:
    from app.services import evidence_llm_provider as module

    source = open(module.__file__, encoding="utf-8").read().lower()
    assert "ranking_engine" not in source
    assert "prediction_calibration" not in source
    assert "simulation_service" not in source


# ---------------------------------------------------------------------------
# 12. Adapter does not call build_pick_evidence / build_mock / build_llm
# ---------------------------------------------------------------------------


def test_adapter_does_not_call_evidence_builders() -> None:
    from app.services import evidence_llm_provider as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "build_pick_evidence" not in source
    assert "build_mock_pick_explanation" not in source
    assert "build_llm_pick_explanation" not in source


# ---------------------------------------------------------------------------
# 13. Adapter does not read candidate_board / alternatives / simulation
# ---------------------------------------------------------------------------


def test_adapter_does_not_read_candidate_board_or_alternatives() -> None:
    from app.services import evidence_llm_provider as module

    source = open(module.__file__, encoding="utf-8").read().lower()
    assert "candidate_board" not in source
    assert "alternatives" not in source
    # "simulation" appears in "simulation_service" check above, but the adapter
    # should not reference it as a data field.
    assert "simulation" not in source.replace("simulation_service", "")


# ---------------------------------------------------------------------------
# 14. Adapter does not log API key / full messages / raw output
# ---------------------------------------------------------------------------


def test_adapter_does_not_log_secrets() -> None:
    from app.services import evidence_llm_provider as module

    source = open(module.__file__, encoding="utf-8").read().lower()
    # No logging of secrets.
    assert "logging" not in source or "logger" not in source
    # The adapter stores api_key but must not log it.
    # Check that there are no logging/print statements that include api_key.
    assert "print(" not in source
    assert "logger" not in source or source.count("logger") == 0


# ---------------------------------------------------------------------------
# 15. Config defaults
# ---------------------------------------------------------------------------


def test_config_defaults() -> None:
    settings = Settings()
    assert settings.enable_real_llm_explanation is False
    assert settings.llm_explanation_timeout == 10.0
    assert settings.llm_explanation_max_tokens == 900
    assert settings.llm_explanation_temperature == 0.0


# ---------------------------------------------------------------------------
# Additional: transport receives correct parameters
# ---------------------------------------------------------------------------


def test_transport_receives_correct_parameters() -> None:
    transport = FakeTransport(_ok_response("ok"))
    client = _make_client(
        transport,
        api_key="sk-test-123",
        model="gpt-test",
        api_base="https://fake.example.com/v1",
        timeout=15.0,
        max_tokens=500,
        temperature=0.2,
    )
    client.complete([{"role": "user", "content": "hi"}])
    call = transport.calls[0]
    assert call["api_key"] == "sk-test-123"
    assert call["model"] == "gpt-test"
    assert call["api_base"] == "https://fake.example.com/v1"
    assert call["timeout"] == 15.0
    assert call["max_tokens"] == 500
    assert call["temperature"] == 0.2
    assert call["messages"] == [{"role": "user", "content": "hi"}]


def test_factory_passes_settings_to_client() -> None:
    settings = Settings(
        enable_real_llm_explanation=True,
        llm_api_key="sk-factory-test",
        llm_model="factory-model",
        llm_api_base="https://factory.example.com/v1",
        llm_explanation_timeout=20.0,
        llm_explanation_max_tokens=800,
        llm_explanation_temperature=0.1,
    )
    client = build_evidence_llm_client(settings)
    assert client is not None
    # Verify the client has the right config by checking a transport call.
    transport = FakeTransport(_ok_response("ok"))
    client._transport = transport  # type: ignore[attr-defined]
    client.complete([{"role": "user", "content": "hi"}])
    call = transport.calls[0]
    assert call["api_key"] == "sk-factory-test"
    assert call["model"] == "factory-model"
    assert call["api_base"] == "https://factory.example.com/v1"
    assert call["timeout"] == 20.0
    assert call["max_tokens"] == 800
    assert call["temperature"] == 0.1
