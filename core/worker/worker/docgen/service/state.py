"""Per-generation worker state, split across multiple Redis structures
to avoid the read-modify-write race that the JSON-blob layout used to
hit under ``worker_concurrency > 1``.

Layout
------

Each generation has a small handful of Redis keys, all under the
``state:docgen:{gen_id}*`` prefix:

  * ``state:docgen:{gen_id}`` — main HASH. Holds scalars only:
    ``worker_id``, ``current_phase``, ``bundle_id``, ``expected_pages``,
    ``dominant_language``, ``cancelled``. Last-write-wins on these is
    fine — they're either set-once or not concurrent.

  * ``state:docgen:{gen_id}:completed`` — SET of page_ids. Updated via
    SADD (atomic, idempotent). Replaces the JSON-list field that used
    to live in the main hash and got clobbered when two handlers'
    read-modify-write cycles overlapped.

  * ``state:docgen:{gen_id}:failed`` — HASH of page_id → reason.
    Updated via HSET (atomic per-field).

  * ``state:docgen:{gen_id}:page_states`` — HASH of page_id → JSON
    ``{status, attempts, spec}``. Per-page write, no cross-page
    contention.

  * ``state:docgen:{gen_id}:source_files`` — HASH of page_id → JSON
    list of file paths the writer touched.

The previous incarnation of this module serialized everything as JSON
inside one HASH, which forced a full read-modify-write cycle on every
update. With ``worker_concurrency=12`` two handlers could both read
``completed_pages=[A]``, each append their own page, and the slower
writer would clobber the faster one — which is how a 48-page run
ended with ``state.completed_pages=[only 3 entries]`` even though
events showed all 48 finishing.
"""

from __future__ import annotations

import dataclasses as dc
import json
import typing as tp

import redis.asyncio as aioredis

from source2doc.logging import get_logger


logger = get_logger(__name__)


@dc.dataclass
class PageState:
    page_id: str
    status: str
    attempts: int
    spec: dict[str, tp.Any]


@dc.dataclass
class GenerationState:
    generation_id: str
    worker_id: str
    current_phase: str
    bundle_id: int | None
    expected_pages: int
    completed_pages: list[str]
    failed_pages: dict[str, str]
    page_states: dict[str, PageState]
    dominant_language: str = "text"
    # Per-task natural-language locale of the rendered docs ("en"/"ru").
    # Set once on create_state from the user_config; every event-handler
    # rehydrates it via get_state and pipes it into the agent prompts.
    output_language: str = "en"
    cancelled: bool = False
    page_source_files: dict[str, list[str]] = dc.field(default_factory=dict)


def _state_key(generation_id: str) -> str:
    return f"state:docgen:{generation_id}"


def _completed_key(generation_id: str) -> str:
    return f"state:docgen:{generation_id}:completed"


def _failed_key(generation_id: str) -> str:
    return f"state:docgen:{generation_id}:failed"


def _page_states_key(generation_id: str) -> str:
    return f"state:docgen:{generation_id}:page_states"


def _source_files_key(generation_id: str) -> str:
    return f"state:docgen:{generation_id}:source_files"


def _config_key(generation_id: str) -> str:
    return f"config:docgen:{generation_id}"


_DEFAULT_TTL_SECONDS = 86400


async def get_state(
    redis: aioredis.Redis,
    generation_id: str,
) -> GenerationState | None:
    main_key = _state_key(generation_id)
    data = await redis.hgetall(main_key)
    if not data:
        return None

    cancelled = data.get("cancelled", "false").lower() == "true"

    # Concurrency-safe per-page structures live in dedicated keys.
    pipe = redis.pipeline()
    pipe.smembers(_completed_key(generation_id))
    pipe.hgetall(_failed_key(generation_id))
    pipe.hgetall(_page_states_key(generation_id))
    pipe.hgetall(_source_files_key(generation_id))
    completed_raw, failed_raw, page_states_raw, source_files_raw = (
        await pipe.execute()
    )

    completed_pages = sorted(completed_raw or [])
    failed_pages = dict(failed_raw or {})

    page_states: dict[str, PageState] = {}
    for page_id, blob in (page_states_raw or {}).items():
        try:
            ps_data = json.loads(blob)
        except (ValueError, TypeError):
            continue
        page_states[page_id] = PageState(
            page_id=page_id,
            status=ps_data.get("status", "pending"),
            attempts=int(ps_data.get("attempts", 0)),
            spec=ps_data.get("spec", {}),
        )

    page_source_files: dict[str, list[str]] = {}
    for page_id, blob in (source_files_raw or {}).items():
        try:
            page_source_files[page_id] = list(json.loads(blob))
        except (ValueError, TypeError):
            continue

    return GenerationState(
        generation_id=generation_id,
        worker_id=data.get("worker_id", ""),
        current_phase=data.get("current_phase", ""),
        bundle_id=int(data["bundle_id"]) if data.get("bundle_id") else None,
        expected_pages=int(data.get("expected_pages", 0)),
        completed_pages=completed_pages,
        failed_pages=failed_pages,
        page_states=page_states,
        dominant_language=data.get("dominant_language", "text"),
        output_language=data.get("output_language", "en"),
        page_source_files=page_source_files,
        cancelled=cancelled,
    )


