from fastapi import APIRouter, Depends, File, Form, UploadFile
import redis.asyncio as aioredis

from source2doc.storage import PostgresStorage, S3Storage

from app.config import Config, get_config
from app.routes.docs.dependencies import get_storage
from app.routes.repos import service
from app.routes.repos.dto import (
    RepositoryCloneRequest,
    RepositoryCloneResponse,
    RepositoryDeleteResponse,
    RepositoryDetailResponse,
    RepositoryExistsResponse,
    RepositoryInfo,
    RepositoryListResponse,
    RepositoryUploadResponse,
)
from app.routes.streams.dependencies import get_redis
from app.security.admin import require_admin


router = APIRouter(prefix="/api/v1/repos", tags=["repositories"])
admin_required = Depends(require_admin)


def get_s3_storage(config: Config = Depends(get_config)) -> S3Storage:
    return S3Storage(config.s3)


@router.post("/upload", response_model=RepositoryUploadResponse, dependencies=[admin_required])
async def upload_repository(
    file: UploadFile = File(...),
    name: str = Form(..., description="Human-readable repository name"),
    description: str | None = Form(None, description="Repository description"),
    s3: S3Storage = Depends(get_s3_storage),
    storage: PostgresStorage = Depends(get_storage),
) -> RepositoryUploadResponse:
    result = await service.upload_repository_archive(
        file,
        name,
        s3,
        storage,
        description,
    )

    return RepositoryUploadResponse(
        repo_id=result.repo_id,
        name=result.name,
        s3_key=result.s3_key,
        message="Repository uploaded successfully",
    )


@router.post("/clone", response_model=RepositoryCloneResponse, dependencies=[admin_required])
async def clone_repository(
    request: RepositoryCloneRequest,
    redis: aioredis.Redis = Depends(get_redis),
    storage: PostgresStorage = Depends(get_storage),
) -> RepositoryCloneResponse:
    result = await service.create_clone_task(
        request.git_url,
        request.branch,
        redis,
        storage,
        request.name,
        request.description,
        request.repo_id,
        commit_sha=request.commit_sha,
        replace_existing=request.replace_existing,
    )

    return RepositoryCloneResponse(
        repo_id=result.repo_id,
        name=result.name,
        message=f"Clone task created for {request.git_url}",
    )


@router.get("", response_model=RepositoryListResponse)
async def list_repositories_route(
    storage: PostgresStorage = Depends(get_storage),
) -> RepositoryListResponse:
    repositories = await service.list_repositories(storage)
    return RepositoryListResponse(
        repositories=[
            RepositoryInfo(
                repo_id=str(repo.repo_id),
                name=repo.name,
                source_type=repo.source_type,
                git_url=repo.git_url,
                git_branch=repo.git_branch,
                s3_key=repo.s3_key,
                description=repo.description,
                created_at=repo.created_at,
                updated_at=repo.updated_at,
            )
            for repo in repositories
        ],
        count=len(repositories),
    )


@router.get("/{repo_id}", response_model=RepositoryDetailResponse)
async def get_repository_route(
    repo_id: str,
    storage: PostgresStorage = Depends(get_storage),
) -> RepositoryDetailResponse:
    repo = await service.get_repository(repo_id, storage)
    return RepositoryDetailResponse(
        repo_id=str(repo.repo_id),
        name=repo.name,
        source_type=repo.source_type,
        git_url=repo.git_url,
        git_branch=repo.git_branch,
        s3_key=repo.s3_key,
        description=repo.description,
        updated_at=repo.updated_at,
    )


@router.get("/{repo_id}/exists", response_model=RepositoryExistsResponse)
async def check_repository_exists_route(
    repo_id: str,
    s3: S3Storage = Depends(get_s3_storage),
) -> RepositoryExistsResponse:
    exists = await service.check_repository_exists(repo_id, s3)
    return RepositoryExistsResponse(
        repo_id=repo_id,
        exists=exists,
    )


@router.delete("/{repo_id}", response_model=RepositoryDeleteResponse, dependencies=[admin_required])
async def delete_repository_route(
    repo_id: str,
    s3: S3Storage = Depends(get_s3_storage),
    storage: PostgresStorage = Depends(get_storage),
) -> RepositoryDeleteResponse:
    await service.delete_repository(repo_id, s3, storage)

    return RepositoryDeleteResponse(
        repo_id=repo_id,
        message="Repository deleted successfully",
    )
