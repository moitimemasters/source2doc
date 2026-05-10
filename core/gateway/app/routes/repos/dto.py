from pydantic import BaseModel, Field


class RepositoryUploadRequest(BaseModel):
    name: str = Field(..., description="Human-readable repository name")
    description: str | None = Field(None, description="Repository description")


class RepositoryUploadResponse(BaseModel):
    repo_id: str
    name: str
    s3_key: str
    message: str


class RepositoryCloneRequest(BaseModel):
    git_url: str = Field(..., description="Git repository URL")
    branch: str | None = Field(
        default=None,
        description="Branch to clone. If omitted, the repository's default branch is used.",
    )
    commit_sha: str | None = Field(
        default=None,
        description=(
            "Optional commit SHA / tag / ref. After the initial clone the worker "
            "runs ``git checkout <commit_sha>`` so the tarball captures the repo "
            "at that specific revision. Useful for iterative-mode demos where "
            "you want a base bundle at an older commit, then refresh the same "
            "``repo_id`` at HEAD via ``replace_existing`` and run incremental."
        ),
    )
    name: str | None = Field(
        None, description="Human-readable repository name (defaults to repo name from URL)"
    )
    description: str | None = Field(None, description="Repository description")
    channel: str = Field(default="repos:new", description="PubSub channel for custom workers")
    repo_id: str | None = Field(
        default=None,
        description=(
            "Optional UUID to use as repo_id. Must be a valid UUIDv4. If omitted, "
            "the gateway generates a fresh UUID. When ``replace_existing`` is "
            "false and a repo with this UUID already exists, returns 409."
        ),
    )
    replace_existing: bool = Field(
        default=False,
        description=(
            "When true, an existing repository with the supplied ``repo_id`` is "
            "re-cloned in place — the tarball is overwritten with whatever "
            "``branch`` / ``commit_sha`` resolves to, and the DB row's metadata "
            "is updated. Lets a caller refresh a repo to a newer commit without "
            "minting a fresh ``repo_id`` (which would break iterative-mode "
            "lineage chains)."
        ),
    )


class RepositoryCloneResponse(BaseModel):
    repo_id: str
    name: str
    message: str


class RepositoryInfo(BaseModel):
    repo_id: str
    name: str
    source_type: str
    git_url: str | None = None
    git_branch: str | None = None
    s3_key: str | None = None
    description: str | None = None
    created_at: str
    updated_at: str


class RepositoryListResponse(BaseModel):
    repositories: list[RepositoryInfo]
    count: int


class RepositoryExistsResponse(BaseModel):
    repo_id: str
    exists: bool


class RepositoryDeleteResponse(BaseModel):
    repo_id: str
    message: str


class RepositoryDetailResponse(BaseModel):
    repo_id: str
    name: str
    source_type: str
    git_url: str | None = None
    git_branch: str | None = None
    s3_key: str | None = None
    description: str | None = None
    updated_at: str
