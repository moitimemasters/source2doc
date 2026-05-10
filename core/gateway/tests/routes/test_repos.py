"""Gateway /api/v1/repos integration tests.

PMI-mapping: 6.2.2 (Синхронизация репозитория из git URL) and
6.2.3 (Загрузка репозитория архивом).
"""

from __future__ import annotations

import io
import json
import tarfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient


async def test_clone_creates_repo_row_and_publishes_to_repos_stream(
    client: AsyncClient,
    fake_redis: Any,
    fake_storage: MagicMock,
) -> None:
    response = await client.post(
        "/api/v1/repos/clone",
        json={"git_url": "https://github.com/example/demo.git", "branch": "main"},
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert "repo_id" in body
    assert body["name"] == "demo"

    # Postgres row created.
    fake_storage.create_repository.assert_awaited_once()
    kwargs = fake_storage.create_repository.await_args.kwargs
    assert kwargs["source_type"] == "git"
    assert kwargs["git_url"] == "https://github.com/example/demo.git"
    assert kwargs["git_branch"] == "main"

    # Stream entry pushed for the repos worker.
    entries = await fake_redis.xrange("tasks:repos", "-", "+")
    assert len(entries) == 1
    _, fields = entries[0]
    assert fields["type"] == "repo.clone_requested"
    data = json.loads(fields["data"])
    assert data["source_type"] == "git"
    assert data["source_data"]["url"] == "https://github.com/example/demo.git"


async def test_clone_extracts_repo_name_from_url_when_name_omitted(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/repos/clone",
        json={"git_url": "git@github.com:example/another-repo.git"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "another-repo"


async def test_upload_rejects_non_tar_gz_archive(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/repos/upload",
        files={"file": ("payload.zip", b"not a tar", "application/zip")},
        data={"name": "demo"},
    )
    assert response.status_code == 400
    assert "tar.gz" in response.text or "tgz" in response.text


async def test_upload_extracts_archive_and_creates_repo_row(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    # Build an in-memory tar.gz containing one directory with a file.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info_dir = tarfile.TarInfo("myrepo")
        info_dir.type = tarfile.DIRTYPE
        tar.addfile(info_dir)

        payload = b"print('hi')\n"
        info_file = tarfile.TarInfo("myrepo/main.py")
        info_file.size = len(payload)
        tar.addfile(info_file, io.BytesIO(payload))
    buf.seek(0)

    # Replace the S3 dependency so we don't talk to LocalStack.
    from app.routes.bundles.router import get_s3_storage as bundles_get_s3
    from app.routes.repos.router import get_s3_storage

    fake_s3 = MagicMock()
    fake_s3.upload_repository = AsyncMock(return_value="repos/abc.tar.gz")
    fake_s3.repository_exists = AsyncMock(return_value=True)
    fake_s3.delete_repository = AsyncMock(return_value=None)

    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_s3_storage] = lambda: fake_s3
    app.dependency_overrides[bundles_get_s3] = lambda: fake_s3

    response = await client.post(
        "/api/v1/repos/upload",
        files={"file": ("repo.tar.gz", buf.getvalue(), "application/gzip")},
        data={"name": "myrepo", "description": "demo"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["s3_key"] == "repos/abc.tar.gz"
    assert body["name"] == "myrepo"

    fake_s3.upload_repository.assert_awaited_once()
    fake_storage.create_repository.assert_awaited_once()


async def test_repository_exists_endpoint(client: AsyncClient) -> None:
    from app.routes.repos.router import get_s3_storage

    fake_s3 = MagicMock()
    fake_s3.repository_exists = AsyncMock(return_value=True)

    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_s3_storage] = lambda: fake_s3

    response = await client.get("/api/v1/repos/abc-123/exists")
    assert response.status_code == 200
    assert response.json() == {"repo_id": "abc-123", "exists": True}


async def test_get_repository_returns_404_when_missing(
    client: AsyncClient, fake_storage: MagicMock
) -> None:
    fake_storage.get_repository = AsyncMock(return_value=None)
    response = await client.get(
        "/api/v1/repos/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404
