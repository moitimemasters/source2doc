import pydantic

from source2doc.agents.config import BaseAgentConfig


class CodetourGeneratorConfig(BaseAgentConfig):
    """Code Tour prompt config.

    Adds a codetour-specific prompt split: ``system_prompt`` (model role,
    workflow, output format), ``user_prompt_template`` (Jinja template for
    initial generation), ``followup_user_prompt_template`` (Jinja template for
    Phase B follow-up requests).
    """

    system_prompt: str = pydantic.Field(...)
    user_prompt_template: str = pydantic.Field(...)
    followup_user_prompt_template: str | None = pydantic.Field(default=None)
