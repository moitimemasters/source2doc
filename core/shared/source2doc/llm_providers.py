"""Provider-resolver for Pydantic-AI ``Model`` instances.

The single entry point is :func:`build_pydantic_ai_model`. Worker handlers
should never instantiate ``OpenAIChatModel`` / ``AnthropicModel`` directly;
that knowledge lives here so that adding a new provider only touches one
file and the LLMConfig schema.

Currently supported providers:

* ``openai`` / ``openai-compatible`` / ``ollama`` / ``yandex`` —
  all routed through :class:`pydantic_ai.providers.openai.OpenAIProvider`.
  Yandex piggy-backs on the OpenAI compat layer with a custom transport
  that unwraps ``{"response": {...}}`` envelopes.
* ``anthropic`` — direct Anthropic API via
  :class:`pydantic_ai.models.anthropic.AnthropicModel`.

All call paths inject a ``httpx.AsyncClient`` with hard per-request
timeouts so a hung upstream cannot wedge ``agent.run`` past the outer
``asyncio.timeout`` (HANDOFF.md bug #1).
"""

from __future__ import annotations

import typing as tp

import httpx
from pydantic_ai.models import Model

from source2doc.config import LLMConfig


# Default per-request HTTP timeouts. Picked conservatively so a single
# stuck connection is bounded long before the agent-level timeout fires.
_DEFAULT_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=90.0, write=10.0, pool=10.0)


def _build_http_client(use_yandex_transport: bool) -> httpx.AsyncClient:
    """httpx client with hard per-request timeouts.

    ``use_yandex_transport=True`` injects the Yandex envelope-unwrapping
    transport. Imported lazily because ``source2doc-shared`` shouldn't
    take a hard dependency on the docgen package layout.
    """

    if use_yandex_transport:
        # Local import keeps httpx the only mandatory shared-lib dep when
        # callers don't actually need the Yandex envelope unwrapping.
        from source2doc.yandex_transport import YandexHTTPTransport  # noqa: PLC0415

        transport: httpx.AsyncBaseTransport = YandexHTTPTransport(verify=False)
        return httpx.AsyncClient(transport=transport, timeout=_DEFAULT_HTTP_TIMEOUT)

    return httpx.AsyncClient(timeout=_DEFAULT_HTTP_TIMEOUT)


def _build_openai_compatible_model(
    config: LLMConfig,
    *,
    use_yandex_transport: bool,
) -> Model:
    # Lazy import: pydantic_ai is a sizeable dep — keep the import cost off
    # cold-load paths that never touch the LLM (e.g. CLI --help).
    from pydantic_ai.models.openai import OpenAIChatModel  # noqa: PLC0415
    from pydantic_ai.providers.openai import OpenAIProvider  # noqa: PLC0415

    http_client = _build_http_client(use_yandex_transport=use_yandex_transport)

    # Ollama doesn't require a real API key but the OpenAI SDK insists on
    # *something*. Pass a sentinel so the request body validates.
    api_key = config.api_key or "ollama-no-auth"

    provider = OpenAIProvider(
        base_url=config.base_url,
        api_key=api_key,
        http_client=http_client,
    )
    return OpenAIChatModel(config.model, provider=provider)


def _build_anthropic_model(config: LLMConfig) -> Model:
    from pydantic_ai.models.anthropic import (  # noqa: PLC0415
        AnthropicModel,
        AnthropicModelSettings,
    )
    from pydantic_ai.providers.anthropic import AnthropicProvider  # noqa: PLC0415

    # When ``base_url`` is set we're talking to a relay (e.g. Eliza's
    # ``/anthropic/v1/`` gateway) that may wrap the Anthropic body in a
    # ``{"response": {...}}`` envelope. Using the Yandex-aware client
    # handles that case transparently and is a no-op against the real
    # Anthropic API (which never sends such an envelope).
    use_yandex_transport = bool(config.base_url)
    http_client = _build_http_client(use_yandex_transport=use_yandex_transport)

    provider = AnthropicProvider(
        api_key=config.api_key,
        base_url=config.base_url or None,
        http_client=http_client,
    )
    # Prompt caching: agent ``instructions`` (system prompt loaded from
    # YAML) and tool schemas are stable across the dozens of round-trips
    # in a single agent.run. Marking them cacheable cuts the input-token
    # bill on those segments to ~10% on cache hits (Anthropic charges
    # 1.25× on the first write, 0.1× on subsequent reads within the 5-min
    # TTL). For a 30-round writer run the YAML alone drops from ~35K to
    # ~3.5K input tokens.
    settings = AnthropicModelSettings(
        anthropic_cache_instructions=True,
        anthropic_cache_tool_definitions=True,
    )
    return AnthropicModel(config.model, provider=provider, settings=settings)


# Provider name → builder. Kept as a module-level dict so tests can patch
# individual builders without monkey-patching the dispatch function itself.
_BUILDERS: dict[str, tp.Callable[[LLMConfig], Model]] = {
    "openai": lambda c: _build_openai_compatible_model(c, use_yandex_transport=False),
    "openai-compatible": lambda c: _build_openai_compatible_model(c, use_yandex_transport=True),
    "ollama": lambda c: _build_openai_compatible_model(c, use_yandex_transport=False),
    "yandex": lambda c: _build_openai_compatible_model(c, use_yandex_transport=True),
    "anthropic": _build_anthropic_model,
}


def build_pydantic_ai_model(llm_config: LLMConfig) -> Model:
    """Return a configured Pydantic-AI ``Model`` for the given provider.

    Raises ``ValueError`` for unknown providers so a typo in user config
    fails loudly at task-start instead of silently mid-run.
    """

    builder = _BUILDERS.get(llm_config.provider)
    if builder is None:
        raise ValueError(
            f"Unknown LLM provider {llm_config.provider!r}. Supported: {sorted(_BUILDERS)}",
        )
    return builder(llm_config)
