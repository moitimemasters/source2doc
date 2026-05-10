from typing import Literal

from pydantic import BaseModel, Field


class Issue(BaseModel):
    """Issue found by critic."""

    severity: Literal["critical", "major", "minor"] = Field(description="Issue severity level")
    category: Literal["content", "structure", "accuracy"] = Field(description="Issue category")
    description: str = Field(description="Detailed description of the issue")


class CriticOutput(BaseModel):
    """Output from Critic Agent review."""

    score: int = Field(ge=1, le=10, description="Overall quality score (1-10)")
    has_hallucinations: bool = Field(description="Whether the page contains fabricated information")
    issues: list[Issue] = Field(default_factory=list, description="List of identified issues")
    suggestions: list[str] = Field(default_factory=list, description="Suggestions for improvement")
    summary: str = Field(description="Brief summary of the review")
