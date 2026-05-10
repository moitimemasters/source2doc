"""Gateway POST /api/v1/tasks integration test.

PMI-mapping: 6.2.4 (Запуск задачи генерации документации). Verifies that
a POST creates a Redis Stream task entry with an opaque (Fernet-encrypted)
``config_key`` and that the response contains the SSE URLs the UI relies
on.
"""

import json
from typing import Any

from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import AsyncClient


def _task_payload() -> dict[str, Any]:
    return {
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
        "generation": {},
    }


async def test_create_task_writes_encrypted_config_to_redis(
    client: AsyncClient,
    fake_redis: Any,
    encryption_key: str,
) -> None:
    response = await client.post("/api/v1/tasks", json=_task_payload())
    assert response.status_code == 200, response.text

    body = response.json()
    assert "generation_id" in body
    assert body["status"] == "pending"
    assert body["stream_url"].endswith("/stream")
    assert body["events_url"].endswith("/events")

    # 1. Redis-stored config exists at the documented key and is opaque.
    config_key = f"config:{body['generation_id']}"
    stored = await fake_redis.get(config_key)
    assert stored is not None
    with pytest.raises(Exception):  # noqa: PT011 — assert opacity, not exact type
        json.loads(stored)

    # 2. It round-trips through the Fernet key the gateway was given.
    cipher = Fernet(encryption_key.encode())
    decrypted = json.loads(cipher.decrypt(stored.encode()).decode())
    assert decrypted["repo_id"] == "11111111-2222-3333-4444-555555555555"
    assert decrypted["llm"]["api_key"] == "sk-test-llm"


async def test_create_task_publishes_to_docgen_stream(
    client: AsyncClient,
    fake_redis: Any,
) -> None:
    response = await client.post("/api/v1/tasks", json=_task_payload())
    assert response.status_code == 200

    entries = await fake_redis.xrange("tasks:docgen", "-", "+")
    assert len(entries) == 1

    _, fields = entries[0]
    assert fields["type"] == "task.created"
    payload = json.loads(fields["data"])
    assert payload["generation_id"] == response.json()["generation_id"]
    assert payload["config_key"] == f"config:{payload['generation_id']}"


async def test_create_task_returns_trace_id_and_stamps_stream(
    client: AsyncClient,
    fake_redis: Any,
) -> None:
    """B3.3 — every accepted task must produce a stable per-task trace_id.

    Verifies (a) the response carries it back to the client and (b) the
    same value is stamped onto the Redis-stream payload so downstream
    workers re-bind it on contextvars before any handler runs.
    """
    response = await client.post("/api/v1/tasks", json=_task_payload())
    assert response.status_code == 200

    body = response.json()
    trace_id = body.get("trace_id")
    assert isinstance(trace_id, str) and len(trace_id) == 32, (
        f"Expected 32-char hex trace_id, got {trace_id!r}"
    )
    # uuid4().hex is lowercase hex with no dashes
    assert all(c in "0123456789abcdef" for c in trace_id)

    entries = await fake_redis.xrange("tasks:docgen", "-", "+")
    assert len(entries) == 1
    _, fields = entries[0]
    payload = json.loads(fields["data"])
    assert payload["trace_id"] == trace_id, (
        "stream payload must carry the same trace_id the response returned"
    )


async def test_consumer_group_is_created(
    client: AsyncClient,
    fake_redis: Any,
) -> None:
    await client.post("/api/v1/tasks", json=_task_payload())
    groups = await fake_redis.xinfo_groups("tasks:docgen")
    assert any(g["name"] == "docgen-receivers" for g in groups)


async def test_create_task_rejects_invalid_payload(client: AsyncClient) -> None:
    # repo_id is the only required field on TaskRequest; everything else
    # (llm/embeddings/qdrant) is now optional and resolved from a preset.
    response = await client.post("/api/v1/tasks", json={})
    assert response.status_code == 422


# pytest is imported lazily so the conftest fixture autoinit happens first.
import pytest  # noqa: E402
