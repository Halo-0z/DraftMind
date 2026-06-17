"""RAG-v0-M3.1-D: Provider adapter safety layer for evidence explanation.

This module provides an OpenAI-compatible adapter that converts
``messages -> text``.  It is deliberately thin:

- It does NOT receive evidence packages.
- It does NOT construct prompts.
- It does NOT do schema validation.
- It does NOT do citation / risk / conflict / dangerous-phrase checks.
- It does NOT query the DB.
- It does NOT call ranking / prediction / draft services.

All safety responsibilities remain in the upstream explanation shell.

The factory is OFF by default.  Even if an API key is present, the adapter is
only created when the explicit enable flag is ``True`` AND a key is configured.
Otherwise the factory returns ``None``, causing the upstream shell to fall
back to the deterministic mock explanation.

No real network requests are made in tests — tests inject a fake transport.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.config import Settings, get_settings


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class EvidenceLLMProviderError(RuntimeError):
    """Raised when the provider adapter cannot produce a valid text response.

    The upstream shell catches this (and any other exception) and falls back
    to the deterministic mock explanation.
    """


# ---------------------------------------------------------------------------
# Transport protocol
# ---------------------------------------------------------------------------


class _Transport(Protocol):
    """Minimal protocol for an OpenAI-compatible chat completion transport.

    Real providers are NOT imported at module load time.  In production a
    transport wrapping the ``openai`` SDK is used; in tests a fake transport
    is injected.
    """

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
        """Return the raw provider response dict."""
        ...


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class OpenAICompatibleEvidenceLLMClient:
    """OpenAI-compatible adapter that only does ``messages -> text``.

    This class implements the ``LLMClient`` protocol expected by the
    upstream explanation shell.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        api_base: str,
        timeout: float,
        max_tokens: int,
        temperature: float,
        transport: _Transport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._api_base = api_base
        self._timeout = timeout
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._transport = transport

    def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Call the provider and return the content string.

        Raises ``EvidenceLLMProviderError`` on timeout, provider error, or
        empty content.  Never swallows exceptions or returns fake text.
        """
        transport = self._transport or _DefaultOpenAITransport()
        try:
            response = transport.chat_completions(
                api_key=self._api_key,
                api_base=self._api_base,
                model=self._model,
                messages=messages,
                timeout=self._timeout,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
            )
        except EvidenceLLMProviderError:
            raise
        except Exception as exc:
            raise EvidenceLLMProviderError(
                f"provider call failed: {type(exc).__name__}"
            ) from exc

        content = _extract_content(response)
        if not content or not content.strip():
            raise EvidenceLLMProviderError("provider returned empty content")
        return content


def _extract_content(response: dict[str, Any]) -> str:
    """Extract the text content from an OpenAI-compatible response dict."""
    try:
        choices = response["choices"]
        if not choices:
            return ""
        message = choices[0].get("message", {})
        return message.get("content", "") or ""
    except (KeyError, IndexError, TypeError):
        return ""


# ---------------------------------------------------------------------------
# Default transport (lazy openai import)
# ---------------------------------------------------------------------------


class _DefaultOpenAITransport:
    """Default transport that lazily imports the ``openai`` SDK.

    If the SDK is not installed, calls raise ``EvidenceLLMProviderError``.
    The import happens at call time, not at module load time, so importing
    this module never triggers a network-related import.
    """

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
        try:
            from openai import OpenAI  # type: ignore[import-not-found]
        except ImportError as exc:
            raise EvidenceLLMProviderError(
                "openai SDK not available"
            ) from exc

        client = OpenAI(api_key=api_key, base_url=api_base, timeout=timeout)
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return completion.model_dump()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_evidence_llm_client(
    settings: Settings | None = None,
) -> OpenAICompatibleEvidenceLLMClient | None:
    """Build an evidence explanation LLM client, or ``None`` if disabled.

    Returns ``None`` when:
    - ``enable_real_llm_explanation`` is ``False`` (default), OR
    - ``llm_api_key`` is empty.

    Only when the flag is ``True`` AND a key is present does the factory
    create the adapter.  No real network request is made here — the adapter
    only contacts the provider when ``.complete()`` is called.
    """
    if settings is None:
        settings = get_settings()

    if not settings.enable_real_llm_explanation:
        return None

    if not settings.llm_api_key:
        return None

    return OpenAICompatibleEvidenceLLMClient(
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        api_base=settings.llm_api_base,
        timeout=settings.llm_explanation_timeout,
        max_tokens=settings.llm_explanation_max_tokens,
        temperature=settings.llm_explanation_temperature,
    )
