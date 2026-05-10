"""Backwards-compatible re-export of the shared agent config schema."""

from source2doc.agents.config import BaseAgentConfig as AgentConfig  # noqa: F401


class PlannerConfig(AgentConfig):
    pass


class WriterConfig(AgentConfig):
    pass


class CriticConfig(AgentConfig):
    pass
