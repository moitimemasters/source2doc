"""Gateway /api/v1/streams integration tests.

PMI-mapping: 6.2.5 (Мониторинг событий генерации через Server-Sent Events).
"""

import json
from typing import Any

from httpx import AsyncClient


GENERATION_ID = "11111111-aaaa-bbbb-cccc-222222222222"


async def _seed_stream(redis: Any) -> None:
    stream_key = f"events:{GENERATION_ID}"
    await redis.xadd(
        stream_key,
        {
            "type": "generation.requested",
            "data": json.dumps(
                {"name": "Demo", "description": "x", "repo_id": "abc"}
            ),
        },
    )
    await redis.xadd(
        stream_key,
        {"type": "step.started", "data": json.dumps({"step": "planner"})},
    )


async def test_get_stream_events_returns_seeded_events(
    client: AsyncClient, fake_redis: Any
) -> None:
    await _seed_stream(fake_redis)
    response = await client.get(f"/api/v1/streams/{GENERATION_ID}/events")
    assert response.status_code == 200

    events = response.json()
    assert len(events) == 2
    assert events[0]["type"] == "generation.requested"
    assert events[1]["type"] == "step.started"
    assert events[1]["data"]["step"] == "planner"


async def test_get_stream_events_404_when_stream_missing(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/streams/00000000-0000-0000-0000-000000000999/events"
    )
    assert response.status_code == 404


async def test_list_streams_returns_running_status_for_unfinished_stream(
    client: AsyncClient, fake_redis: Any
) -> None:
    await _seed_stream(fake_redis)
    response = await client.get("/api/v1/streams")
    assert response.status_code == 200

    streams = response.json()["streams"]
    assert len(streams) == 1
    info = streams[0]
    assert info["stream_id"] == GENERATION_ID
    assert info["event_count"] == 2
    assert info["status"] == "running"
    assert info["name"] == "Demo"


async def test_list_streams_marks_completed_stream(
    client: AsyncClient, fake_redis: Any
) -> None:
    stream_key = f"events:{GENERATION_ID}"
    await fake_redis.xadd(
        stream_key,
        {
            "type": "generation.requested",
            "data": json.dumps({"name": "Done"}),
        },
    )
    await fake_redis.xadd(
        stream_key,
        {"type": "generation.completed", "data": json.dumps({})},
    )

    response = await client.get("/api/v1/streams")
    info = response.json()["streams"][0]
    assert info["status"] == "completed"
