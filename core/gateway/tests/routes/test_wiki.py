"""Gateway /api/v1/wiki integration tests.

Covers:
  * B6.2 / ТЗ ДОК-08 — ``GET /symbols``: cross-page symbol map for
    inline-link rewriting.
  * B13.2 / ТЗ АГТ-06 — ``GET /graph`` and
    ``GET /pages/{page_id}/inbound``: nodes+edges for the link graph
    and the "Referenced by …" panel.

The endpoints are read-only; fakes return canned data straight from
``app.state.storage`` so we exercise routing, DTO shape, and
service-layer wiring without a real Postgres.
"""

from typing import Any
from unittest.mock import AsyncMock

from httpx import AsyncClient

from source2doc.storage.postgres import PageLink


async def test_symbols_endpoint_returns_storage_payload(
    client: AsyncClient,
    fake_storage: Any,
) -> None:
    fake_storage.list_page_symbols = AsyncMock(
        return_value=[
            {"symbol": "DocPage", "page_id": "models", "kind": "class"},
            {"symbol": "Overview", "page_id": "overview", "kind": "page_title"},
        ]
    )

    response = await client.get("/api/v1/wiki/00000000-0000-0000-0000-000000000001/symbols")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "symbols": [
            {"symbol": "DocPage", "page_id": "models", "kind": "class"},
            {"symbol": "Overview", "page_id": "overview", "kind": "page_title"},
        ]
    }


async def test_symbols_endpoint_empty_for_unknown_generation(
    client: AsyncClient,
    fake_storage: Any,
) -> None:
    fake_storage.list_page_symbols = AsyncMock(return_value=[])

    response = await client.get("/api/v1/wiki/00000000-0000-0000-0000-000000000099/symbols")
    assert response.status_code == 200
    assert response.json() == {"symbols": []}


async def test_symbols_endpoint_rejects_invalid_uuid(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/wiki/not-a-uuid/symbols")
    # FastAPI's UUID path-converter rejects with 422 before storage is hit.
    assert response.status_code == 422


# --- B13.2 / ТЗ АГТ-06 — graph endpoint ------------------------------


async def test_graph_endpoint_returns_nodes_and_edges(
    client: AsyncClient,
    fake_storage: Any,
) -> None:
    """``GET /graph`` joins ``get_bundle_pages`` + ``list_page_links``."""
    fake_storage.get_bundle_pages = AsyncMock(
        return_value=[
            {
                "page_id": "overview",
                "title": "Overview",
                "summary": "",
                "status": "completed",
                "error": None,
                "commit_sha": None,
                "created_at": "2026-05-05T12:00:00+00:00",
                "updated_at": "2026-05-05T12:00:00+00:00",
            },
            {
                "page_id": "models",
                "title": "Models",
                "summary": "",
                "status": "completed",
                "error": None,
                "commit_sha": None,
                "created_at": "2026-05-05T12:00:00+00:00",
                "updated_at": "2026-05-05T12:00:00+00:00",
            },
        ]
    )
    fake_storage.list_page_links = AsyncMock(
        return_value=[
            PageLink(from_page_id="overview", to_page_id="models", kind="symbol", weight=3),
        ]
    )

    response = await client.get("/api/v1/wiki/00000000-0000-0000-0000-000000000001/graph")
    assert response.status_code == 200, response.text
    body = response.json()
    assert {n["id"] for n in body["nodes"]} == {"overview", "models"}
    assert body["edges"] == [
        {"from": "overview", "to": "models", "kind": "symbol", "weight": 3},
    ]


async def test_graph_endpoint_empty_for_unknown_generation(
    client: AsyncClient,
    fake_storage: Any,
) -> None:
    fake_storage.get_bundle_pages = AsyncMock(return_value=[])
    fake_storage.list_page_links = AsyncMock(return_value=[])

    response = await client.get("/api/v1/wiki/00000000-0000-0000-0000-000000000099/graph")
    assert response.status_code == 200
    assert response.json() == {"nodes": [], "edges": []}


async def test_graph_endpoint_rejects_invalid_uuid(client: AsyncClient) -> None:
    response = await client.get("/api/v1/wiki/not-a-uuid/graph")
    assert response.status_code == 422


# --- B13.2 — inbound endpoint ----------------------------------------


async def test_inbound_endpoint_joins_titles(
    client: AsyncClient,
    fake_storage: Any,
) -> None:
    """``GET /pages/{id}/inbound`` should attach the source page title."""
    fake_storage.list_inbound_links = AsyncMock(
        return_value=[
            PageLink(from_page_id="overview", to_page_id="models", kind="symbol", weight=2),
            PageLink(from_page_id="ghost", to_page_id="models", kind="symbol", weight=1),
        ]
    )
    fake_storage.get_bundle_pages = AsyncMock(
        return_value=[
            {
                "page_id": "overview",
                "title": "Overview",
                "summary": "",
                "status": "completed",
                "error": None,
                "commit_sha": None,
                "created_at": "2026-05-05T12:00:00+00:00",
                "updated_at": "2026-05-05T12:00:00+00:00",
            },
        ]
    )

    response = await client.get(
        "/api/v1/wiki/00000000-0000-0000-0000-000000000001/pages/models/inbound"
    )
    assert response.status_code == 200, response.text
    inbound = response.json()["inbound"]
    titles = {row["from_page_id"]: row["title"] for row in inbound}
    assert titles == {"overview": "Overview", "ghost": None}


async def test_inbound_endpoint_empty_when_no_edges(
    client: AsyncClient,
    fake_storage: Any,
) -> None:
    """No edges → empty list and we never bother fetching pages."""
    fake_storage.list_inbound_links = AsyncMock(return_value=[])
    fake_storage.get_bundle_pages = AsyncMock(return_value=[])

    response = await client.get(
        "/api/v1/wiki/00000000-0000-0000-0000-000000000001/pages/orphan/inbound"
    )
    assert response.status_code == 200
    assert response.json() == {"inbound": []}
    fake_storage.get_bundle_pages.assert_not_awaited()
