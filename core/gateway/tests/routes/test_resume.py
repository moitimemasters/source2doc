"""Gateway POST /api/v1/tasks/{generation_id}/resume integration test.

Resume — unlike retry — keeps the same ``generation_id`` and re-emits
the last successful transition event into ``events:{gen_id}``. The
worker, on the other side of Redis, re-dispatches the handler whose
previous invocation failed.

The four scenarios covered here:

* Happy path — failure event present, ``state:docgen:{id}`` populated,
  multiple successful transition events upstream. Resume picks the most
  recent one and XADDs a copy into the events stream. The
  ``failed_pages`` field on state is reset.
* No failure event — request returns 422 (the run is either still
  running, completed, or never started).
* State evicted — Redis lost ``state:docgen:{id}`` (24h TTL). Even if a
  failure event is on the stream we can't resume safely; expect 422
  with a hint that points the user at Restart.
* Failed pages cleanup — ``state.failed_pages`` is non-empty before the
  resume call; after the call it must be reset to ``{}`` so those pages
  are re-attempted.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from httpx import AsyncClient


def _xadd_event(
    redis: Any,
    stream: str,
    event_type: str,
    data: dict[str, Any],
):
    """Helper to xadd an event in the same shape the worker emits."""
    return redis.xadd(stream, {"type": event_type, "data": json.dumps(data)})


async def _seed_state(
    redis: Any,
    gen_id: str,
    *,
    bundle_id: int | None = 42,
    completed_pages: list[str] | None = None,
    failed_pages: dict[str, str] | None = None,
) -> None:
    """Mirror ``state_mod.save_state`` shape closely enough for resume."""
    completed_pages = completed_pages or []
    failed_pages = failed_pages or {}
    await redis.hset(
        f"state:docgen:{gen_id}",
        mapping={
            "worker_id": "test-worker",
            "current_phase": "write",
            "bundle_id": str(bundle_id) if bundle_id else "",
            "expected_pages": "5",
            "completed_pages": json.dumps(completed_pages),
            "failed_pages": json.dumps(failed_pages),
            "page_states": "{}",
            "dominant_language": "python",
            "page_source_files": "{}",
        },
    )


async def test_resume_happy_path_reemits_last_transition_event(
    client: AsyncClient,
    fake_redis: Any,
) -> None:
    """A failed run with several successful transitions in its history.

    Stream timeline (oldest → newest):
      - generation.requested      (entry event — must NOT be picked)
      - ingest.completed
      - index.completed
      - task.failed               (failure marker)

    Resume should pick ``index.completed`` (latest TRANSITION, not
    failure) and re-XADD it.
    """
    gen_id = str(uuid4())
    stream = f"events:{gen_id}"

    await _seed_state(fake_redis, gen_id)

    await _xadd_event(
        fake_redis,
        stream,
        "generation.requested",
        {"generation_id": gen_id, "trace_id": "t" * 32, "repo_id": "r1"},
    )
    await _xadd_event(
        fake_redis,
        stream,
        "ingest.completed",
        {"generation_id": gen_id, "files_count": 12, "chunks_count": 88},
    )
    index_payload = {
        "generation_id": gen_id,
        "trace_id": "t" * 32,
        "repo_id": "r1",
        "indexed_chunks": 88,
    }
    index_entry_id = await _xadd_event(
        fake_redis, stream, "index.completed", index_payload
    )
    await _xadd_event(
        fake_redis,
        stream,
        "task.failed",
        {
            "generation_id": gen_id,
            "task_stream": "tasks:docgen",
            "event_type": "index.completed",
            "error": "planner crashed",
        },
    )

    entries_before = await fake_redis.xrange(stream, "-", "+")
    count_before = len(entries_before)

    response = await client.post(f"/api/v1/tasks/{gen_id}/resume")
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["generation_id"] == gen_id
    assert body["status"] == "queued"
    assert body["resumed_from_event"]["type"] == "index.completed"
    assert body["resumed_from_event"]["id"] == index_entry_id
    assert body["stream_url"].endswith(f"/streams/{gen_id}/stream")
    assert body["events_url"].endswith(f"/streams/{gen_id}/events")

    # Two new entries appended:
    #   1. ``task.resumed`` audit marker (so the event list reads
    #      "task.failed → task.resumed → re-emitted upstream").
    #   2. The re-emitted ``index.completed`` (new entry id, same payload).
    entries_after = await fake_redis.xrange(stream, "-", "+")
    assert len(entries_after) == count_before + 2

    audit_id, audit_fields = entries_after[-2]
    assert audit_fields["type"] == "task.resumed"
    audit_decoded = json.loads(audit_fields["data"])
    assert audit_decoded["generation_id"] == gen_id
    assert audit_decoded["resumed_from_event_type"] == "index.completed"
    assert audit_decoded["resumed_from_event_id"] == index_entry_id

    new_entry_id, new_fields = entries_after[-1]
    assert new_entry_id != index_entry_id
    assert new_fields["type"] == "index.completed"
    decoded = json.loads(new_fields["data"])
    # Original payload preserved + ``resumed`` marker stamped on.
    assert decoded["generation_id"] == gen_id
    assert decoded["indexed_chunks"] == 88
    assert decoded["repo_id"] == "r1"
    assert decoded["resumed"] is True

    # State preserved (bundle_id intact, failed_pages reset).
    state = await fake_redis.hgetall(f"state:docgen:{gen_id}")
    assert state["bundle_id"] == "42"
    assert state["failed_pages"] == "{}"

    # Stream re-armed in the active set so the watcher reliably picks it.
    assert await fake_redis.sismember("active_event_streams", stream)


async def test_resume_returns_422_when_no_failure_event(
    client: AsyncClient,
    fake_redis: Any,
) -> None:
    """Stream exists and has progress events, but no failure marker."""
    gen_id = str(uuid4())
    stream = f"events:{gen_id}"

    await _seed_state(fake_redis, gen_id)

    await _xadd_event(
        fake_redis,
        stream,
        "generation.requested",
        {"generation_id": gen_id},
    )
    await _xadd_event(
        fake_redis,
        stream,
        "ingest.completed",
        {"generation_id": gen_id, "files_count": 5},
    )

    response = await client.post(f"/api/v1/tasks/{gen_id}/resume")
    assert response.status_code == 422
    body = response.json()
    detail = body.get("detail", "").lower()
    assert "not in a failed state" in detail or "no" in detail


async def test_resume_returns_422_when_state_missing(
    client: AsyncClient,
    fake_redis: Any,
) -> None:
    """Failure event is on the stream but worker state was evicted."""
    gen_id = str(uuid4())
    stream = f"events:{gen_id}"

    # Deliberately do NOT call _seed_state — simulates 24h TTL eviction.
    await _xadd_event(
        fake_redis,
        stream,
        "generation.requested",
        {"generation_id": gen_id},
    )
    await _xadd_event(
        fake_redis,
        stream,
        "ingest.completed",
        {"generation_id": gen_id, "files_count": 5},
    )
    await _xadd_event(
        fake_redis,
        stream,
        "task.failed",
        {"generation_id": gen_id, "error": "boom"},
    )

    response = await client.post(f"/api/v1/tasks/{gen_id}/resume")
    assert response.status_code == 422
    detail = response.json()["detail"]
    # The hint must steer the user to Restart so they recover instead of
    # bouncing on the broken Resume button.
    assert "expired" in detail.lower()
    assert "restart" in detail.lower()


async def test_resume_clears_failed_pages_so_they_get_retried(
    client: AsyncClient,
    fake_redis: Any,
) -> None:
    """Pages in ``state.failed_pages`` block ``is_complete()``; resume must
    wipe that map so the writer re-attempts them."""
    gen_id = str(uuid4())
    stream = f"events:{gen_id}"

    await _seed_state(
        fake_redis,
        gen_id,
        failed_pages={"page-1": "writer hallucinated", "page-2": "json invalid"},
    )

    await _xadd_event(
        fake_redis,
        stream,
        "generation.requested",
        {"generation_id": gen_id},
    )
    await _xadd_event(
        fake_redis,
        stream,
        "ingest.completed",
        {"generation_id": gen_id, "files_count": 5},
    )
    await _xadd_event(
        fake_redis,
        stream,
        "index.completed",
        {"generation_id": gen_id},
    )
    await _xadd_event(
        fake_redis,
        stream,
        "step.failed",
        {"generation_id": gen_id, "error": "writer phase exhausted retries"},
    )

    # Pre-condition sanity check.
    state_before = await fake_redis.hgetall(f"state:docgen:{gen_id}")
    failed_before = json.loads(state_before["failed_pages"])
    assert "page-1" in failed_before

    response = await client.post(f"/api/v1/tasks/{gen_id}/resume")
    assert response.status_code == 200, response.text

    state_after = await fake_redis.hgetall(f"state:docgen:{gen_id}")
    assert state_after["failed_pages"] == "{}"
    # bundle_id and other state fields untouched.
    assert state_after["bundle_id"] == "42"
    assert state_after["expected_pages"] == "5"


async def test_resume_returns_422_when_no_events_stream(
    client: AsyncClient,
    fake_redis: Any,
) -> None:
    """Generation id with no Redis events stream at all → 422."""
    gen_id = str(uuid4())

    response = await client.post(f"/api/v1/tasks/{gen_id}/resume")
    assert response.status_code == 422
    detail = response.json()["detail"].lower()
    assert "no events" in detail or "trimmed" in detail


async def test_resume_clears_subplan_tracker_when_resuming_outline(
    client: AsyncClient,
    fake_redis: Any,
) -> None:
    """Resuming from ``plan.outline_created`` must wipe ``subplan:{id}:*``
    keys so the fan-in aggregator re-seeds cleanly."""
    gen_id = str(uuid4())
    stream = f"events:{gen_id}"

    await _seed_state(fake_redis, gen_id)

    # Stale tracker keys from the previous run.
    await fake_redis.sadd(f"subplan:{gen_id}:pending", "section-a", "section-b")
    await fake_redis.set(f"subplan:{gen_id}:aggregated", "1")
    await fake_redis.hset(f"subplan:{gen_id}:meta", mapping={"k": "v"})

    await _xadd_event(
        fake_redis,
        stream,
        "generation.requested",
        {"generation_id": gen_id},
    )
    await _xadd_event(
        fake_redis,
        stream,
        "ingest.completed",
        {"generation_id": gen_id, "files_count": 5},
    )
    await _xadd_event(
        fake_redis,
        stream,
        "index.completed",
        {"generation_id": gen_id},
    )
    await _xadd_event(
        fake_redis,
        stream,
        "plan.outline_created",
        {
            "generation_id": gen_id,
            "outline": {"sections": [{"id": "section-a"}, {"id": "section-b"}]},
        },
    )
    await _xadd_event(
        fake_redis,
        stream,
        "task.failed",
        {"generation_id": gen_id, "error": "subplan crashed"},
    )

    response = await client.post(f"/api/v1/tasks/{gen_id}/resume")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resumed_from_event"]["type"] == "plan.outline_created"

    # All subplan tracker keys should be gone.
    assert not await fake_redis.exists(f"subplan:{gen_id}:pending")
    assert not await fake_redis.exists(f"subplan:{gen_id}:aggregated")
    assert not await fake_redis.exists(f"subplan:{gen_id}:meta")
