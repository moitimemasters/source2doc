"""History processors for Pydantic-AI agent runs.

Pydantic-AI by design re-sends the full message list (system prompt + every
prior tool call + tool result + assistant response) on every LLM round-trip.
That gives the model the full chain-of-tool-use context, but for an agent
that legitimately needs 20+ rounds (writer/critic on a complex page) the
history can balloon past the model's context window — qwen3-coder-480b has
262k tokens and we've seen 1.3M+ cumulative input tokens on a single run
that looped through 23 tool calls.

The processors here truncate or summarise older messages while keeping the
system prompt and the most recent few rounds intact, so the model always
sees fresh tool results plus a compact summary of what it already did.

Constraints:
- Pydantic-AI validates that every ``ToolCallPart`` has a matching
  ``ToolReturnPart``. Cannot drop one without the other. Easiest: replace
  the *content* of older ``ToolReturnPart``s with a placeholder while
  keeping the message structure intact.
"""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)


# How many of the most recent (request, response) round-trips to keep at
# full fidelity. Anything older has its tool-return contents replaced with
# a short placeholder. 3 = ~6 messages of full detail.
_KEEP_LAST_FULL_ROUNDS = 3

# Wording matters: weak models (Haiku, qwen3-coder) read "see latest
# results below" as an invitation to re-call the same tool to get the
# content back. The phrasing here makes it explicit that the content is
# spent and a re-call is wasted.
_PLACEHOLDER = (
    "[earlier tool result — content already incorporated into your "
    "reasoning above; do NOT re-call this tool, the result is final]"
)


def _is_response(message: ModelMessage) -> bool:
    return isinstance(message, ModelResponse)


def truncate_old_tool_results(
    messages: list[ModelMessage],
) -> list[ModelMessage]:
    """Replace contents of tool returns older than the last few rounds.

    Keeps:
    - The full message structure (so tool_call ↔ tool_return pairing
      stays valid).
    - The first request (system + initial user prompt).
    - The last ``_KEEP_LAST_FULL_ROUNDS`` request/response pairs verbatim.

    Replaces ``ToolReturnPart.content`` everywhere else with a fixed
    placeholder. Token savings come from the now-tiny tool returns; tool
    *call* parts and assistant text are kept since they are the model's
    own reasoning trace.
    """
    if not messages:
        return messages

    # Index every ModelResponse so we can find the last N response indexes
    # and treat everything from the matching preceding ModelRequest onward
    # as "recent". Pydantic-AI alternates Request/Response in the history,
    # so the count here is straightforward.
    response_indices = [i for i, m in enumerate(messages) if _is_response(m)]
    if len(response_indices) <= _KEEP_LAST_FULL_ROUNDS:
        return messages

    # First index that should remain at full fidelity: the request that
    # immediately precedes the (-_KEEP_LAST_FULL_ROUNDS)th response.
    pivot_response = response_indices[-_KEEP_LAST_FULL_ROUNDS]
    pivot_request = pivot_response - 1 if pivot_response > 0 else 0

    truncated: list[ModelMessage] = []
    for i, message in enumerate(messages):
        # Always keep the very first message (system + initial user prompt)
        # and everything from the pivot onward verbatim.
        if i == 0 or i >= pivot_request:
            truncated.append(message)
            continue

        if isinstance(message, ModelRequest):
            new_parts = list(message.parts)
            for j, part in enumerate(new_parts):
                if isinstance(part, ToolReturnPart):
                    new_parts[j] = ToolReturnPart(
                        tool_name=part.tool_name,
                        tool_call_id=part.tool_call_id,
                        content=_PLACEHOLDER,
                        timestamp=part.timestamp,
                    )
            truncated.append(ModelRequest(parts=new_parts))
        elif isinstance(message, ModelResponse):
            # Strip long assistant text but keep tool calls so the chain
            # of decisions is preserved (the model can still see it called
            # ``search_code('class Client')`` earlier).
            new_parts = list(message.parts)
            for j, part in enumerate(new_parts):
                if isinstance(part, TextPart) and len(part.content) > 200:
                    new_parts[j] = TextPart(content=part.content[:200] + " …[truncated]")
            truncated.append(
                ModelResponse(
                    parts=new_parts,
                    model_name=message.model_name,
                    timestamp=message.timestamp,
                )
            )
        else:
            truncated.append(message)

    return truncated


__all__ = ["truncate_old_tool_results", "UserPromptPart", "ToolCallPart"]
