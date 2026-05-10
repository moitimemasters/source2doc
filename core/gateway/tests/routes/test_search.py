"""Gateway /api/v1/projects/{repository_id}/search integration tests.

PMI-mapping: ПСК-01..04, ПСК-06 (Осокин) and СКВ-04 — project-level
semantic + fulltext search over Qdrant collections.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from httpx import AsyncClient
import pytest


REPO_UUID = "11111111-1111-4111-8111-111111111111"
GENERATION_UUID = "22222222-2222-4222-8222-222222222222"


def _fake_repo(repo_id: str = REPO_UUID) -> Any:
    """Minimal RepositoryInfo-shaped object — service only checks identity."""

    return SimpleNamespace(
        repo_id=UUID(repo_id),
        name="demo",
        source_type="git",
        git_url="https://example.com/demo.git",
        git_branch="main",
        s3_key=None,
        description=None,
        created_at="2026-05-05T00:00:00",
        updated_at="2026-05-05T00:00:00",
        metadata={},
        commit_sha=None,
    )


def _fake_qdrant_point(
    *,
    chunk_id: str,
    file_path: str,
    content: str,
    language: str = "python",
    score: float = 0.9,
    start_line: int = 1,
    end_line: int = 10,
) -> Any:
    """Build a fake Qdrant point that matches both ``query_points`` and ``scroll`` shapes."""

    return SimpleNamespace(
        id=1,
        score=score,
        payload={
            "chunk_id": chunk_id,
            "file_path": file_path,
            "content": content,
            "language": language,
            "start_line": start_line,
            "end_line": end_line,
        },
    )


class _FakeQdrantClient:
    """Fake AsyncQdrantClient capturing the kwargs passed to query_points/scroll."""

    def __init__(self, *, points: list[Any] | None = None) -> None:
        self.points = points or []
        self.last_query_kwargs: dict[str, Any] = {}
        self.last_scroll_kwargs: dict[str, Any] = {}
        self.create_payload_index = AsyncMock(return_value=None)
        self.closed = False

    async def query_points(self, **kwargs: Any) -> Any:
        self.last_query_kwargs = kwargs
        return SimpleNamespace(points=self.points)

    async def scroll(self, **kwargs: Any) -> Any:
        self.last_scroll_kwargs = kwargs
        return (self.points, None)

    async def close(self) -> None:
        self.closed = True


def _patch_search_dependencies(
    app: Any,
    *,
    qdrant_client: _FakeQdrantClient,
    embedding: list[float] | None = None,
) -> None:
    """Replace the search service factories so tests don't hit OpenAI / Qdrant."""

    from app.routes.search import service as search_service

    async def _fake_factory(_qdrant_config: Any) -> _FakeQdrantClient:
        return qdrant_client

    async def _fake_embed(_config: Any, _text: str) -> list[float]:
        return embedding or [0.1, 0.2, 0.3]

    # Module-level factories are read by name inside ``search_project``, so a
    # plain monkeypatch via attribute assignment is enough — the route hands
    # them in as default arguments and we override here.
    search_service._default_qdrant_client_factory = _fake_factory  # type: ignore[assignment]
    search_service._default_embed_text = _fake_embed  # type: ignore[assignment]


@pytest.fixture
def fake_qdrant_client() -> _FakeQdrantClient:
    return _FakeQdrantClient(
        points=[
            _fake_qdrant_point(
                chunk_id="abc123",
                file_path="src/foo.py",
                content="def hello(): return 'world'",
                score=0.78,
                start_line=42,
                end_line=67,
            ),
            _fake_qdrant_point(
                chunk_id="def456",
                file_path="src/bar.py",
                content="def goodbye(): pass",
                score=0.55,
            ),
        ]
    )


@pytest.fixture
def configured_app(
    client: AsyncClient,
    app_under_test: Any,
    fake_storage: MagicMock,
    fake_qdrant_client: _FakeQdrantClient,
    encryption_key: str,
) -> Any:
    """App pre-loaded with: a known repo, one bundle/generation, default preset
    that yields embeddings + qdrant config.

    Depends on ``client`` so the lifespan_context has already executed and
    ``app.state.encryption`` / ``preset_storage`` are wired up.
    """
    from source2doc.security.encryption import ConfigEncryption

    fake_storage.get_repository = AsyncMock(return_value=_fake_repo())
    fake_storage.list_bundle_generation_ids_for_repo = AsyncMock(return_value=[GENERATION_UUID])

    # Default preset returns embeddings + qdrant config so semantic mode is
    # available end-to-end. We build a real ConfigEncryption with the same
    # key used by the conftest stub_lifespan so encrypt/decrypt roundtrip.
    encryption = ConfigEncryption(encryption_key)
    preset_payload = {
        "embeddings": {
            "provider": "openai",
            "model": "text-embedding-3-small",
            "api_key": "sk-test",
            "base_url": "https://api.example.com/v1",
        },
        "qdrant": {
            "url": "http://qdrant.example:6333",
            "collection": "ignored",
            "api_key": None,
        },
    }
    encrypted = encryption.encrypt_config(preset_payload)
    app_under_test.state.preset_storage.get_default = AsyncMock(
        return_value=SimpleNamespace(encrypted_config=encrypted)
    )
    app_under_test.state.preset_storage.get_by_name = AsyncMock(return_value=None)

    _patch_search_dependencies(app_under_test, qdrant_client=fake_qdrant_client)
    return app_under_test


