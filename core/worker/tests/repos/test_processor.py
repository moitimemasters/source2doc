"""repos worker tests.

PMI-mapping: 6.2.2 (Синхронизация репозитория из git URL) and 6.2.3
(Загрузка репозитория архивом). The Redis -> Postgres -> S3 round-trip
runs against real services in PMI; here we cover the dispatch and the
archive-extraction path with mocks for S3 and Postgres.
"""

from pathlib import Path
import tarfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from worker.repos.processor import (
    _process_archive_repository,
    process_repository_upload,
)


def _make_env():  # type: ignore[no-untyped-def]
    """Duck-typed RepoWorkerEnv stub — only the fields the processor reads."""
    s3 = SimpleNamespace(upload_repository=AsyncMock(return_value="repos/x.tar.gz"))
    pg = SimpleNamespace(update_repository=AsyncMock(return_value=None))
    return SimpleNamespace(s3_storage=s3, pg_storage=pg)


async def test_process_repository_upload_routes_unknown_source_to_error() -> None:
    env = _make_env()
    with pytest.raises(ValueError, match="Unsupported source type"):
        await process_repository_upload(
            env,
            {"repo_id": "abc", "source_type": "ftp", "source_data": {}},
        )


async def test_process_archive_extracts_and_uploads(tmp_path: Path) -> None:
    # Build a tar.gz containing a single top-level dir with a file.
    src_dir = tmp_path / "myrepo"
    src_dir.mkdir()
    (src_dir / "README.md").write_text("hello", encoding="utf-8")

    archive_path = tmp_path / "repo.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(src_dir, arcname="myrepo")

    env = _make_env()
    await _process_archive_repository(
        env, "repo-id-1", {"path": str(archive_path)}
    )

    env.s3_storage.upload_repository.assert_awaited_once()
    call_args = env.s3_storage.upload_repository.await_args
    assert call_args.args[0] == "repo-id-1"
    # The uploaded path must point at the extracted directory, not the tarball.
    uploaded_path = Path(call_args.args[1])
    assert uploaded_path.name == "myrepo"


async def test_process_archive_rejects_archive_without_directory(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "empty.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        # Only a top-level FILE, no directory.
        f = tmp_path / "loose.txt"
        f.write_text("x", encoding="utf-8")
        tar.add(f, arcname="loose.txt")

    env = _make_env()
    with pytest.raises(ValueError, match="at least one directory"):
        await _process_archive_repository(
            env, "repo-id-2", {"path": str(archive_path)}
        )


async def test_process_repository_upload_dispatches_to_archive_branch(
    tmp_path: Path,
) -> None:
    # Build a minimal archive.
    src_dir = tmp_path / "myrepo"
    src_dir.mkdir()
    (src_dir / "x.py").write_text("pass", encoding="utf-8")

    archive_path = tmp_path / "repo.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(src_dir, arcname="myrepo")

    env = _make_env()

    # Upstream change: processor now calls UUID(repo_id) when persisting
    # the s3_key back to Postgres. Pass a real UUID instead of "abc".
    await process_repository_upload(
        env,
        {
            "repo_id": "11111111-2222-3333-4444-555555555555",
            "source_type": "archive",
            "source_data": {"path": str(archive_path)},
        },
    )
    env.s3_storage.upload_repository.assert_awaited_once()
    env.pg_storage.update_repository.assert_awaited_once()