async def save_state(
    redis: aioredis.Redis,
    state: GenerationState,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> None:
    """Full-replace save, used for ``create_state`` only.

    For per-event delta updates use the dedicated atomic helpers
    (``mark_page_completed``, ``mark_page_failed``, ``upsert_page_state``,
    ``set_page_source_files``). This function is the one place where a
    bulk overwrite is intentional — typically from ``create_state`` or
    from tests.
    """
    main_key = _state_key(state.generation_id)
    completed_key = _completed_key(state.generation_id)
    failed_key = _failed_key(state.generation_id)
    page_states_key = _page_states_key(state.generation_id)
    source_files_key = _source_files_key(state.generation_id)

    pipe = redis.pipeline()
    pipe.hset(
        main_key,
        mapping={
            "worker_id": state.worker_id,
            "current_phase": state.current_phase,
            "bundle_id": str(state.bundle_id) if state.bundle_id else "",
            "expected_pages": str(state.expected_pages),
            "dominant_language": state.dominant_language,
            "output_language": state.output_language,
            "cancelled": "true" if state.cancelled else "false",
        },
    )
    pipe.expire(main_key, ttl_seconds)

    if state.completed_pages:
        pipe.sadd(completed_key, *state.completed_pages)
        pipe.expire(completed_key, ttl_seconds)
    if state.failed_pages:
        pipe.hset(failed_key, mapping=state.failed_pages)
        pipe.expire(failed_key, ttl_seconds)
    if state.page_states:
        page_states_serialized = {
            page_id: json.dumps(
                {"status": ps.status, "attempts": ps.attempts, "spec": ps.spec}
            )
            for page_id, ps in state.page_states.items()
        }
        pipe.hset(page_states_key, mapping=page_states_serialized)
        pipe.expire(page_states_key, ttl_seconds)
    if state.page_source_files:
        source_files_serialized = {
            page_id: json.dumps(files)
            for page_id, files in state.page_source_files.items()
        }
        pipe.hset(source_files_key, mapping=source_files_serialized)
        pipe.expire(source_files_key, ttl_seconds)

    await pipe.execute()


async def save_scalars(
    redis: aioredis.Redis,
    generation_id: str,
    *,
    worker_id: str | None = None,
    current_phase: str | None = None,
    bundle_id: int | None = None,
    expected_pages: int | None = None,
    dominant_language: str | None = None,
    cancelled: bool | None = None,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> None:
    """Atomic write of the main-hash scalars only.

    Used by the worker dispatcher's per-event flush path to update the
    generation-wide single-value fields. Per-page collections are
    written via the dedicated helpers below — never touched here.
    """
    mapping: dict[str, str] = {}
    if worker_id is not None:
        mapping["worker_id"] = worker_id
    if current_phase is not None:
        mapping["current_phase"] = current_phase
    if bundle_id is not None:
        mapping["bundle_id"] = str(bundle_id)
    if expected_pages is not None:
        mapping["expected_pages"] = str(expected_pages)
    if dominant_language is not None:
        mapping["dominant_language"] = dominant_language
    if cancelled is not None:
        mapping["cancelled"] = "true" if cancelled else "false"
    if not mapping:
        return
    main_key = _state_key(generation_id)
    pipe = redis.pipeline()
    pipe.hset(main_key, mapping=mapping)
    pipe.expire(main_key, ttl_seconds)
    await pipe.execute()


async def add_completed_page(
    redis: aioredis.Redis,
    generation_id: str,
    page_id: str,
    *,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> int:
    """Atomic SADD into the completed-pages set.

    Returns the new SCARD (post-add total) so the caller can decide
    whether ``is_complete()`` should fire ``generation.completed`` from
    this handler's branch — concurrent finalize handlers won't both
    pass that check because exactly one of them gets the count that
    crosses the ``expected_pages`` threshold.
    """
    completed_key = _completed_key(generation_id)
    pipe = redis.pipeline()
    pipe.sadd(completed_key, page_id)
    pipe.scard(completed_key)
    pipe.expire(completed_key, ttl_seconds)
    _added, total, _expire = await pipe.execute()
    return int(total)


async def add_failed_page(
    redis: aioredis.Redis,
    generation_id: str,
    page_id: str,
    reason: str,
    *,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> None:
    """Atomic HSET on the failed-pages hash."""
    failed_key = _failed_key(generation_id)
    pipe = redis.pipeline()
    pipe.hset(failed_key, page_id, reason)
    pipe.expire(failed_key, ttl_seconds)
    await pipe.execute()


async def upsert_page_state(
    redis: aioredis.Redis,
    generation_id: str,
    page_id: str,
    *,
    status: str | None = None,
    attempts: int | None = None,
    spec: dict[str, tp.Any] | None = None,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> None:
    """Atomic HSET on the per-page state hash.

    This is the one place we still do a per-page read-modify-write
    (HGET → merge → HSET) — but the contention is per page_id, and a
    single page is only ever processed by one handler at a time, so
    the race is structurally impossible.
    """
    page_states_key = _page_states_key(generation_id)
    raw = await redis.hget(page_states_key, page_id)
    current: dict[str, tp.Any] = {}
    if raw:
        try:
            current = json.loads(raw)
        except (ValueError, TypeError):
            current = {}
    if status is not None:
        current["status"] = status
    if attempts is not None:
        current["attempts"] = attempts
    if spec is not None:
        current["spec"] = spec
    pipe = redis.pipeline()
    pipe.hset(page_states_key, page_id, json.dumps(current))
    pipe.expire(page_states_key, ttl_seconds)
    await pipe.execute()


async def set_page_source_files(
    redis: aioredis.Redis,
    generation_id: str,
    page_id: str,
    files: list[str],
    *,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> None:
    """Atomic HSET on the source-files hash."""
    source_files_key = _source_files_key(generation_id)
    pipe = redis.pipeline()
    pipe.hset(source_files_key, page_id, json.dumps(files))
    pipe.expire(source_files_key, ttl_seconds)
    await pipe.execute()


async def create_state(
    redis: aioredis.Redis,
    generation_id: str,
    worker_id: str,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    *,
    output_language: str = "en",
) -> GenerationState:
    """Create the per-generation state hash, idempotent on re-delivery.

    ``processor.handle_generation_request`` calls this on every
    ``generation.requested`` it consumes. Stream redelivery (handler
    raised, ``dispatch_message`` retries up to ``max_retries=3``) means
    the same gen_id can hit this path more than once. The previous
    implementation always called ``save_state`` which is a bulk-overwrite
    of the main hash — that **clobbered ``cancelled=true``** set by the
    user-initiated /stop endpoint, silently un-cancelling the generation
    and letting the pipeline resume. We now skip recreation if the main
    state key already exists; the existing flags (cancelled, phase,
    bundle_id) survive untouched.
    """
    main_key = _state_key(generation_id)
    existing = await redis.exists(main_key)
    if existing:
        return await get_state(redis, generation_id)

    state = GenerationState(
        generation_id=generation_id,
        worker_id=worker_id,
        current_phase="requested",
        bundle_id=None,
        expected_pages=0,
        completed_pages=[],
        failed_pages={},
        page_states={},
        dominant_language="text",
        output_language=output_language,
    )
    await save_state(redis, state, ttl_seconds)
    return state


async def update_phase(
    redis: aioredis.Redis,
    generation_id: str,
    phase: str,
    *,
    phase_order: list[str] | None = None,
) -> None:
    """Persist the current pipeline phase, optionally enforcing monotonic
    advancement.
    """
    key = _state_key(generation_id)
    if phase_order is None:
        await redis.hset(key, "current_phase", phase)
        return

    try:
        new_idx = phase_order.index(phase)
    except ValueError:
        await redis.hset(key, "current_phase", phase)
        return

    current = await redis.hget(key, "current_phase")
    if current is None:
        await redis.hset(key, "current_phase", phase)
        return

    try:
        current_idx = phase_order.index(current)
    except ValueError:
        await redis.hset(key, "current_phase", phase)
        return

    if new_idx >= current_idx:
        await redis.hset(key, "current_phase", phase)


async def set_bundle_id(
    redis: aioredis.Redis,
    generation_id: str,
    bundle_id: int,
) -> None:
    key = _state_key(generation_id)
    await redis.hset(key, "bundle_id", str(bundle_id))


async def set_expected_pages(
    redis: aioredis.Redis,
    generation_id: str,
    count: int,
) -> None:
    key = _state_key(generation_id)
    await redis.hset(key, "expected_pages", str(count))


async def add_page_state(
    redis: aioredis.Redis,
    generation_id: str,
    page_id: str,
    spec: dict[str, tp.Any],
) -> None:
    """Initial registration of a page (status=pending, attempts=1)."""
    await upsert_page_state(
        redis,
        generation_id,
        page_id,
        status="pending",
        attempts=1,
        spec=spec,
    )


async def update_page_status(
    redis: aioredis.Redis,
    generation_id: str,
    page_id: str,
    status: str,
    increment_attempts: bool = False,
) -> None:
    if not increment_attempts:
        await upsert_page_state(redis, generation_id, page_id, status=status)
        return
    # Atomic-ish: read attempts, +1, write back. Per-page contention.
    page_states_key = _page_states_key(generation_id)
    raw = await redis.hget(page_states_key, page_id)
    attempts = 0
    if raw:
        try:
            attempts = int(json.loads(raw).get("attempts", 0))
        except (ValueError, TypeError):
            pass
    await upsert_page_state(
        redis,
        generation_id,
        page_id,
        status=status,
        attempts=attempts + 1,
    )


async def mark_page_completed(
    redis: aioredis.Redis,
    generation_id: str,
    page_id: str,
) -> int:
    """Mark a page as completed; returns the new completed count.

    Atomic: SADD on the completed-pages set + HSET on the per-page
    state hash. No more JSON read-modify-write loop, no more dropped
    page_ids under high concurrency.
    """
    total = await add_completed_page(redis, generation_id, page_id)
    await upsert_page_state(redis, generation_id, page_id, status="completed")
    return total


async def mark_page_failed(
    redis: aioredis.Redis,
    generation_id: str,
    page_id: str,
    reason: str,
) -> int:
    """Mark a page as failed; returns combined ``completed + failed`` count."""
    completed_key = _completed_key(generation_id)
    failed_key = _failed_key(generation_id)
    pipe = redis.pipeline()
    pipe.hset(failed_key, page_id, reason)
    pipe.expire(failed_key, _DEFAULT_TTL_SECONDS)
    pipe.scard(completed_key)
    pipe.hlen(failed_key)
    _hset, _exp, scard, hlen = await pipe.execute()
    await upsert_page_state(redis, generation_id, page_id, status="failed")
    return int(scard) + int(hlen)


async def is_generation_complete(
    redis: aioredis.Redis,
    generation_id: str,
) -> bool:
    """Atomic check: SCARD(completed) + HLEN(failed) >= expected_pages."""
    main_key = _state_key(generation_id)
    completed_key = _completed_key(generation_id)
    failed_key = _failed_key(generation_id)
    pipe = redis.pipeline()
    pipe.hget(main_key, "expected_pages")
    pipe.scard(completed_key)
    pipe.hlen(failed_key)
    expected_raw, scard, hlen = await pipe.execute()
    if expected_raw is None:
        return False
    try:
        expected = int(expected_raw)
    except (ValueError, TypeError):
        return False
    return (int(scard) + int(hlen)) >= expected and expected > 0


async def get_page_attempts(
    redis: aioredis.Redis,
    generation_id: str,
    page_id: str,
) -> int:
    page_states_key = _page_states_key(generation_id)
    raw = await redis.hget(page_states_key, page_id)
    if not raw:
        return 0
    try:
        return int(json.loads(raw).get("attempts", 0))
    except (ValueError, TypeError):
        return 0


async def delete_state(
    redis: aioredis.Redis,
    generation_id: str,
) -> None:
    """Remove all state keys for the generation."""
    pipe = redis.pipeline()
    pipe.delete(_state_key(generation_id))
    pipe.delete(_completed_key(generation_id))
    pipe.delete(_failed_key(generation_id))
    pipe.delete(_page_states_key(generation_id))
    pipe.delete(_source_files_key(generation_id))
    await pipe.execute()