async def test_semantic_happy_path_returns_qdrant_hits(
    configured_app: Any,
    client: AsyncClient,
    fake_qdrant_client: _FakeQdrantClient,
) -> None:
    response = await client.post(
        f"/api/v1/projects/{REPO_UUID}/search",
        json={"query": "hello world", "mode": "semantic", "limit": 5},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["mode"] == "semantic"
    assert body["total"] == 2
    assert len(body["results"]) == 2

    first = body["results"][0]
    assert first["text"] == "def hello(): return 'world'"
    assert first["score"] == pytest.approx(0.78)
    assert first["source"]["file_path"] == "src/foo.py"
    assert first["source"]["start_line"] == 42
    assert first["source"]["end_line"] == 67
    assert first["source"]["language"] == "python"
    assert first["metadata"]["repository_id"] == REPO_UUID
    assert first["metadata"]["chunk_id"] == "abc123"

    # Qdrant collection name is derived from the bundle's generation_id.
    assert fake_qdrant_client.last_query_kwargs["collection_name"] == f"docgen_{GENERATION_UUID}"
    # The embeddings client was called and its vector forwarded.
    assert fake_qdrant_client.last_query_kwargs["query"] == [0.1, 0.2, 0.3]
    assert fake_qdrant_client.last_query_kwargs["limit"] == 5


async def test_fulltext_happy_path_uses_match_text_filter(
    configured_app: Any,
    client: AsyncClient,
    fake_qdrant_client: _FakeQdrantClient,
) -> None:
    response = await client.post(
        f"/api/v1/projects/{REPO_UUID}/search",
        json={"query": "hello", "mode": "fulltext", "limit": 10},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["mode"] == "fulltext"
    assert body["total"] == 2
    # Rank-based score: first hit gets 1.0, decays linearly.
    assert body["results"][0]["score"] == pytest.approx(1.0)
    assert body["results"][1]["score"] == pytest.approx(0.5)

    # scroll() received a Filter that matches content text against the query.
    scroll_filter = fake_qdrant_client.last_scroll_kwargs["scroll_filter"]
    must_conditions = scroll_filter.must
    content_conds = [c for c in must_conditions if c.key == "content"]
    assert len(content_conds) == 1
    assert content_conds[0].match.text == "hello"

    # Text-index ensure was attempted (idempotent).
    fake_qdrant_client.create_payload_index.assert_awaited_once()


async def test_returns_404_when_repository_unknown(
    app_under_test: Any,
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    fake_storage.get_repository = AsyncMock(return_value=None)
    fake_storage.get_bundle_repository = AsyncMock(return_value=None)
    response = await client.post(
        f"/api/v1/projects/{uuid4()}/search",
        json={"query": "foo"},
    )
    assert response.status_code == 404
    assert "not found" in response.text.lower()


async def test_returns_422_when_repository_id_not_uuid(
    app_under_test: Any,
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/projects/not-a-uuid/search",
        json={"query": "foo"},
    )
    assert response.status_code == 422


async def test_returns_empty_when_repo_has_no_indexed_generations(
    app_under_test: Any,
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    fake_storage.get_repository = AsyncMock(return_value=_fake_repo())
    fake_storage.list_bundle_generation_ids_for_repo = AsyncMock(return_value=[])

    response = await client.post(
        f"/api/v1/projects/{REPO_UUID}/search",
        json={"query": "foo", "mode": "fulltext"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["results"] == []


async def test_semantic_without_default_preset_returns_503(
    app_under_test: Any,
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    fake_storage.get_repository = AsyncMock(return_value=_fake_repo())
    fake_storage.list_bundle_generation_ids_for_repo = AsyncMock(return_value=[GENERATION_UUID])
    # No default preset → semantic mode has no embeddings config.
    app_under_test.state.preset_storage.get_default = AsyncMock(return_value=None)

    response = await client.post(
        f"/api/v1/projects/{REPO_UUID}/search",
        json={"query": "foo", "mode": "semantic"},
    )
    assert response.status_code == 503
    assert "embeddings" in response.text.lower()


async def test_filters_propagate_to_qdrant(
    configured_app: Any,
    client: AsyncClient,
    fake_qdrant_client: _FakeQdrantClient,
) -> None:
    response = await client.post(
        f"/api/v1/projects/{REPO_UUID}/search",
        json={
            "query": "hello",
            "mode": "semantic",
            "filters": {
                "file_path": "src/foo.py",
                "directory": "src/",
                "language": "python",
            },
        },
    )
    assert response.status_code == 200, response.text

    qfilter = fake_qdrant_client.last_query_kwargs["query_filter"]
    must = qfilter.must
    keys_matched = {(c.key, type(c.match).__name__) for c in must}

    # file_path exact match + language exact match + directory MatchText.
    assert ("file_path", "MatchValue") in keys_matched
    assert ("file_path", "MatchText") in keys_matched
    assert ("language", "MatchValue") in keys_matched

    # And the actual values are what we sent.
    by_key_kind = {(c.key, type(c.match).__name__): c.match for c in must}
    assert by_key_kind[("file_path", "MatchValue")].value == "src/foo.py"
    assert by_key_kind[("file_path", "MatchText")].text == "src/"
    assert by_key_kind[("language", "MatchValue")].value == "python"


async def test_invalid_body_rejected_by_pydantic(
    app_under_test: Any,
    client: AsyncClient,
) -> None:
    response = await client.post(
        f"/api/v1/projects/{REPO_UUID}/search",
        json={"query": "", "mode": "semantic"},
    )
    assert response.status_code == 422


async def test_qdrant_failure_returns_503(
    configured_app: Any,
    client: AsyncClient,
    fake_qdrant_client: _FakeQdrantClient,
) -> None:
    async def boom(**_kwargs: Any) -> Any:
        raise RuntimeError("qdrant connection refused")

    fake_qdrant_client.query_points = boom  # type: ignore[assignment]

    response = await client.post(
        f"/api/v1/projects/{REPO_UUID}/search",
        json={"query": "hi", "mode": "semantic"},
    )
    assert response.status_code == 503
    assert "vector store" in response.text.lower()
