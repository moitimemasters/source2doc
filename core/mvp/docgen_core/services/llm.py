"""Pydantic-AI model factory for the docgen agents.

Thin wrapper around :func:`source2doc.llm_providers.build_pydantic_ai_model`
kept here for import-stability — the existing handlers import
``docgen_core.services.llm.create_llm_model``. Anthropic / OpenAI / Yandex
provider routing all live in the shared module so that adding a provider
is a one-file change.
"""

from pydantic_ai.models import Model

from source2doc.config import LLMConfig
from source2doc.llm_providers import build_pydantic_ai_model


def create_llm_model(config: LLMConfig) -> Model:
    """Return a configured Pydantic-AI ``Model`` for the given LLM config."""

    return build_pydantic_ai_model(config)
