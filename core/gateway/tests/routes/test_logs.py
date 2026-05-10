"""Gateway /api/v1/logs integration tests.

PMI-mapping: 6.2.11 (Просмотр логов генерации).
"""

from typing import Any

from httpx import AsyncClient


GENERATION_ID = "ffffffff-1111-2222-3333-444444444444"


async def test_get_logs_returns_parsed_entries(client: AsyncClient, fake_redis: Any) -> None:
    stream_key = f"logs:{GENERATION_ID}"
    await fake_redis.xadd(
        stream_key,
        {
            "level": "info",
            "event": "started",
            "timestamp": "2026-05-04T00:00:00Z",
            "logger": "worker.docgen",
        },
    )
    await fake_redis.xadd(
        stream_key,
        {
            "level": "error",
            "event": "boom",
            "timestamp": "2026-05-04T00:00:01Z",
            "logger": "worker.docgen",
        },
    )

    response = await client.get(f"/api/v1/logs/{GENERATION_ID}")
    assert response.status_code == 200

    body = response.json()
    assert body["generation_id"] == GENERATION_ID
    assert len(body["entries"]) == 2
    assert body["entries"][0]["event"] == "started"
    assert body["entries"][1]["level"] == "error"


async def test_get_logs_returns_empty_when_no_stream(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/logs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 200
    assert response.json()["entries"] == []


async def test_get_logs_filters_by_from_timestamp(client: AsyncClient, fake_redis: Any) -> None:
    """`from` query param trims out entries written before the cutoff.

    Redis stream IDs are millisecond-prefixed, so we add entries with
    explicit IDs to control which side of the cutoff they fall on.
    """
    stream_key = f"logs:{GENERATION_ID}"
    # Entry at t=1_000_000 ms (before cutoff)
    await fake_redis.xadd(
        stream_key,
        {
            "level": "info",
            "event": "old",
            "timestamp": "2026-05-04T00:00:00Z",
            "logger": "worker.docgen",
        },
        id="1000000-0",
    )
    # Entry at t=2_000_000 ms (at/after cutoff)
    await fake_redis.xadd(
        stream_key,
        {
            "level": "info",
            "event": "new",
            "timestamp": "2026-05-04T00:01:00Z",
            "logger": "worker.docgen",
        },
        id="2000000-0",
    )

    # 1_500_000 ms = 1970-01-01T00:25:00+00:00 → trims the first entry only.
    cutoff_iso = "1970-01-01T00:25:00+00:00"
    response = await client.get(f"/api/v1/logs/{GENERATION_ID}", params={"from": cutoff_iso})
    assert response.status_code == 200
    body = response.json()
    events = [e["event"] for e in body["entries"]]
    assert events == ["new"]


async def test_get_logs_filters_by_to_timestamp(client: AsyncClient, fake_redis: Any) -> None:
    stream_key = f"logs:{GENERATION_ID}"
    await fake_redis.xadd(
        stream_key,
        {
            "level": "info",
            "event": "early",
            "timestamp": "x",
            "logger": "l",
        },
        id="1000000-0",
    )
    await fake_redis.xadd(
        stream_key,
        {
            "level": "info",
            "event": "late",
            "timestamp": "x",
            "logger": "l",
        },
        id="2000000-0",
    )

    # cutoff_to = 1_500_000 ms → keeps the early entry only.
    cutoff_iso = "1970-01-01T00:25:00+00:00"
    response = await client.get(f"/api/v1/logs/{GENERATION_ID}", params={"to": cutoff_iso})
    assert response.status_code == 200
    events = [e["event"] for e in response.json()["entries"]]
    assert events == ["early"]


async def test_get_logs_invalid_iso_falls_back_to_unfiltered(
    client: AsyncClient, fake_redis: Any
) -> None:
    """Garbage in `from`/`to` should not crash; just drop the bound."""
    stream_key = f"logs:{GENERATION_ID}"
    await fake_redis.xadd(
        stream_key,
        {"level": "info", "event": "a", "timestamp": "x", "logger": "l"},
    )
    response = await client.get(
        f"/api/v1/logs/{GENERATION_ID}",
        params={"from": "not-a-date", "to": "also-bad"},
    )
    assert response.status_code == 200
    assert len(response.json()["entries"]) == 1
