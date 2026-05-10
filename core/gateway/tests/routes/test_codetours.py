"""Gateway /api/v1/codetours integration tests.

PMI-mapping: 6.2.9 (Создание и просмотр CodeTour).

Upstream change: the public CodetourRequest no longer carries LLM
credentials in the body — they're resolved from the configured default
preset. Tests now stub a default preset and verify the gateway pulls its
config from there.
"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from cryptography.fernet import Fernet
from httpx import AsyncClient

from source2doc.security.encryption import ConfigEncryption
from source2doc.storage.presets import Preset


def _payload() -> dict:
    return {
        "generation_id": "00000000-0000-0000-0000-000000000123",
        "query": "How does login work?",
        "max_steps": 5,
        "mode": "overview",
    }


def _make_default_preset(encryption_key: str) -> Preset:
    """Build a Preset whose encrypted_config matches the gateway's key."""
    enc = ConfigEncryption(encryption_key)
    encrypted = enc.encrypt_config(
        {
            "llm": {
                "provider": "openai-compatible",
                "model": "gpt-4o-mini",
                "api_key": "sk-codetour",
            },
            "embeddings": {
                "provider": "openai",
                "model": "text-embedding-3-small",
                "api_key": "sk-emb",
            },
        }
    )
    return Preset(
        id=1,
        name="default",
        is_default=True,
        description="test default",
        encrypted_config=encrypted,
        created_at="2026-05-04T00:00:00+00:00",
        updated_at="2026-05-04T00:00:00+00:00",
    )


async def test_create_codetour_writes_stream_and_pending_row(
    client: AsyncClient,
    app_under_test,
    fake_redis: Any,
    fake_codetour_storage: MagicMock,
    encryption_key: str,
) -> None:
    # Wire a default preset so the resolver finds LLM credentials.
    preset = _make_default_preset(encryption_key)
    app_under_test.state.preset_storage.get_default = AsyncMock(return_value=preset)

    response = await client.post("/api/v1/codetours", json=_payload())
    assert response.status_code == 200, response.text

    body = response.json()
    tour_id = body["tour_id"]
    assert body["status"] == "pending"

    fake_codetour_storage.create_pending_tour.assert_awaited_once()

    entries = await fake_redis.xrange("tasks:codetour", "-", "+")
    assert len(entries) == 1
    _, fields = entries[0]
    assert fields["type"] == "codetour.requested"
    data = json.loads(fields["data"])
    assert data["tour_id"] == tour_id
    assert data["query"] == "How does login work?"

    # Encrypted config in Redis must carry the preset's LLM credentials.
    config_key = data["config_key"]
    stored = await fake_redis.get(config_key)
    assert stored is not None
    cipher = Fernet(encryption_key.encode())
    decoded = json.loads(cipher.decrypt(stored.encode()).decode())
    assert decoded["llm"]["api_key"] == "sk-codetour"


async def test_create_codetour_returns_503_when_no_preset_configured(
    client: AsyncClient,
) -> None:
    """Without a default preset and no admin override, the public
    /codetours endpoint must refuse the request — there's no LLM to use."""
    response = await client.post("/api/v1/codetours", json=_payload())
    assert response.status_code == 503


async def test_get_codetour_404_for_unknown_tour(
    client: AsyncClient,
    fake_codetour_storage: MagicMock,
) -> None:
    response = await client.get(
        "/api/v1/codetours/00000000-0000-0000-0000-00000000ffff"
    )
    assert response.status_code == 404
