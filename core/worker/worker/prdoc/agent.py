"""Pydantic-AI agent for PR microdoc generation.

The agent receives a compact prompt with the changed-files diff snapshot
(plus optional RAG snippets) and returns a structured ``PRDocSummary`` with
a Markdown summary, highlights, and concerns. Prompt style mirrors
``core/mvp/docgen_core/workers/handlers/write.py`` — RU/EN mix is fine for
the writer's voice but instructions stay in English so model behaviour is
consistent across providers.
"""

from __future__ import annotations

import typing as tp

import pydantic
import pydantic_ai

from source2doc.config import LLMConfig

# Reuse the docgen core's LLM model factory — it already wires the Yandex
# transport + per-request timeouts that the rest of the worker depends on.
from docgen_core.services.llm import create_llm_model


_INSTRUCTIONS = """\
You are a senior reviewer writing a concise Markdown summary of a pull
request, suitable for posting back as a PR comment.

You will receive:
- An optional PR title and description.
- A list of changed files. For each file you get the unified diff hunks and
  may also get the full updated file content.
- Optional RAG context: short snippets pulled from the repository for
  symbols touched by the diff. Use them to ground the explanation but do
  not invent code that is not in the diff or the snippets.

Write your output as a structured object:

* ``summary_markdown`` — 3-5 sentences in Markdown explaining what the PR
  changes and **why** it matters. Stay technical, no marketing.
* ``highlights`` — 2-3 bullet strings about notable improvements or new
  capabilities introduced by the change.
* ``concerns`` — 1-3 bullet strings about risks, edge cases, missing
  tests, or follow-ups worth verifying. If you genuinely have nothing to
  flag, return an empty list.
* ``files_summarised`` — exact integer count of files you considered.

Hard rules:
- Total length under 400 words across all fields.
- Quote at most short fragments of code; avoid pasting whole hunks back.
- Do not invent file paths, symbols, or behaviours that are not in the
  inputs. If a file only has a diff (no full content), reason from the
  diff alone and say so when uncertain.
- If the diff is trivial (formatting / typos / version bumps), say so
  briefly instead of padding the response.
"""


class PRDocSummary(pydantic.BaseModel):
    """Structured output of the prdoc agent."""

    summary_markdown: str = pydantic.Field(
        description="Markdown summary of the PR (3-5 sentences).",
    )
    highlights: list[str] = pydantic.Field(
        default_factory=list,
        description="2-3 notable improvements introduced by the PR.",
    )
    concerns: list[str] = pydantic.Field(
        default_factory=list,
        description="1-3 risks, missing tests, or follow-ups.",
    )
    files_summarised: int = pydantic.Field(
        default=0,
        ge=0,
        description="Number of changed files the agent considered.",
    )


def create_prdoc_agent(
    llm_config: LLMConfig,
) -> pydantic_ai.Agent[None, PRDocSummary]:
    """Build a Pydantic-AI agent that produces ``PRDocSummary``.

    No tools are registered — the diff snapshot is fed inline. RAG context,
    when available, is also stitched into the prompt by the caller.
    """

    model = create_llm_model(llm_config)
    agent: pydantic_ai.Agent[None, PRDocSummary] = pydantic_ai.Agent(
        model=model,
        output_type=PRDocSummary,
        instructions=_INSTRUCTIONS,
        retries=2,
    )
    return agent


def build_prompt(
    *,
    title: str | None,
    description: str | None,
    base_sha: str | None,
    head_sha: str | None,
    changed_files: list[dict[str, tp.Any]],
    rag_snippets_by_file: dict[str, list[str]] | None = None,
    max_rag_chunks: int = 30,
    max_full_content_chars: int = 6000,
) -> str:
    """Render a compact text prompt for the prdoc agent.

    ``changed_files`` items are dicts with keys: ``path``, ``language``,
    ``diff``, ``full_content_after`` (optional). RAG snippets are keyed
    by file path.
    """

    parts: list[str] = []
    if title:
        parts.append(f"# PR title\n{title.strip()}")
    if description:
        parts.append(f"# PR description\n{description.strip()}")
    if base_sha or head_sha:
        parts.append(
            "# Commits\n"
            f"- base: {base_sha or 'unknown'}\n"
            f"- head: {head_sha or 'unknown'}"
        )

    files_block: list[str] = []
    for entry in changed_files:
        path = entry.get("path") or "<unknown-path>"
        language = entry.get("language") or ""
        diff = (entry.get("diff") or "").strip()
        full = entry.get("full_content_after")

        section = [f"## File: {path}"]
        if language:
            section.append(f"language: {language}")
        if diff:
            section.append("### Diff")
            section.append("```diff")
            section.append(diff)
            section.append("```")
        else:
            section.append("(no diff supplied)")

        if full:
            truncated = full[:max_full_content_chars]
            note = ""
            if len(full) > max_full_content_chars:
                note = (
                    f"\n... (truncated; original size {len(full)} chars,"
                    f" showing first {max_full_content_chars})"
                )
            section.append("### Updated content")
            section.append(f"```{language}")
            section.append(truncated + note)
            section.append("```")
        files_block.append("\n".join(section))

    if files_block:
        parts.append("# Changed files\n" + "\n\n".join(files_block))

    if rag_snippets_by_file:
        rag_block: list[str] = ["# RAG context (top results from the repo index)"]
        remaining = max_rag_chunks
        for path, snippets in rag_snippets_by_file.items():
            if remaining <= 0:
                break
            usable = snippets[:remaining]
            if not usable:
                continue
            rag_block.append(f"## {path}")
            for snippet in usable:
                rag_block.append("```")
                rag_block.append(snippet.strip())
                rag_block.append("```")
            remaining -= len(usable)
        if len(rag_block) > 1:
            parts.append("\n".join(rag_block))

    parts.append(
        "# Task\nWrite the PR doc summary now. Keep total output under 400 words."
    )
    return "\n\n".join(parts)
