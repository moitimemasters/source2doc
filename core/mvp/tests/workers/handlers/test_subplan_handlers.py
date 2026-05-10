"""Pure-logic tests for the hierarchical-planner fan-out / fan-in handlers.

The subplan phase sits between the top-planner (``plan.outline_created``)
and the writer (``plan.created``):

  * fan-out emits one ``subplan.requested`` per section,
  * the per-section handler runs the subplanner agent,
  * the aggregator drains the tracker (held in Redis as atomic primitives),
    creates the bundle, and emits the original ``plan.created`` event with
    merged ``page_specs``.

Tracker state lives in Redis (SET / HASH / SET-NX) so concurrent
``subplan.completed`` events don't race on an in-memory dict that the worker
rebuilds per event. Tests use ``fakeredis`` to cover that path.
"""

from __future__ import annotations

import collections.abc as cabc
from types import SimpleNamespace
import typing as tp
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import fakeredis.aioredis
import pytest

from docgen_core.workers import context as ctx_mod
from docgen_core.workers.handlers import subplan as subplan_handlers


class _CapturingBus:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    async def emit(self, event_type: str, data: dict) -> None:
        self.emitted.append((event_type, data))

    def subscribe(self, event_type: str, handler: cabc.Callable) -> None:  # noqa: ARG002
        pass

    def get_events(self) -> list[dict]:
        return [{"type": t, **d} for t, d in self.emitted]


def _outline() -> dict:
    return {
        "project_summary": "Test project",
        "sections": [
            {
                "id": "overview",
                "title": "Overview",
                "description": "What this is.",
                "scope_paths": ["README.md"],
                "search_seeds": ["overview"],
            },
            {
                "id": "client",
                "title": "Client API",
                "description": "Sync and async client.",
                "scope_paths": ["src/_client.py"],
                "search_seeds": ["class Client"],
            },
        ],
    }


def _env_with_storage(redis: tp.Any) -> tp.Any:
    """Build a minimal env stub that satisfies the subplan handlers."""
    storage = MagicMock()
    storage.create_bundle = AsyncMock(return_value=42)
    storage.write_index = AsyncMock()
    storage.get_repository = AsyncMock(return_value=SimpleNamespace(commit_sha="deadbeef"))
    return SimpleNamespace(
        storage=storage,
        event_bus=_CapturingBus(),
        config=SimpleNamespace(generation=SimpleNamespace(max_nodes=20)),
        redis=redis,
    )


def _fakeredis() -> tp.Any:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


# ---------------------------------------------------------------------------
# 1. Fan-out emits one subplan.requested per section + seeds Redis tracker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fanout_emits_one_event_per_section() -> None:
    redis = _fakeredis()
    env = _env_with_storage(redis)
    ctx = ctx_mod.GenerationContext()
    gen_id = str(uuid4())

    await subplan_handlers.handle_outline_created(
        env,
        ctx,
        {
            "generation_id": gen_id,
            "outline": _outline(),
            "section_count": 2,
            "repo_id": None,
            "path": "/tmp/repo",
        },
    )

    requested = [t for t, _ in env.event_bus.emitted if t == "subplan.requested"]
    assert len(requested) == 2

    # Tracker now lives in Redis, not on ctx.
    pending = await redis.smembers(f"subplan:{gen_id}:pending")
    assert pending == {"overview", "client"}
    meta = await redis.hgetall(f"subplan:{gen_id}:meta")
    assert meta["project_summary"] == "Test project"


