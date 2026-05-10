"""E2E task creation against real Postgres + Redis.

PMI-mapping: 6.3.4 (Запуск задачи генерации документации). Verifies that
the encrypted config blob in Redis can actually be decrypted with the
key the gateway was given, and that the docgen consumer group is
registered on the real Redis Streams instance.
"""

import json
from typing import Any

import pytest
import redis.asyncio as aioredis
from cryptography.fernet import Fernet
from httpx import AsyncClient


pytestmark = pytest.mark.e2e


def _payload() -> dict:
    return {
        "repo_id": "11111111-2222-3333-4444-555555555555",
        "name": "real run",
        "llm": {
            "provider": "openai-compatible",
            "model": "gpt-4o-mini",
            "api_key": "sk-real-test",
        },
        "embeddings": {
            "provider": "openai",
            "model": "text-embedding-3-small",
            "api_key": "sk-emb-real",
        },
    }


async def test_create_task_persists_encrypted_config_in_real_redis(
    real_client: AsyncClient,
    real_config: Any,
    encryption_key: str,
) -> None:
    response = await real_client.post("/api/v1/tasks", json=_payload())
    assert response.status_code == 200, response.text

    gen_id = response.json()["generation_id"]

    r = aioredis.from_url(real_config.redis.url, decode_responses=True)
    try:
        encrypted = await r.get(f"config:{gen_id}")
    finally:
        await r.aclose()

    assert encrypted is not None
    # Opaque blob — must NOT be valid JSON.
    with pytest.raises(Exception):
        json.loads(encrypted)
    # Round-trips with the gateway's Fernet key.
    cipher = Fernet(encryption_key.encode())
    decoded = json.loads(cipher.decrypt(encrypted.encode()).decode())
    assert decoded["llm"]["api_key"] == "sk-real-test"


async def test_create_task_creates_real_consumer_group(
    real_client: AsyncClient,
    real_config: Any,
) -> None:
    await real_client.post("/api/v1/tasks", json=_payload())

    r = aioredis.from_url(real_config.redis.url, decode_responses=True)
    try:
        groups = await r.xinfo_groups("tasks:docgen")
    finally:
        await r.aclose()

    names = [g["name"] for g in groups]
    assert "docgen-receivers" in names
