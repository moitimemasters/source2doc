"""Gateway POST /api/v1/tasks/{generation_id}/retry integration test.

Covers the two recovery paths exercised by ``app.routes.tasks.retry``:

* DLQ path — the worker exhausted ``max_retries`` and pushed the original
  payload onto ``dlq:tasks:docgen``. Retry must reuse the encrypted
  config blob referenced by ``original.config_key`` and re-enqueue under
  a fresh ``generation_id``.

* No-DLQ-yet path — only a ``task.failed`` event exists on
  ``events:{gen_id}`` and the encrypted config still lives at
  ``config:{gen_id}``. Retry must read that key directly.

The unrecoverable case (no DLQ entry, no live config blob) returns 422.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from cryptography.fernet import Fernet
from httpx import AsyncClient


def _enc(encryption_key: str, payload: dict[str, Any]) -> str:
    return Fernet(encryption_key.encode()).encrypt(json.dumps(payload).encode()).decode()


def _dec(encryption_key: str, blob: str) -> dict[str, Any]:
    return json.loads(Fernet(encryption_key.encode()).decrypt(blob.encode()).decode())


def _user_config(generation_id: str) -> dict[str, Any]:
    """A plausible decrypted task config — mirrors what create_task writes."""
    return {
        "generation_id": generation_id,
        "repo_id": "11111111-2222-3333-4444-555555555555",
        "name": "My docs",
        "description": "test description",
        "llm": {
            "provider": "openai-compatible",
            "model": "gpt-4o-mini",
            "api_key": "sk-test-llm",
            "base_url": None,
            "temperature": 0.5,
            "max_tokens": 1024,
        },
        "embeddings": {
            "provider": "openai",
            "model": "text-embedding-3-small",
            "api_key": "sk-test-emb",
            "dimensions": 1536,
        },
        "qdrant": {
            "url": "http://qdrant:6333",
            "collection": f"docgen_{generation_id}",
            "api_key": None,
        },
        "postgres": {"connection_string": None},
        "generation": {},
        "force_reindex": False,
    }


async def _seed_dlq_failure(
    redis: Any,
    encryption_key: str,
    old_id: str,
    *,
    write_config_blob: bool = True,
) -> None:
    """Seed a DLQ entry + matching encrypted config + task.failed event."""
    user_config = _user_config(old_id)
    encrypted = _enc(encryption_key, user_config)
    if write_config_blob:
        await redis.setex(f"config:{old_id}", 86400, encrypted)

    # DLQ envelope shape — see worker.streams.consumer._move_to_dlq.
    dlq_payload = {
        "original_message_id": "1700000000000-0",
        "original_stream": "tasks:docgen",
        "event_type": "task.created",
        "data": {
            "generation_id": old_id,
            "trace_id": "deadbeef" * 4,
            "config_key": f"config:{old_id}",
            "qdrant_collection": f"docgen_{old_id}",
            "name": "My docs",
            "force_reindex": False,
        },
        "attempts": 3,
    }
    await redis.xadd(
        "dlq:tasks:docgen",
        {"type": "task.failed", "data": json.dumps(dlq_payload)},
    )

    # Per-generation events stream — used by the gateway to discover
    # ``task_stream`` when computing the DLQ key.
    await redis.xadd(
        f"events:{old_id}",
        {
            "type": "task.failed",
            "data": json.dumps(
                {
                    "generation_id": old_id,
                    "task_stream": "tasks:docgen",
                    "event_type": "task.created",
                    "attempts": 3,
                    "error": "boom",
                }
            ),
        },
    )


async def test_retry_via_dlq_reenqueues_with_fresh_generation_id(
    client: AsyncClient,
    fake_redis: Any,
    encryption_key: str,
) -> None:
    old_id = str(uuid4())
    await _seed_dlq_failure(fake_redis, encryption_key, old_id)

    response = await client.post(f"/api/v1/tasks/{old_id}/retry")
    assert response.status_code == 200, response.text

    body = response.json()
    new_id = body["generation_id"]
    assert new_id != old_id
    assert body["retried_from"] == old_id
    assert body["status"] == "queued"
    assert body["stream_url"].endswith(f"/streams/{new_id}/stream")
    assert body["events_url"].endswith(f"/streams/{new_id}/events")

    # 1. A new task entry was xadd'd onto tasks:docgen.
    entries = await fake_redis.xrange("tasks:docgen", "-", "+")
    assert len(entries) == 1
    _, fields = entries[0]
    assert fields["type"] == "task.created"
    payload = json.loads(fields["data"])
    assert payload["generation_id"] == new_id
    assert payload["config_key"] == f"config:{new_id}"
    assert payload["qdrant_collection"] == f"docgen_{new_id}"
    assert payload["name"] == "My docs"
    assert payload["force_reindex"] is False
    # New trace_id, not reused from the failed run.
    assert payload["trace_id"] != "deadbeef" * 4
    assert len(payload["trace_id"]) == 32

    # 2. New encrypted config blob exists, decrypts to the same secrets,
    # but with the generation_id / qdrant collection rewritten.
    new_blob = await fake_redis.get(f"config:{new_id}")
    assert new_blob is not None
    decrypted = _dec(encryption_key, new_blob)
    assert decrypted["generation_id"] == new_id
    assert decrypted["qdrant"]["collection"] == f"docgen_{new_id}"
    assert decrypted["llm"]["api_key"] == "sk-test-llm"
    assert decrypted["embeddings"]["api_key"] == "sk-test-emb"
    assert decrypted["repo_id"] == "11111111-2222-3333-4444-555555555555"


async def test_retry_falls_back_to_live_config_when_no_dlq_entry(
    client: AsyncClient,
    fake_redis: Any,
    encryption_key: str,
) -> None:
    """When the message hasn't been DLQ'd yet but ``config:{id}`` is live."""
    old_id = str(uuid4())
    user_config = _user_config(old_id)
    encrypted = _enc(encryption_key, user_config)
    await fake_redis.setex(f"config:{old_id}", 86400, encrypted)

    # Emit only a task.failed event — no DLQ entry.
    await fake_redis.xadd(
        f"events:{old_id}",
        {
            "type": "task.failed",
            "data": json.dumps(
                {
                    "generation_id": old_id,
                    "task_stream": "tasks:docgen",
                    "event_type": "task.created",
                    "attempts": 1,
                    "error": "transient",
                }
            ),
        },
    )

    response = await client.post(f"/api/v1/tasks/{old_id}/retry")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["generation_id"] != old_id
    assert body["retried_from"] == old_id

    entries = await fake_redis.xrange("tasks:docgen", "-", "+")
    assert len(entries) == 1


async def test_retry_returns_422_when_payload_unrecoverable(
    client: AsyncClient,
    fake_redis: Any,
) -> None:
    """No DLQ entry + no live config blob → 422 with a clear error."""
    old_id = str(uuid4())

    # Only a task.failed event, but the encrypted config has been evicted
    # and there's no DLQ entry to fall back to.
    await fake_redis.xadd(
        f"events:{old_id}",
        {
            "type": "task.failed",
            "data": json.dumps(
                {
                    "generation_id": old_id,
                    "task_stream": "tasks:docgen",
                    "event_type": "task.created",
                    "attempts": 3,
                    "error": "lost",
                }
            ),
        },
    )

    response = await client.post(f"/api/v1/tasks/{old_id}/retry")
    assert response.status_code == 422
    assert "not recoverable" in response.json()["detail"]


async def test_retry_creates_consumer_group(
    client: AsyncClient,
    fake_redis: Any,
    encryption_key: str,
) -> None:
    old_id = str(uuid4())
    await _seed_dlq_failure(fake_redis, encryption_key, old_id)

    await client.post(f"/api/v1/tasks/{old_id}/retry")
    groups = await fake_redis.xinfo_groups("tasks:docgen")
    assert any(g["name"] == "docgen-receivers" for g in groups)