# ---------------------------------------------------------------------------
# 2. Aggregator drains tracker via Redis and emits plan.created exactly once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregator_emits_plan_created_once_when_drained() -> None:
    redis = _fakeredis()
    env = _env_with_storage(redis)
    ctx = ctx_mod.GenerationContext()
    gen_id = str(uuid4())

    # Fan-out seeds Redis state.
    await subplan_handlers.handle_outline_created(
        env,
        ctx,
        {
            "generation_id": gen_id,
            "outline": _outline(),
            "section_count": 2,
            "repo_id": None,
            "path": "/tmp/repo",
            "name": "test",
            "description": None,
        },
    )
    # Reset emit log so we can count plan.created cleanly.
    env.event_bus.emitted.clear()

    # First section drains — no plan.created yet.
    await subplan_handlers.handle_subplan_completed(
        env,
        ctx,
        {
            "generation_id": gen_id,
            "section_id": "overview",
            "page_specs": [
                {
                    "page_id": "overview",
                    "title": "Overview",
                    "description": "Project overview.",
                    "search_queries": ["overview"],
                }
            ],
            "pages_count": 1,
        },
    )
    assert not any(t == "plan.created" for t, _ in env.event_bus.emitted)
    pending_after_first = await redis.smembers(f"subplan:{gen_id}:pending")
    assert pending_after_first == {"client"}

    # Second section drains — aggregator fires.
    await subplan_handlers.handle_subplan_completed(
        env,
        ctx,
        {
            "generation_id": gen_id,
            "section_id": "client",
            "page_specs": [
                {
                    "page_id": "client-sync",
                    "title": "Sync Client",
                    "description": "Sync client.",
                    "search_queries": ["class Client"],
                },
                {
                    "page_id": "client-async",
                    "title": "Async Client",
                    "description": "Async client.",
                    "search_queries": ["class AsyncClient"],
                },
            ],
            "pages_count": 2,
        },
    )

    plan_events = [d for t, d in env.event_bus.emitted if t == "plan.created"]
    assert len(plan_events) == 1
    payload = plan_events[0]
    assert payload["plan"]["page_specs"][0]["page_id"] == "overview"
    assert {ps["page_id"] for ps in payload["plan"]["page_specs"]} == {
        "overview",
        "client-sync",
        "client-async",
    }
    nav = payload["plan"]["navigation"]
    assert nav["overview"] == "Overview"
    assert isinstance(nav["client"], dict)
    assert set(nav["client"]["children"].keys()) == {"client-sync", "client-async"}

    env.storage.create_bundle.assert_awaited_once()
    assert ctx.bundle_id == 42
    assert ctx.expected_pages == 3

    # Aggregator sentinel set so a duplicate redelivery doesn't double-emit.
    assert await redis.get(f"subplan:{gen_id}:aggregated") == "1"


# ---------------------------------------------------------------------------
# 3. Duplicate subplan.completed (e.g. redelivery) does NOT re-emit plan.created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_subplan_completed_is_idempotent() -> None:
    redis = _fakeredis()
    env = _env_with_storage(redis)
    ctx = ctx_mod.GenerationContext()
    gen_id = str(uuid4())

    await subplan_handlers.handle_outline_created(
        env,
        ctx,
        {
            "generation_id": gen_id,
            "outline": {
                "project_summary": "x",
                "sections": [
                    {
                        "id": "only",
                        "title": "Only",
                        "description": "x",
                        "scope_paths": [],
                        "search_seeds": [],
                    }
                ],
            },
            "section_count": 1,
            "repo_id": None,
            "path": "/tmp/repo",
        },
    )
    env.event_bus.emitted.clear()

    payload = {
        "generation_id": gen_id,
        "section_id": "only",
        "page_specs": [
            {
                "page_id": "only",
                "title": "Only",
                "description": "x",
                "search_queries": [],
            }
        ],
        "pages_count": 1,
    }
    await subplan_handlers.handle_subplan_completed(env, ctx, payload)
    await subplan_handlers.handle_subplan_completed(env, ctx, payload)

    plan_events = [t for t, _ in env.event_bus.emitted if t == "plan.created"]
    assert len(plan_events) == 1


# ---------------------------------------------------------------------------
# 4. Outline with zero sections: no Redis seeding, no events emitted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_outline_emits_nothing() -> None:
    redis = _fakeredis()
    env = _env_with_storage(redis)
    ctx = ctx_mod.GenerationContext()
    gen_id = str(uuid4())

    await subplan_handlers.handle_outline_created(
        env,
        ctx,
        {
            "generation_id": gen_id,
            "outline": {"project_summary": "x", "sections": []},
            "section_count": 0,
            "repo_id": None,
            "path": "/tmp/repo",
        },
    )

    assert not any(t == "subplan.requested" for t, _ in env.event_bus.emitted)
    assert await redis.exists(f"subplan:{gen_id}:pending") == 0
