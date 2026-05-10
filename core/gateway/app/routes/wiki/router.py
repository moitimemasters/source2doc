"""Wiki-side endpoints — cross-page links, link graph, and other read-only helpers.

* ``GET /api/v1/wiki/{gen}/symbols`` (B6.2 / ТЗ ДОК-08) — symbol map for
  in-page link rewriting.
* ``GET /api/v1/wiki/{gen}/graph`` (B13.2 / ТЗ АГТ-06) — full nodes+edges
  graph for a generation.
* ``GET /api/v1/wiki/{gen}/pages/{page_id}/inbound`` (B13.2) —
  "Referenced by …" list for a single page.
"""

from uuid import UUID

from fastapi import APIRouter, Depends

from source2doc.storage import PostgresStorage

from app.routes.docs import service as docs_service
from app.routes.docs.dependencies import get_storage
from app.routes.docs.dto import (
    InboundLink,
    InboundLinksResponse,
    PageGraphEdge,
    PageGraphNode,
    PageGraphResponse,
    PageSymbol,
    PageSymbolsResponse,
)


router = APIRouter(prefix="/api/v1/wiki", tags=["wiki"])


@router.get("/{generation_id}/symbols", response_model=PageSymbolsResponse)
async def list_symbols_route(
    generation_id: UUID,
    storage: PostgresStorage = Depends(get_storage),
) -> PageSymbolsResponse:
    rows = await docs_service.list_page_symbols(storage, generation_id)
    return PageSymbolsResponse(symbols=[PageSymbol(**row) for row in rows])


@router.get("/{generation_id}/graph", response_model=PageGraphResponse)
async def get_graph_route(
    generation_id: UUID,
    storage: PostgresStorage = Depends(get_storage),
) -> PageGraphResponse:
    """B13.2 / ТЗ АГТ-06 — return ``{nodes, edges}`` for the wiki graph."""
    graph = await docs_service.get_page_graph(storage, generation_id)
    return PageGraphResponse(
        nodes=[PageGraphNode(**node) for node in graph["nodes"]],
        edges=[PageGraphEdge(**edge) for edge in graph["edges"]],
    )


@router.get(
    "/{generation_id}/pages/{page_id}/inbound",
    response_model=InboundLinksResponse,
)
async def list_inbound_route(
    generation_id: UUID,
    page_id: str,
    storage: PostgresStorage = Depends(get_storage),
) -> InboundLinksResponse:
    """B13.2 — list pages that reference ``page_id`` ("Referenced by …")."""
    rows = await docs_service.list_inbound_links(storage, generation_id, page_id)
    return InboundLinksResponse(inbound=[InboundLink(**row) for row in rows])
