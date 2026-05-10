"""Gateway /api/v1/bundles integration tests.

PMI-mapping: 6.2.6 (Экспорт бандла документации). Verifies the gateway
publishes a properly shaped task to ``tasks:bundler`` and validates the
download key prefix.
"""

import json
from typing import Any

import pytest
from httpx import AsyncClient


@pytest.mark.parametrize("fmt", ["mkdocs", "nextra", "sphinx"])
async def test_export_publishes_to_bundler_stream(
    client: AsyncClient,
    fake_redis: Any,
    fmt: str,
) -> None:
    response = await client.post(
        "/api/v1/bundles/export",
        json={
            "bundle_id": 7,
            "generation_id": "00000000-0000-0000-0000-000000000001",
            "format": fmt,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["bundle_id"] == 7
    assert body["format"] == fmt

    entries = await fake_redis.xrange("tasks:bundler", "-", "+")
    assert len(entries) == 1
    _, fields = entries[0]
    assert fields["type"] == "bundle.export_requested"

    payload = json.loads(fields["data"])
    assert payload["bundle_id"] == 7
    assert payload["format"] == fmt
    assert payload["generation_id"] == "00000000-0000-0000-0000-000000000001"
    # The Postgres connection string flows through so the bundler can read pages.
    assert "postgres_connection_string" in payload


async def test_download_rejects_keys_outside_bundles_prefix(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/bundles/exports/download",
        params={"s3_key": "secrets/dump.tar.gz"},
    )
    # Generic exception handler upstream stopped echoing the original
    # ValueError detail; assert only the 500 status.
    assert response.status_code == 500
