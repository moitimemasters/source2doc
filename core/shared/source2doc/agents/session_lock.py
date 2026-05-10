"""Cluster-wide LLM session limiter backed by Redis.

The agent runner (``runner.run_agent``) wraps every ``agent.run`` in a
process-level ``asyncio.Semaphore`` sized from
``BaseAgentConfig.llm_concurrency``. That stops a single worker from
flooding the LLM provider with > N concurrent calls, but it does
nothing about the case where multiple worker processes (or multiple
parallel user-submitted tasks within one worker) all share the same
provider quota. Eliza in particular returns HTTP 429 ``inflight limit
exceeded`` past 5 concurrent calls — and that limit is per-API-key,
not per-process.

This module implements a small distributed semaphore: a Redis sorted
set keyed by ``llm:sessions:{api_key_hash}`` whose members are
short-lived "session tokens" (UUIDs) scored by their acquisition
timestamp. Acquire = atomically prune entries older than ``ttl_seconds``
(crash-resistance), count current holders, and add ours iff under the
limit. Release = ``ZREM`` the token. The whole acquire-or-fail step is a
single Lua script so two workers can't both squeeze in past the limit
between check and write.

Hashing key
-----------
We never put the raw API key in Redis — keys leak on dump/inspect.
``sha256(api_key)[:16]`` is enough entropy to avoid collisions across
realistic deployments while being cheap to recompute.
"""

from __future__ import annotations

import asyncio
import dataclasses as dc
import hashlib
import time
import typing as tp
import uuid

import redis.asyncio as aioredis

from source2doc.logging import get_logger


logger = get_logger(__name__)


_KEY_PREFIX = "llm:sessions:"
# Stale-token TTL. The Lua try-acquire prunes ZSET entries older than
# this on every call, so a worker that crashes mid-LLM-request frees its
# slot within ``_DEFAULT_TTL_SECONDS``. Set tight enough that recovery
# from crashes is fast, loose enough that a single long agent.run
# doesn't expire under itself — the heartbeat task below refreshes the
# token score every ``_HEARTBEAT_INTERVAL_SECONDS`` to keep healthy
# long-running calls alive past the TTL.
_DEFAULT_TTL_SECONDS = 120
_HEARTBEAT_INTERVAL_SECONDS = 30
_DEFAULT_POLL_INTERVAL_SECONDS = 0.25
_DEFAULT_ACQUIRE_TIMEOUT_SECONDS = 300


# Lua: prune expired, count active, add ours iff under limit.
# KEYS[1] = sorted-set key
# ARGV[1] = now_ms (integer timestamp)
# ARGV[2] = ttl_ms (entries older than now_ms - ttl_ms are pruned)
# ARGV[3] = max_sessions (limit)
# ARGV[4] = session_id (member to ZADD if we win)
# Returns 1 on success, 0 if the limit was full.
_TRY_ACQUIRE_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - ttl)
local active = redis.call('ZCARD', key)
if active < limit then
    redis.call('ZADD', key, now, member)
    redis.call('PEXPIRE', key, ttl + 1000)
    return 1
end
return 0
"""


def hash_api_key(api_key: str) -> str:
    """Stable short hash of the API key — used as the lock key suffix.

    16 hex chars (64 bits) is plenty for realistic deployments and keeps
    the Redis keyspace readable.
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


async def _heartbeat_loop(
    redis: aioredis.Redis,
    key: str,
    token: str,
    interval_seconds: float,
) -> None:
    """Refresh the token's score periodically while the lock is held.

    Refreshing means ZADDing the token with the current timestamp —
    that's the value the Lua try-acquire script compares against the
    TTL window when pruning. So as long as the heartbeat is running,
    the token can't be pruned by a competing acquire. The moment we
    stop refreshing (release / crash / cancellation), the entry ages
    out within ``_DEFAULT_TTL_SECONDS``.
    """
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            now_ms = int(time.time() * 1000)
            try:
                await redis.zadd(key, {token: now_ms})
            except Exception as exc:  # noqa: BLE001 — defensive
                logger.warning(
                    "session_lock_heartbeat_failed",
                    key=key,
                    token=token,
                    error=str(exc),
                )
    except asyncio.CancelledError:
        return


