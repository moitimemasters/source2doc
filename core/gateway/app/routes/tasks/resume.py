"""Resume-failed-generation endpoint.

Sister to ``retry`` but with very different semantics: ``retry`` mints a
fresh ``generation_id`` and re-runs every phase from scratch; ``resume``
keeps the same ``generation_id``, the same Qdrant collection, the same
Postgres bundle row, the same Redis state, and asks the worker to
re-process only the phase that failed (plus everything downstream).

Mechanism
---------
The docgen worker subscribes to every ``events:{gen_id}`` stream that
matches its scan pattern and dispatches handlers off each new entry. A
failed handler emits ``task.failed`` (or ``step.failed`` /
``handler.error``) but the *trigger* event for that handler — the
upstream ``*.completed`` — is still sitting in the stream. By
re-XADD'ing that trigger event with a fresh entry id we get the worker
to run the failed handler again, this time hopefully successfully.

Idempotency caveats
-------------------
Most handlers are tolerant of a re-fire (writes use ON CONFLICT, the
write-page handler bumps an attempt counter, etc.). The notable
exception is the subplan fan-out + fan-in aggregator, which keeps
per-generation tracker keys (``subplan:{id}:pending`` etc.) in Redis.
When we re-emit ``plan.outline_created`` we wipe those tracker keys so
the fan-out re-seeds them cleanly. ``handle_outline_created`` already
deletes the same keys on entry; the explicit wipe here mostly guards
against resuming from an event that's later than the outline.

State preservation
------------------
``state:docgen:{gen_id}`` is the worker's per-generation memory
(``bundle_id``, ``completed_pages``, etc.). We never delete it on
resume — the whole point is to *not* re-do completed work. We do clear
the per-page failure list (``state.failed_pages``) so any pages that
hit terminal failure get retried.

If the state was evicted by Redis (24h TTL) the resume can't
reasonably proceed — the worker has no way to rebuild ``bundle_id`` /
``completed_pages`` mid-pipeline. We return 422 with a clear hint that
the user should fall back to ``retry`` (which restarts from scratch).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
import redis.asyncio as aioredis
import structlog

from source2doc.pipelines import DOCGEN
from source2doc.pipelines.types import EventKind

from app.routes.streams import dependencies as streams_deps
from app.security.admin import require_admin


logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tasks",
    tags=["tasks"],
    dependencies=[Depends(require_admin)],
)


# Events that signal the run terminated abnormally OR was halted by the
# user. ``task.stopped`` is a deliberate user-cancel marker, not an error,
# but it's exactly as resumable as a failure — same checkpoint logic, same
# state preservation. Treating them uniformly here is what lets the UI
# Resume button work for both "Generation failed" and "Generation stopped"
# banners. ``generation.failed`` isn't in the registry currently but the
# streams service treats it as terminal too — defensive include.
_FAILURE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "task.failed",
        "task.stopped",
        "step.failed",
        "handler.error",
        "generation.failed",
        "ingest.failed",
        "page.failed",
    }
)

# Events that signal the run already finished successfully — we never
# resume those.
_TERMINAL_OK_EVENT_TYPES: frozenset[str] = frozenset({"generation.completed"})


@router.post(
    "/{generation_id}/resume",
    response_model=None,  # response built by hand to avoid pydantic UUID coercion
)
async def resume_task_route(
    generation_id: UUID,
    redis: aioredis.Redis = Depends(streams_deps.get_redis),
) -> dict[str, Any]:
    return await _resume_task(generation_id, redis)


async def _resume_task(
    generation_id: UUID,
    redis: aioredis.Redis,
) -> dict[str, Any]:
    gen_id = str(generation_id)
    events_stream = f"events:{gen_id}"

    entries = await _read_events(redis, events_stream)
    if not entries:
        logger.warning("resume_no_events_stream", generation_id=gen_id)
        raise HTTPException(
            status_code=422,
            detail=(
                "cannot resume — no events found for this generation "
                "(stream may have been trimmed or never existed)"
            ),
        )

    has_failure, has_completion = _classify_terminal(entries)
    if has_completion:
        logger.info("resume_already_completed", generation_id=gen_id)
        raise HTTPException(
            status_code=422,
            detail=(
                "cannot resume — generation already completed successfully"
            ),
        )
    if not has_failure:
        logger.info("resume_no_failure_marker", generation_id=gen_id)
        raise HTTPException(
            status_code=422,
            detail=(
                "cannot resume — generation is not in a failed or stopped "
                "state (no task.failed / task.stopped / step.failed / "
                "handler.error event found)"
            ),
        )

    # Worker state is the load-bearing piece. Without it the next handler
    # has no bundle_id / completed_pages and would corrupt the run.
    state_key = f"state:docgen:{gen_id}"
    state_exists = bool(await redis.exists(state_key))
    if not state_exists:
        logger.warning("resume_state_evicted", generation_id=gen_id)
        raise HTTPException(
            status_code=422,
            detail=(
                "cannot resume — worker state has expired (Redis TTL). "
                "Use Restart instead to re-run the generation from scratch."
            ),
        )

    # Per-page resume: when the run was halted DURING the page-flow phase
    # (write/diagram/review/normalize/finalize), re-emit only the events
    # that didn't reach a terminal state for each page. This is much more
    # efficient than re-firing ``plan.created`` (which would re-fan-out
    # 40+ writers including ones that already finished).
    completed_pages = await redis.smembers(f"state:docgen:{gen_id}:completed")
    page_emits = _build_page_resume_plan(entries, completed_pages)

    warnings: list[str] = []

    if page_emits:
        # We have unfinished pages — surgical resume. Skip the global
        # last-transition logic; the trigger events emitted below cover
        # every page that didn't finalize.
        await redis.hset(state_key, "failed_pages", "{}")
        await redis.hset(state_key, "cancelled", "false")
        await redis.sadd("active_event_streams", events_stream)
        await _xadd_event(
            redis,
            events_stream,
            "task.resumed",
            {
                "generation_id": gen_id,
                "resumed_strategy": "per_page",
                "resumed_event_count": len(page_emits),
            },
        )
        for evt_type, evt_payload in page_emits:
            await _xadd_event(redis, events_stream, evt_type, evt_payload)
        logger.info(
            "task_resume_enqueued_per_page",
            generation_id=gen_id,
            event_count=len(page_emits),
        )
        return {
            "generation_id": gen_id,
            "resumed_from_event": {
                "type": "per_page",
                "id": str(len(page_emits)),
            },
            "status": "queued",
            "message": (
                f"Resume queued — re-emitted {len(page_emits)} per-page "
                f"event(s) for unfinished work."
            ),
            "stream_url": f"/api/v1/streams/{gen_id}/stream",
            "events_url": f"/api/v1/streams/{gen_id}/events",
            "warnings": warnings,
        }

    # No per-page work to resume → run was halted before the page phase
    # (during ingest / index / planner / subplanner). Fall back to the
    # global "re-emit last successful transition" approach.
    last_transition = _find_last_successful_transition(entries)
    if last_transition is None:
        logger.warning("resume_no_transition_event", generation_id=gen_id)
        raise HTTPException(
            status_code=422,
            detail=(
                "cannot resume — no successful upstream transition event "
                "found before the failure point. The pipeline may have "
                "failed at the very first step; use Restart instead."
            ),
        )

    original_entry_id, event_type, payload = last_transition

    # Clear stale subplan tracker keys when the resume target is anywhere
    # at-or-before the subplan phase. Re-firing ``plan.outline_created``
    # without this would risk a half-drained pending set seeing extra
    # ``subplan.completed`` events from the previous run and double-emitting
    # ``plan.created``. The fan-out handler also deletes these keys on
    # entry, so this is belt-and-suspenders.
    if event_type in {
        "ingest.completed",
        "iterative.index_completed",
        "index.completed",
        "plan.outline_created",
    }:
        await _clear_subplan_tracker(redis, gen_id)

    # Drop the per-page failure list. Pages that terminally failed in the
    # previous run should be re-attempted as part of the resume — leaving
    # them in ``state.failed_pages`` would bias ``is_complete()`` and the
    # writer would skip them. Per-page in-flight markers are preserved;
    # the writer is tolerant of repeat ``page.write_requested`` events.
    await redis.hset(state_key, "failed_pages", "{}")
    # Clear the user-cancellation flag if it was set by ``/stop``.
    # Otherwise the worker would skip+ack the event we're about to
    # re-emit and resume would no-op.
    await redis.hset(state_key, "cancelled", "false")

    # Make sure the worker actually subscribes to this stream. The watcher
    # discovers streams via SCAN — but if cleanup ran for some reason
    # (shouldn't on a failed run, but defense in depth) we add it back to
    # the active set so any tooling that consumes that set still sees it.
    await redis.sadd("active_event_streams", events_stream)

    # Audit marker: emit ``task.resumed`` BEFORE the re-emit so the event
    # list reads "task.failed → task.resumed → <re-emitted upstream>".
    # The frontend can render the prior task.failed as struck-through /
    # superseded once it sees a subsequent task.resumed for the same gen.
    # We don't delete the original task.failed (audit trail matters).
    await _xadd_event(
        redis,
        events_stream,
        "task.resumed",
        {
            "generation_id": gen_id,
            "resumed_from_event_type": event_type,
            "resumed_from_event_id": original_entry_id,
        },
    )

    # Re-emit the trigger event. The new entry id will be fresh; the worker
    # treats it like any other incoming event and dispatches the handler
    # whose previous invocation failed.
    new_entry_id = await _xadd_event(redis, events_stream, event_type, payload)

    logger.info(
        "task_resume_enqueued",
        generation_id=gen_id,
        resumed_from_event_type=event_type,
        original_entry_id=original_entry_id,
        new_entry_id=new_entry_id,
    )

    return {
        "generation_id": gen_id,
        "resumed_from_event": {
            "type": event_type,
            "id": original_entry_id,
        },
        "status": "queued",
        "message": (
            f"Resume queued. Worker will re-run from {event_type!r}."
        ),
        "stream_url": f"/api/v1/streams/{gen_id}/stream",
        "events_url": f"/api/v1/streams/{gen_id}/events",
        "warnings": warnings,
    }


async def _read_events(
    redis: aioredis.Redis,
    stream_name: str,
) -> list[tuple[str, dict[str, str]]]:
    """Read up to 1000 most-recent stream entries newest-first.

    1000 is a generous upper bound — even a chatty docgen run rarely
    exceeds a few hundred entries before terminating, and SUBPLAN/diagram
    fan-outs trim much earlier. Returns ``[]`` when the stream is missing
    or trimmed.
    """
    try:
        return await redis.xrevrange(stream_name, "+", "-", count=1000)
    except aioredis.ResponseError:
        return []


def _classify_terminal(
    entries: list[tuple[str, dict[str, str]]],
) -> tuple[bool, bool]:
    """Return ``(has_failure, has_completion)`` for the given entries."""
    has_failure = False
    has_completion = False
    for _entry_id, fields in entries:
        etype = fields.get("type", "")
        if etype in _FAILURE_EVENT_TYPES:
            has_failure = True
        if etype in _TERMINAL_OK_EVENT_TYPES:
            has_completion = True
        if has_failure and has_completion:
            break
    return has_failure, has_completion


# Per-page event types — events whose ``data.page_id`` (or
# ``data.page_spec.page_id``) identifies a single page in the
# write→diagram→review→normalize→finalize sub-pipeline.
_PAGE_LEVEL_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "page.write_requested",
        "page.written",
        "page.diagrams_completed",
        "page.reviewed",
        "page.revision_requested",
        "page.completed",
        "page.normalize_started",
        "page.normalized",
    }
)

# Diagram-level events still carry ``page_id`` — when a page's latest
# event lands here we treat the page as "in diagram fan-out" and roll
# back to ``page.written`` for clean re-fan-out (the diagram aggregator's
# Redis tracker is wiped on every ``page.written`` handler invocation).
_DIAGRAM_LEVEL_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "diagram.requested",
        "diagram.completed",
    }
)

# Per-page terminal events. Pages whose latest event is one of these are
# "done" from the resume perspective — either successfully created
# (``doc.page.created``) or terminally failed.
_PAGE_TERMINAL_SUCCESS_EVENT_TYPES: frozenset[str] = frozenset(
    {"doc.page.created"}
)
_PAGE_TERMINAL_FAILURE_EVENT_TYPES: frozenset[str] = frozenset(
    {"doc.page.failed", "page.failed"}
)


def _extract_page_id(data: dict[str, Any]) -> str | None:
    """Pull ``page_id`` from event data, looking in ``page_spec`` as a
    fallback. ``page.write_requested`` nests it inside ``page_spec``;
    most other per-page events carry it at the top level.
    """
    pid = data.get("page_id")
    if isinstance(pid, str) and pid:
        return pid
    spec = data.get("page_spec")
    if isinstance(spec, dict):
        spec_pid = spec.get("page_id")
        if isinstance(spec_pid, str) and spec_pid:
            return spec_pid
    return None


def _build_page_resume_plan(
    entries: list[tuple[str, dict[str, str]]],
    completed_pages: set[str],
) -> list[tuple[str, dict[str, Any]]]:
    """Walk events stream and return ``(event_type, payload)`` pairs to
    re-emit for every page that hasn't reached a terminal state.

    Algorithm:

    1. Walk entries oldest-first. For each event with a recoverable
       ``page_id``, record the latest non-progress event as that page's
       "front" + remember the original ``page.write_requested`` payload
       (used for failed-page restarts where we want a fresh
       ``attempt=1`` writer run).
    2. Capture the final ``plan.created`` event so pages that never even
       got a ``page.write_requested`` (queue was drained / consumer skip-
       acked them all before the writer started) can be synthesised.
    3. For each page with a "front" that's not terminal:
       - Failed page → re-emit ``page.write_requested`` with
         ``attempt=1`` (clean retry).
       - Front in diagram fan-out → re-emit the captured ``page.written``
         to trigger the diagram handler, which wipes the per-page
         aggregator tracker and re-fans-out from scratch. Diagrams that
         were already done get redone (deemed acceptable since the
         diagrammer is cheap and the aggregator's stale state is
         non-trivial to reconcile).
       - Front is page-level → re-emit it as-is; the next-stage handler
         picks up.
    4. For every page in the captured ``plan.created`` that wasn't seen
       at all (no events) and isn't already in ``completed_pages``,
       synthesise a fresh ``page.write_requested``.

    The caller is responsible for clearing ``state.cancelled`` and
    ``state.failed_pages`` before re-emitting; we only return the list.
    """
    page_latest: dict[str, tuple[str, dict[str, Any]]] = {}
    page_initial_request: dict[str, dict[str, Any]] = {}
    page_written_payload: dict[str, dict[str, Any]] = {}
    plan_created_payload: dict[str, Any] | None = None
    common_plan_meta: dict[str, Any] = {}

    # ``entries`` arrives newest-first from ``_read_events``; walk
    # oldest-first so the "latest" map records the chronological tail.
    for _entry_id, fields in reversed(entries):
        etype = fields.get("type", "")
        if not etype:
            continue
        try:
            data = json.loads(fields.get("data", "{}"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue

        if etype == "plan.created":
            plan_created_payload = data
            common_plan_meta = {
                "repo_id": data.get("repo_id"),
                "path": data.get("path"),
            }
            continue

        if etype not in _PAGE_LEVEL_EVENT_TYPES \
                and etype not in _DIAGRAM_LEVEL_EVENT_TYPES \
                and etype not in _PAGE_TERMINAL_SUCCESS_EVENT_TYPES \
                and etype not in _PAGE_TERMINAL_FAILURE_EVENT_TYPES:
            continue

        pid = _extract_page_id(data)
        if not pid:
            continue

        page_latest[pid] = (etype, data)
        if etype == "page.write_requested" and pid not in page_initial_request:
            page_initial_request[pid] = data
        if etype == "page.written":
            page_written_payload[pid] = data

    emits: list[tuple[str, dict[str, Any]]] = []
    seen_pages: set[str] = set()

    for pid, (etype, data) in page_latest.items():
        seen_pages.add(pid)
        if pid in completed_pages:
            continue
        if etype in _PAGE_TERMINAL_SUCCESS_EVENT_TYPES:
            # Defensive: doc.page.created should have populated
            # ``completed_pages`` already, but if it didn't (legacy state
            # / Redis eviction), don't re-process.
            continue
        if etype in _PAGE_TERMINAL_FAILURE_EVENT_TYPES:
            initial = page_initial_request.get(pid)
            if initial is None:
                # No write_requested in the stream window — can only
                # synthesise from plan_created_payload below.
                continue
            fresh = dict(initial)
            fresh["attempt"] = 1
            emits.append(("page.write_requested", fresh))
            continue
        if etype in _DIAGRAM_LEVEL_EVENT_TYPES:
            written = page_written_payload.get(pid)
            if written is not None:
                emits.append(("page.written", written))
            else:
                initial = page_initial_request.get(pid)
                if initial is not None:
                    fresh = dict(initial)
                    fresh["attempt"] = 1
                    emits.append(("page.write_requested", fresh))
            continue
        # Page-level event → re-emit verbatim, the next-stage handler
        # picks up the chain.
        emits.append((etype, data))

    # Pages from plan.created that never produced an event at all.
    if plan_created_payload is not None:
        plan = plan_created_payload.get("plan") or {}
        page_specs = plan.get("page_specs") or []
        for spec in page_specs:
            if not isinstance(spec, dict):
                continue
            pid = spec.get("page_id")
            if not isinstance(pid, str) or not pid:
                continue
            if pid in seen_pages or pid in completed_pages:
                continue
            synthesised = {
                "page_spec": spec,
                "attempt": 1,
            }
            if common_plan_meta.get("repo_id"):
                synthesised["repo_id"] = common_plan_meta["repo_id"]
            if common_plan_meta.get("path"):
                synthesised["path"] = common_plan_meta["path"]
            emits.append(("page.write_requested", synthesised))

    return emits


def _find_last_successful_transition(
    entries: list[tuple[str, dict[str, str]]],
) -> tuple[str, str, dict[str, Any]] | None:
    """Find the most recent ``EventKind.TRANSITION`` event in the stream
    that is not itself a failure marker.

    Returns ``(entry_id, event_type, decoded_data)`` or None.

    Walking newest-first means the first transition we hit is the latest
    successful step before the failure (failure events themselves are
    ``EventKind.ERROR`` and skipped here). We deliberately also skip the
    pipeline entry event (``generation.requested``) because re-emitting
    that runs the *ingest* handler — equivalent to a full restart, which
    is what the dedicated ``retry`` endpoint already does.
    """
    for entry_id, fields in entries:
        etype = fields.get("type", "")
        if not etype:
            continue
        if etype in _FAILURE_EVENT_TYPES:
            continue
        if etype == DOCGEN.entry_event:
            # ``generation.requested`` is the pipeline's seed — re-emitting
            # it would restart ingest, which defeats the purpose of resume.
            continue
        if not DOCGEN.has_event(etype):
            continue
        ev_def = DOCGEN.event(etype)
        if ev_def.kind != EventKind.TRANSITION:
            continue
        data_raw = fields.get("data", "{}")
        try:
            decoded = json.loads(data_raw)
        except json.JSONDecodeError:
            decoded = {}
        if not isinstance(decoded, dict):
            decoded = {}
        return entry_id, etype, decoded
    return None


async def _clear_subplan_tracker(redis: aioredis.Redis, gen_id: str) -> None:
    """Delete any leftover ``subplan:{gen_id}:*`` keys.

    The subplan handler keeps ``pending``, ``results``, ``meta``, and
    ``aggregated`` keys in Redis to coordinate its fan-in across
    concurrent ``subplan.completed`` events. If we resume from
    ``plan.outline_created`` (or earlier) without nuking those, a stale
    aggregated-sentinel would suppress the fan-in re-emit. SCAN+DEL
    instead of hard-coding key names so any new tracker keys added
    later get swept too.
    """
    pattern = f"subplan:{gen_id}:*"
    cursor: int | str = 0
    keys_to_delete: list[str] = []
    while True:
        cursor, batch = await redis.scan(cursor=cursor, match=pattern, count=100)
        keys_to_delete.extend(batch)
        if cursor == 0 or cursor == "0":
            break
    if keys_to_delete:
        await redis.delete(*keys_to_delete)
        logger.info(
            "resume_cleared_subplan_tracker",
            generation_id=gen_id,
            keys_deleted=len(keys_to_delete),
        )


async def _xadd_event(
    redis: aioredis.Redis,
    stream_name: str,
    event_type: str,
    data: dict[str, Any],
) -> str:
    """XADD a fresh copy of an event onto the per-generation stream.

    Mirrors ``worker.streams.consumer._xadd_event`` so the payload shape
    matches what the worker expects (``type`` + ``data`` JSON). Stamping a
    ``resumed=True`` flag on the data lets handlers eventually distinguish
    re-emits from originals — they don't today, but it's cheap insurance.
    """
    payload = dict(data)
    payload.setdefault("resumed", True)
    return await redis.xadd(
        stream_name,
        {
            "type": event_type,
            "data": json.dumps(payload),
        },
    )
