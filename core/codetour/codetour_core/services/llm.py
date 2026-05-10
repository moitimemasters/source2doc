"""Pydantic-AI model factory for the code-tour agent.

Thin wrapper around :func:`source2doc.llm_providers.build_pydantic_ai_model`.
Provider routing logic lives in the shared module.
"""

from pydantic_ai.models import Model

from source2doc.config import LLMConfig
from source2doc.llm_providers import build_pydantic_ai_model


def create_llm_model(config: LLMConfig) -> Model:
    """Return a configured Pydantic-AI ``Model`` for the given LLM config."""

    return build_pydantic_ai_model(config)