@dc.dataclass
class SessionLock:
    """Reservation handle returned by :func:`acquire`.

    Holds the Redis client + key + token so the caller can ``release()``
    on completion. Also implements the async context manager protocol
    so ``async with await acquire(...)`` works. A background heartbeat
    task refreshes the token's score every
    ``_HEARTBEAT_INTERVAL_SECONDS`` while the lock is held; if the
    holder crashes / cancels / loses the event loop, the heartbeat
    stops, the token ages past ``_DEFAULT_TTL_SECONDS``, and the next
    acquirer prunes it.
    """

    redis: aioredis.Redis
    key: str
    token: str
    _heartbeat: asyncio.Task | None = None
    released: bool = False

    async def release(self) -> None:
        if self.released:
            return
        self.released = True
        if self._heartbeat is not None and not self._heartbeat.done():
            self._heartbeat.cancel()
            try:
                await self._heartbeat
            except (asyncio.CancelledError, BaseException):  # noqa: BLE001
                # Heartbeat cancellation is the expected path. Swallow
                # everything because release() is always safe to call.
                pass
        try:
            await self.redis.zrem(self.key, self.token)
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.warning(
                "session_lock_release_failed",
                key=self.key,
                token=self.token,
                error=str(exc),
            )

    async def __aenter__(self) -> "SessionLock":
        return self

    async def __aexit__(self, *exc_info: tp.Any) -> None:
        await self.release()


async def acquire(
    redis: aioredis.Redis,
    *,
    api_key_hash: str,
    max_sessions: int,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
    acquire_timeout_seconds: float = _DEFAULT_ACQUIRE_TIMEOUT_SECONDS,
    label: str | None = None,
) -> SessionLock:
    """Block until a slot opens up under the global ``max_sessions`` cap.

    The wait is implemented as Lua-atomic try-acquire + jittered sleep
    on miss. We DON'T use Redis pub/sub or BLPOP because the lock must
    survive crash-induced stale entries (TTL prune in the Lua script
    handles that). For typical LLM call durations (1-30 seconds) the
    polling overhead is negligible compared to the call itself.

    Raises ``TimeoutError`` after ``acquire_timeout_seconds`` of unsuccessful
    attempts. Callers should pick a value larger than the longest
    expected agent.run wall-clock so a temporarily-empty quota doesn't
    burn the run prematurely.
    """
    key = f"{_KEY_PREFIX}{api_key_hash}"
    # Token format: ``{label}|{nonce}`` so the admin metrics endpoint
    # can show which worker / agent role currently holds each slot
    # without an extra Redis key. Label is sanitized to drop the
    # delimiter; ``|`` in worker_id would corrupt parsing on the read
    # side. Empty label collapses to just the nonce.
    nonce = uuid.uuid4().hex[:16]
    safe_label = (label or "").replace("|", "_")
    token = f"{safe_label}|{nonce}" if safe_label else nonce
    ttl_ms = ttl_seconds * 1000
    deadline = time.monotonic() + acquire_timeout_seconds
    attempts = 0

    while True:
        attempts += 1
        now_ms = int(time.time() * 1000)
        result = await redis.eval(
            _TRY_ACQUIRE_LUA,
            1,
            key,
            now_ms,
            ttl_ms,
            max_sessions,
            token,
        )
        if int(result) == 1:
            if attempts > 1:
                logger.info(
                    "session_lock_acquired_after_wait",
                    key=key,
                    attempts=attempts,
                )
            heartbeat = asyncio.create_task(
                _heartbeat_loop(redis, key, token, _HEARTBEAT_INTERVAL_SECONDS),
                name=f"session-lock-heartbeat-{token[:8]}",
            )
            return SessionLock(
                redis=redis, key=key, token=token, _heartbeat=heartbeat
            )
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"session_lock acquire timed out after {acquire_timeout_seconds}s "
                f"({attempts} attempts) on {key}"
            )
        # Jitter to avoid thundering-herd when many workers wake at once.
        await asyncio.sleep(poll_interval_seconds * (0.7 + 0.6 * (token[0:2] == "ff")))
