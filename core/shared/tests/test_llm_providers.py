"""Tests for the LLM provider resolver.

Coverage targets:

* ``provider=anthropic`` returns an ``AnthropicModel`` (real instance —
  the anthropic SDK is already installed in the venv).
* ``provider=openai-compatible`` returns the OpenAI chat model with the
  Yandex transport injected.
* Unknown provider raises ``ValueError`` (fail-fast at task start).
* Anthropic without ``api_key`` is rejected by ``LLMConfig`` itself.
"""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from source2doc.config import LLMConfig
from source2doc.llm_providers import build_pydantic_ai_model


def test_build_anthropic_model_returns_anthropic_instance() -> None:
    config = LLMConfig(
        provider="anthropic",
        model="claude-sonnet-4-6",
        api_key="sk-ant-test",
    )
    model = build_pydantic_ai_model(config)

    # Importing here so the assertion failure isn't masked by a missing
    # package — ``pydantic-ai-slim[anthropic]`` is a hard shared-lib dep.
    from pydantic_ai.models.anthropic import AnthropicModel

    assert isinstance(model, AnthropicModel)
    assert model.model_name == "claude-sonnet-4-6"


def test_build_openai_compatible_uses_yandex_transport() -> None:
    config = LLMConfig(
        provider="openai-compatible",
        model="gpt-test",
        api_key="key",
        base_url="https://example.test/v1",
    )
    model = build_pydantic_ai_model(config)

    from pydantic_ai.models.openai import OpenAIChatModel

    from source2doc.yandex_transport import YandexHTTPTransport

    assert isinstance(model, OpenAIChatModel)
    # The Yandex transport sits on the underlying httpx client.
    http_client = model.client._client  # type: ignore[attr-defined]
    transport = http_client._transport  # httpx internal
    assert isinstance(transport, YandexHTTPTransport)


def test_unknown_provider_raises() -> None:
    config = LLMConfig(provider="bogus", model="x", api_key="k")
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        build_pydantic_ai_model(config)


def test_anthropic_requires_api_key() -> None:
    # Empty api_key is rejected by the LLMConfig model_validator before
    # the resolver even runs.
    with pytest.raises(ValidationError, match="api_key is required"):
        LLMConfig(provider="anthropic", model="claude-sonnet-4-6", api_key="")


def test_openai_provider_skips_yandex_transport() -> None:
    config = LLMConfig(
        provider="openai",
        model="gpt-4o",
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
    )
    model = build_pydantic_ai_model(config)

    from pydantic_ai.models.openai import OpenAIChatModel

    from source2doc.yandex_transport import YandexHTTPTransport

    assert isinstance(model, OpenAIChatModel)
    http_client = model.client._client  # type: ignore[attr-defined]
    assert not isinstance(http_client._transport, YandexHTTPTransport)
