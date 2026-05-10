"""Unit tests for the shared SSE keep-alive helper.

PMI-mapping: SSE-04 (periodic keep-alive ping every 5s on idle SSE streams).

We use a tiny interval to keep the test fast — the production constant
``SSE_PING_INTERVAL_SECONDS == 5`` is asserted separately so the value
itself is also covered.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.routes._shared.sse import (
    PING_FRAME,
    SSE_PING_INTERVAL_SECONDS,
    with_idle_pings,
)


def test_ping_constants_match_tz_sse04() -> None:
    """TZ SSE-04 mandates 5s interval and the ``event: ping`` frame format."""
    assert SSE_PING_INTERVAL_SECONDS == 5
    assert PING_FRAME == "event: ping\ndata: {}\n\n"


async def test_with_idle_pings_emits_ping_when_source_is_idle() -> None:
    """An idle source must produce a ping within ~one interval."""

    started = asyncio.Event()

    async def idle_source() -> AsyncIterator[str]:
        started.set()
        # Block forever so the wrapper times out and emits a ping.
        await asyncio.Event().wait()
        yield "unreachable"

    iterator = with_idle_pings(idle_source(), interval_seconds=0.1).__aiter__()
    try:
        # Allow generous slack for slow CI: 6x interval ≈ 0.6s, which still
        # proves "ping arrives within ~6s on an idle stream" at production
        # scale (1.0 -> 6.0).
        frame = await asyncio.wait_for(iterator.__anext__(), timeout=0.6)
    finally:
        await iterator.aclose()

    assert started.is_set()
    assert frame == PING_FRAME


async def test_with_idle_pings_passes_real_events_through() -> None:
    """Real frames must be yielded verbatim and reset the idle timer."""

    async def source() -> AsyncIterator[str]:
        yield 'data: {"type": "step.started"}\n\n'
        yield 'data: {"type": "step.completed"}\n\n'

    collected: list[str] = []
    async for frame in with_idle_pings(source(), interval_seconds=10):
        collected.append(frame)

    assert collected == [
        'data: {"type": "step.started"}\n\n',
        'data: {"type": "step.completed"}\n\n',
    ]


async def test_with_idle_pings_interleaves_ping_then_event() -> None:
    """When the source idles then produces, we must see ping → event."""

    release = asyncio.Event()

    async def source() -> AsyncIterator[str]:
        await release.wait()
        yield 'data: {"type": "late"}\n\n'

    async def trigger() -> None:
        # Wait long enough for at least one ping to fire.
        await asyncio.sleep(0.25)
        release.set()

    asyncio.create_task(trigger())

    collected: list[str] = []
    async for frame in with_idle_pings(source(), interval_seconds=0.1):
        collected.append(frame)

    assert PING_FRAME in collected
    # The real event must arrive after at least one ping.
    assert collected[-1] == 'data: {"type": "late"}\n\n'
    assert collected.index(PING_FRAME) < collected.index('data: {"type": "late"}\n\n')


async def test_with_idle_pings_propagates_cancellation() -> None:
    """Client disconnect (CancelledError) must surface, not be swallowed."""

    async def idle_source() -> AsyncIterator[str]:
        await asyncio.Event().wait()
        yield "never"

    async def consume() -> None:
        async for _ in with_idle_pings(idle_source(), interval_seconds=10):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return
    raise AssertionError("expected CancelledError to propagate")
