import dataclasses as dc
import json
from pathlib import Path
import re
import tarfile
import tempfile
import uuid
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile
import redis.asyncio as aioredis
import structlog

from source2doc.storage import PostgresStorage, S3Storage


def _set_logfire_trace_attribute(trace_id: str) -> None:
    """Best-effort tag the active logfire span with our trace_id."""
    try:
        import logfire

        logfire.current_span().set_attribute("trace_id", trace_id)
    except Exception:  # noqa: BLE001
        pass


@dc.dataclass
class UploadResult:
    repo_id: str
    name: str
    s3_key: str


@dc.dataclass
class CloneResult:
    repo_id: str
    name: str


def _extract_repo_name_from_url(git_url: str) -> str:
    match = re.search(r"/([^/]+?)(?:\.git)?$", git_url)
    if match:
        return match.group(1)
    return "unknown-repo"


async def upload_repository_archive(
    file: UploadFile,
    name: str,
    s3: S3Storage,
    storage: PostgresStorage,
    description: str | None = None,
) -> UploadResult:
    if not file.filename or not file.filename.endswith((".tar.gz", ".tgz")):
        raise HTTPException(
            status_code=400,
            detail="File must be a .tar.gz or .tgz archive",
        )

    repo_id = uuid4()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / file.filename

        content = await file.read()
        archive_path.write_bytes(content)

        extract_path = temp_path / "extracted"
        extract_path.mkdir()

        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(extract_path)

        extracted_dirs = [d for d in extract_path.iterdir() if d.is_dir()]
        if not extracted_dirs:
            raise HTTPException(
                status_code=400,
                detail="Archive must contain at least one directory",
            )

        repo_path = extracted_dirs[0]
        s3_key = await s3.upload_repository(str(repo_id), repo_path)

    await storage.create_repository(
        repo_id=repo_id,
        name=name,
        source_type="upload",
        s3_key=s3_key,
        description=description,
    )

    return UploadResult(
        repo_id=str(repo_id),
        name=name,
        s3_key=s3_key,
    )


async def list_repositories(storage: PostgresStorage) -> list:
    return await storage.list_repositories()


async def get_repository(repo_id: str, storage: PostgresStorage):
    repo = await storage.get_repository(UUID(repo_id))
    if not repo:
        raise HTTPException(
            status_code=404,
            detail=f"Repository not found: {repo_id}",
        )
    return repo


async def check_repository_exists(repo_id: str, s3: S3Storage) -> bool:
    return await s3.repository_exists(repo_id)


async def delete_repository(
    repo_id: str,
    s3: S3Storage,
    storage: PostgresStorage,
) -> None:
    # Existence in Postgres is the source of truth — a stale row whose S3
    # archive was lost (e.g. localstack volume reset between sessions) must
    # still be deletable so the admin UI can clean it up. Treat S3 as
    # best-effort: try to remove the archive, swallow "not found", surface
    # other errors. Then drop the Postgres row, 404ing only when the row
    # is also missing.
    try:
        if await s3.repository_exists(repo_id):
            await s3.delete_repository(repo_id)
    except Exception:  # noqa: BLE001 — defensive: don't block DB cleanup on S3 failure
        pass
    deleted = await storage.delete_repository(UUID(repo_id))
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Repository not found: {repo_id}",
        )


REPOS_STREAM = "tasks:repos"
REPOS_CONSUMER_GROUP = "repos-workers"


async def create_clone_task(
    git_url: str,
    branch: str | None,
    redis: aioredis.Redis,
    storage: PostgresStorage,
    name: str | None = None,
    description: str | None = None,
    repo_id: str | None = None,
    commit_sha: str | None = None,
    replace_existing: bool = False,
) -> CloneResult:
    # ``replace_existing`` only makes sense when the caller supplies an
    # explicit ``repo_id`` — otherwise the gateway mints a fresh UUID,
    # nothing to replace, and a brand-new repository row gets created
    # silently. Fail loudly so the UX matches the user's intent.
    if replace_existing and not repo_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "``replace_existing=true`` requires an explicit ``repo_id`` "
                "(the UUID of the existing repository to refresh). Without "
                "it the gateway would mint a fresh UUID and your replace "
                "would silently create a duplicate repo."
            ),
        )

    repo_uuid = _resolve_clone_repo_id(repo_id)
    existing = await storage.get_repository(repo_uuid)
    if existing is not None and not replace_existing:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Repository with repo_id {repo_uuid} already exists. "
                "Pass ``replace_existing=true`` to overwrite the tarball "
                "with a fresh clone (useful for refreshing to a newer commit)."
            ),
        )
    repo_name = name or _extract_repo_name_from_url(git_url)
    trace_id = uuid.uuid4().hex

    structlog.contextvars.bind_contextvars(
        trace_id=trace_id,
        repo_id=str(repo_uuid),
    )
    _set_logfire_trace_attribute(trace_id)

    try:
        if existing is None:
            await storage.create_repository(
                repo_id=repo_uuid,
                name=repo_name,
                source_type="git",
                git_url=git_url,
                git_branch=branch,
                description=description,
            )
        else:
            # Refresh path: keep the existing row but bump the metadata so
            # the UI / iterative classifier see the new branch / git_url.
            # ``commit_sha`` lands in the row only after the worker
            # finishes the new clone (it writes ``commit_sha`` itself
            # alongside ``s3_key``).
            await storage.update_repository_metadata(
                repo_id=repo_uuid,
                name=repo_name,
                git_url=git_url,
                git_branch=branch,
                description=description,
            )

        task_info = {
            "repo_id": str(repo_uuid),
            "trace_id": trace_id,
            "name": repo_name,
            "source_type": "git",
            "source_data": {
                "url": git_url,
                "branch": branch,
                "commit_sha": commit_sha,
            },
            "replace_existing": replace_existing,
        }

        await _ensure_consumer_group(redis, REPOS_STREAM, REPOS_CONSUMER_GROUP)

        await redis.xadd(
            REPOS_STREAM,
            {
                "type": "repo.clone_requested",
                "data": json.dumps(task_info),
            },
        )

        return CloneResult(
            repo_id=str(repo_uuid),
            name=repo_name,
        )
    finally:
        structlog.contextvars.clear_contextvars()


def _resolve_clone_repo_id(supplied: str | None) -> UUID:
    if supplied is None:
        return uuid4()
    try:
        return UUID(supplied)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"repo_id must be a valid UUID, got: {supplied}",
        )


async def _ensure_consumer_group(
    redis: aioredis.Redis,
    stream_name: str,
    group_name: str,
) -> None:
    try:
        await redis.xgroup_create(
            name=stream_name,
            groupname=group_name,
            id="0",
            mkstream=True,
        )
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise
