"""Shared Server-Sent Events helpers.

Currently exposes ``with_idle_pings``, a wrapper that injects a periodic
``event: ping`` frame whenever the wrapped async iterator goes idle for
longer than ``SSE_PING_INTERVAL_SECONDS``. Required by TZ SSE-04 so
proxies/load-balancers (nginx, Yandex Cloud LB, browser timeouts) don't
drop the connection during long-running generations.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator


SSE_PING_INTERVAL_SECONDS = 5
"""Idle interval before emitting a keep-alive ``event: ping`` frame."""

PING_FRAME = "event: ping\ndata: {}\n\n"
"""Pre-formatted SSE keep-alive frame; never carries a payload."""


async def with_idle_pings(
    source: AsyncIterable[str],
    interval_seconds: float = SSE_PING_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """Yield from ``source``, injecting a ping whenever it idles.

    The ping is purely a keep-alive: it does **not** consume from any
    Redis stream or consumer group. The idle timer resets every time the
    underlying iterator yields a real frame.

    ``CancelledError`` is propagated so Starlette can shut the response
    down cleanly when the client disconnects.
    """

    iterator = source.__aiter__()
    pending: asyncio.Task[str] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())

            done, _ = await asyncio.wait({pending}, timeout=interval_seconds)

            if not done:
                # Source idle — emit keep-alive and keep waiting on the
                # same pending task on the next loop iteration.
                yield PING_FRAME
                continue

            try:
                item = pending.result()
            except StopAsyncIteration:
                pending = None
                return
            finally:
                if pending is not None and pending.done():
                    pending = None

            yield item
    except asyncio.CancelledError:
        if pending is not None and not pending.done():
            pending.cancel()
        raise
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            try:
                await pending
            except BaseException:
                pass
