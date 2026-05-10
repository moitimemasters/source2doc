from __future__ import annotations

import dataclasses as dc
import datetime as dt
from decimal import Decimal
import json
import types
import typing as tp
from uuid import UUID

import asyncpg

from source2doc.logging import get_logger
from source2doc.models import docs as doc_models
from source2doc.storage.base import DocIndex, StorageBackend


logger = get_logger(__name__)


@dc.dataclass
class GenerationMetric:
    """One token-usage / cost / timing row recorded by a docgen agent handler.

    Mirrors the ``generation_metrics`` table schema 1:1. ``cost_usd`` is
    nullable because the pricing map may not cover every model — a missing
    entry means we still persist the token counts but skip the cost
    calculation. The ``step_started_at`` / ``step_completed_at`` /
    ``duration_ms`` triplet (added in migration 14) is also nullable for
    rows written by older handlers that didn't capture timings.
    """

    id: int
    generation_id: UUID
    step: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: Decimal | None
    created_at: str
    step_started_at: str | None = None
    step_completed_at: str | None = None
    duration_ms: int | None = None
    trace_id: str | None = None
    extras: dict[str, tp.Any] = dc.field(default_factory=dict)


@dc.dataclass
class MetricsBucket:
    """One row of the metrics-aggregate dashboard query (B3.4).

    ``key`` carries the bucket label (``"2026-05-05"`` for ``group_by=day``,
    a model name, or a step name). ``runs`` counts ``generation_metrics``
    rows in the bucket — i.e., agent invocations, not distinct generations.
    """

    key: str
    tokens: int
    cost_usd: Decimal | None
    duration_ms_p50: int | None
    duration_ms_p95: int | None
    runs: int


@dc.dataclass
class RepositoryInfo:
    repo_id: UUID
    name: str
    source_type: str
    git_url: str | None
    git_branch: str | None
    s3_key: str | None
    description: str | None
    created_at: str
    updated_at: str
    metadata: dict[str, tp.Any]
    commit_sha: str | None = None


@dc.dataclass
class BundleInfo:
    id: int
    generation_id: str
    name: str | None
    project_name: str | None
    description: str | None
    repo_id: str | None
    created_at: str
    updated_at: str
    metadata: dict[str, tp.Any]
    pages_count: int
    repository: RepositoryInfo | None = None


@dc.dataclass
class PageVersionMeta:
    """One row of the page-version dropdown query (B11.2 / ТЗ ГЕН-08).

    Carries only the small fields the wiki UI needs to render an entry in
    the "Versions ▾" popover: the snapshot's ``generation_id`` (used as
    the lookup key for the detail fetch), the ``commit_sha`` recorded at
    write time (rendered as a 7-char short SHA next to the date), and
    ``created_at`` for sorting + the human-readable label.
    """

    generation_id: UUID
    commit_sha: str | None
    created_at: str


@dc.dataclass
class PageVersionDetail:
    """Full payload for one historical page snapshot.

    Mirrors the columns of ``page_versions`` 1:1. ``body`` is the same
    ``{"blocks": [...], "related": [...]}`` shape that
    ``documentation_pages.content`` carries — keeping the two formats
    identical lets the UI re-use ``ContentRenderer`` to render an old
    version exactly as it would have rendered when current.
    """

    page_id: str
    generation_id: UUID
    repository_id: UUID | None
    commit_sha: str | None
    body: dict[str, tp.Any]
    body_markdown: str | None
    metadata: dict[str, tp.Any] | None
    created_at: str


@dc.dataclass
class FileHashEntry:
    """One ``repo_file_hashes`` row written after an incremental ingest run.

    Mirrors the table from migration 15 1:1. ``chunks_count`` is the number
    of Qdrant points we created for the file in this generation — stored
    purely for observability (e.g. dashboards and incremental-skip stats).
    """

    file_path: str
    content_sha256: str
    chunks_count: int


@dc.dataclass
class PageLinkEntry:
    """Single directed edge to insert into ``page_links`` (B13.2).

    Used by ``record_page_links`` for bulk upserts. ``kind`` mirrors the
    column comment: ``'symbol'`` (resolved via ``page_symbols``),
    ``'mention'`` (string match), ``'inferred'`` (heuristic).
    """

    from_page_id: str
    to_page_id: str
    kind: str
    weight: int = 1


@dc.dataclass
class PageLink:
    """One row from ``page_links`` returned by graph queries (B13.2)."""

    from_page_id: str
    to_page_id: str
    kind: str
    weight: int


@dc.dataclass
class AgentRunRecord:
    """One row of the per-generation ``agent_runs`` history (migration 20).

    Mirrors the table 1:1. ``messages`` carries the full ``ModelMessage``
    list dump (system + user + tool calls + tool results + final assistant
    message) so the UI can replay the conversation. ``output`` is the
    structured agent return value (``AgentRunResult.output``); ``None``
    when the run failed before producing one.
    """

    id: int
    generation_id: UUID
    page_id: str | None
    section_id: str | None
    agent_name: str
    attempt: int
    started_at: str
    finished_at: str | None
    duration_ms: int | None
    success: bool
    error_type: str | None
    error_message: str | None
    request_count: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost_usd: Decimal | None
    messages: tp.Any
    output: tp.Any
    trace_id: str | None


class PostgresStorage(StorageBackend):
    def __init__(
        self,
        connection_string: str,
        pool_min_size: int = 2,
        pool_max_size: int = 10,
    ) -> None:
        self.connection_string = connection_string
        self.pool_min_size = pool_min_size
        self.pool_max_size = pool_max_size
        self.pool: asyncpg.Pool | None = None

    async def __aenter__(self) -> PostgresStorage:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException],
        exc_val: BaseException,
        exc_tb: types.TracebackType,
    ) -> None:
        await self.close()

    async def connect(self) -> None:
        logger.info(
            "connecting_to_postgres",
            pool_min_size=self.pool_min_size,
            pool_max_size=self.pool_max_size,
        )
        self.pool = await asyncpg.create_pool(
            self.connection_string,
            min_size=self.pool_min_size,
            max_size=self.pool_max_size,
        )
        logger.info("postgres_connected")

    async def close(self) -> None:
        if self.pool:
            logger.info("closing_postgres_connection")
            await self.pool.close()
            logger.info("postgres_closed")

    async def create_bundle(
        self,
        generation_id: UUID,
        project_name: str | None = None,
        name: str | None = None,
        description: str | None = None,
        repo_id: UUID | None = None,
        parent_generation_id: UUID | None = None,
        generation_mode: str = "full",
    ) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO documentation_bundles (
                    generation_id, project_name, name, description, repo_id,
                    parent_generation_id, generation_mode
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (generation_id) DO UPDATE
                SET project_name = COALESCE(EXCLUDED.project_name, documentation_bundles.project_name),
                    name = COALESCE(EXCLUDED.name, documentation_bundles.name),
                    description = COALESCE(EXCLUDED.description, documentation_bundles.description),
                    repo_id = COALESCE(EXCLUDED.repo_id, documentation_bundles.repo_id),
                    parent_generation_id = COALESCE(EXCLUDED.parent_generation_id, documentation_bundles.parent_generation_id),
                    generation_mode = EXCLUDED.generation_mode,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                generation_id,
                project_name,
                name,
                description,
                repo_id,
                parent_generation_id,
                generation_mode,
            )
            bundle_id = row["id"]
            logger.info(
                "bundle_created",
                bundle_id=bundle_id,
                generation_id=str(generation_id),
                parent_generation_id=str(parent_generation_id) if parent_generation_id else None,
                generation_mode=generation_mode,
            )
            return bundle_id

    async def write_index(self, bundle_id: int, index: doc_models.DocIndex) -> None:
        async with self.pool.acquire() as conn:
            generated_at = index.generated_at
            if isinstance(generated_at, str):
                generated_at = dt.datetime.fromisoformat(generated_at.replace("Z", "+00:00"))

            await conn.execute(
                """
                INSERT INTO documentation_index (bundle_id, version, generated_at, navigation)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (bundle_id) DO UPDATE
                SET version = EXCLUDED.version,
                    generated_at = EXCLUDED.generated_at,
                    navigation = EXCLUDED.navigation
                """,
                bundle_id,
                index.version,
                generated_at,
                json.dumps(index.navigation),
            )
            logger.info("index_written", bundle_id=bundle_id)

    async def write_page(
        self,
        bundle_id: int,
        page_id: str,
        page: doc_models.DocPage,
        commit_sha: str | None = None,
        source_files: list[str] | None = None,
    ) -> None:
        async with self.pool.acquire() as conn:
            content_dict = {
                "blocks": [block.model_dump() for block in page.blocks],
                "related": page.related,
            }
            metadata_dict = page.metadata.model_dump()

            if commit_sha is None:
                # Not necessarily a bug — archive uploads have no `.git` dir,
                # and old bundles backfilled before B11.1 won't have one
                # either — but it does mean the UI cannot deep-link the page
                # to a revision, which is worth a debug breadcrumb.
                logger.debug(
                    "page_written_without_commit_sha",
                    bundle_id=bundle_id,
                    page_id=page_id,
                )

            await conn.execute(
                """
                INSERT INTO documentation_pages (
                    bundle_id, page_id, title, summary, content, metadata,
                    status, error, commit_sha, source_files
                )
                VALUES ($1, $2, $3, $4, $5, $6, 'completed', NULL, $7, $8)
                ON CONFLICT (bundle_id, page_id) DO UPDATE
                SET title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    content = EXCLUDED.content,
                    metadata = EXCLUDED.metadata,
                    status = 'completed',
                    error = NULL,
                    commit_sha = EXCLUDED.commit_sha,
                    source_files = EXCLUDED.source_files,
                    updated_at = CURRENT_TIMESTAMP
                """,
                bundle_id,
                page_id,
                page.title,
                page.summary,
                json.dumps(content_dict),
                json.dumps(metadata_dict),
                commit_sha,
                list(source_files) if source_files else None,
            )
            logger.info(
                "page_written",
                bundle_id=bundle_id,
                page_id=page_id,
                commit_sha=commit_sha[:8] if commit_sha else None,
            )

    async def mark_page_failed(
        self,
        bundle_id: int,
        page_id: str,
        error: str,
        title: str = "",
    ) -> None:
        """Persist a placeholder row marking the page as ``failed``.

        Stores the agent error so the UI can render a helpful message
        instead of empty content. Idempotent: re-running over a previous
        failure or retry just updates the row.
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO documentation_pages (
                    bundle_id, page_id, title, summary, content, metadata, status, error
                )
                VALUES ($1, $2, $3, $4, $5::jsonb, '{}'::jsonb, 'failed', $6)
                ON CONFLICT (bundle_id, page_id) DO UPDATE
                SET status = 'failed',
                    error = EXCLUDED.error,
                    updated_at = CURRENT_TIMESTAMP
                """,
                bundle_id,
                page_id,
                title or page_id,
                f"Page generation failed: {error}",
                json.dumps({"blocks": [], "related": []}),
                error,
            )
            logger.warning(
                "page_marked_failed",
                bundle_id=bundle_id,
                page_id=page_id,
                error=error,
            )

    async def replace_placeholder(
        self,
        generation_id: UUID,
        page_id: str,
        placeholder_id: str,
        new_block: dict,
    ) -> bool:
        """Replace a ``mermaid_placeholder`` block in a page's content.

        Walks the stored ``content.blocks`` jsonb, recursing into nested
        ``CutBlock.blocks``. Idempotent: if no placeholder with that id is
        present the call is a no-op and returns ``False``. Otherwise returns
        ``True`` after writing the patched content.

        Done inside a transaction with ``SELECT ... FOR UPDATE`` so two
        concurrent diagram handlers can't lose each other's writes on the
        same page.
        """

        def _replace_in_list(items: list[dict]) -> bool:
            replaced = False
            for index, block in enumerate(items):
                if not isinstance(block, dict):
                    continue
                if (
                    block.get("type") == "mermaid_placeholder"
                    and block.get("placeholder_id") == placeholder_id
                ):
                    items[index] = new_block
                    replaced = True
                    return replaced
                if block.get("type") == "cut":
                    nested = block.get("blocks") or []
                    if _replace_in_list(nested):
                        block["blocks"] = nested
                        return True
            return replaced

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT dp.id, dp.content
                    FROM documentation_pages dp
                    JOIN documentation_bundles db ON dp.bundle_id = db.id
                    WHERE db.generation_id = $1 AND dp.page_id = $2
                    FOR UPDATE OF dp
                    """,
                    generation_id,
                    page_id,
                )
                if row is None:
                    return False

                content = row["content"]
                if isinstance(content, str):
                    content = json.loads(content)

                blocks = content.get("blocks") or []
                if not _replace_in_list(blocks):
                    return False
                content["blocks"] = blocks

                await conn.execute(
                    """
                    UPDATE documentation_pages
                    SET content = $1::jsonb,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = $2
                    """,
                    json.dumps(content),
                    row["id"],
                )
                logger.info(
                    "placeholder_replaced",
                    page_id=page_id,
                    placeholder_id=placeholder_id,
                    new_type=new_block.get("type"),
                )
                return True

    async def get_index(self, generation_id: UUID) -> DocIndex | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT di.version, di.generated_at, di.navigation
                FROM documentation_index di
                JOIN documentation_bundles db ON di.bundle_id = db.id
                WHERE db.generation_id = $1
                """,
                generation_id,
            )

            if not row:
                return None

            navigation = row["navigation"]
            if isinstance(navigation, str):
                navigation = json.loads(navigation)

            return DocIndex(
                version=row["version"],
                generated_at=row["generated_at"],
                navigation=navigation,
            )

    async def get_page(
        self,
        generation_id: UUID,
        page_id: str,
    ) -> doc_models.DocPage | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT dp.title, dp.summary, dp.content, dp.metadata, dp.commit_sha,
                       dp.created_at, dp.updated_at
                FROM documentation_pages dp
                JOIN documentation_bundles db ON dp.bundle_id = db.id
                WHERE db.generation_id = $1 AND dp.page_id = $2
                """,
                generation_id,
                page_id,
            )

            if not row:
                return None

            content = (
                json.loads(row["content"]) if isinstance(row["content"], str) else row["content"]
            )
            metadata = (
                json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
            )

            # The dedicated `commit_sha` column is the source of truth — older
            # bundles may not have it embedded in the JSON metadata blob, and
            # newer writes only persist it on the column to avoid two
            # divergent copies. Surface it through PageMetadata so the API
            # layer doesn't need to special-case it.
            metadata["commit_sha"] = row["commit_sha"]

            # B6.3 / ТЗ ДОК-09: surface the row's ``updated_at`` (preferred
            # — reflects the most recent rewrite) on PageMetadata.generated_at
            # so the wiki viewer can show "Generated <date>" without an extra
            # round-trip. We overwrite any pre-existing JSON value because the
            # DB column is the canonical source of truth (the JSON copy is
            # best-effort and not maintained on update).
            updated_at = row["updated_at"]
            if updated_at is not None:
                metadata["generated_at"] = updated_at.isoformat()

            return doc_models.DocPage(
                title=row["title"],
                summary=row["summary"],
                metadata=doc_models.PageMetadata(**metadata),
                blocks=content.get("blocks", []),
                related=content.get("related", []),
            )

    async def get_dominant_model(self, generation_id: UUID) -> str | None:
        """Return the most-frequent ``model`` across ``generation_metrics`` rows.

        Closes ТЗ ДОК-09 (B6.3 in the implementation tracker): the wiki
        viewer renders this as a small badge so readers can see which LLM
        wrote the page they're looking at. Ties are broken by the SQL
        engine's secondary ordering on ``model`` for determinism.
        Returns ``None`` when no rows exist (legacy bundles from before
        B3.1 / migration 10).
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT model, COUNT(*) AS uses
                FROM generation_metrics
                WHERE generation_id = $1
                GROUP BY model
                ORDER BY uses DESC, model ASC
                LIMIT 1
                """,
                generation_id,
            )
            if row is None:
                return None
            return row["model"]

    async def list_bundles(self, limit: int = 100, offset: int = 0) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    db.id,
                    db.generation_id,
                    db.project_name,
                    db.name,
                    db.description,
                    db.repo_id,
                    db.created_at,
                    db.updated_at,
                    db.metadata,
                    (
                        SELECT COUNT(*)
                        FROM documentation_pages
                        WHERE bundle_id = db.id
                    ) as pages_count,
                    (
                        SELECT COUNT(*)
                        FROM documentation_pages
                        WHERE bundle_id = db.id AND status = 'failed'
                    ) as failed_pages_count,
                    r.name as repo_name,
                    r.source_type as repo_source_type,
                    r.git_url as repo_git_url,
                    r.git_branch as repo_git_branch,
                    r.commit_sha as repo_commit_sha
                FROM documentation_bundles db
                LEFT JOIN repositories r ON db.repo_id = r.repo_id
                ORDER BY db.created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )

            return [
                {
                    "id": row["id"],
                    "generation_id": str(row["generation_id"]),
                    "project_name": row["project_name"],
                    "name": row["name"],
                    "description": row["description"],
                    "repo_id": str(row["repo_id"]) if row["repo_id"] else None,
                    "created_at": row["created_at"].isoformat(),
                    "updated_at": row["updated_at"].isoformat(),
                    "metadata": json.loads(row["metadata"])
                    if isinstance(row["metadata"], str)
                    else row["metadata"],
                    "pages_count": row["pages_count"],
                    "failed_pages_count": row["failed_pages_count"],
                    "repository": {
                        "name": row["repo_name"],
                        "source_type": row["repo_source_type"],
                        "git_url": row["repo_git_url"],
                        "git_branch": row["repo_git_branch"],
                        "commit_sha": row["repo_commit_sha"],
                    }
                    if row["repo_name"]
                    else None,
                }
                for row in rows
            ]

    async def get_bundle_repository(self, generation_id: UUID) -> RepositoryInfo | None:
        """Fetch the source repository for a bundle, joined via ``repo_id``.

        Returns ``None`` if either the bundle is unknown or it has no
        attached repository (e.g. legacy generations from before the
        ``repositories`` table was introduced in 04_add_repositories_metadata).
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    r.repo_id, r.name, r.source_type, r.git_url, r.git_branch,
                    r.s3_key, r.description, r.created_at, r.updated_at,
                    r.metadata, r.commit_sha
                FROM documentation_bundles db
                JOIN repositories r ON db.repo_id = r.repo_id
                WHERE db.generation_id = $1
                """,
                generation_id,
            )

            if not row:
                return None

            metadata = row["metadata"]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)

            return RepositoryInfo(
                repo_id=row["repo_id"],
                name=row["name"],
                source_type=row["source_type"],
                git_url=row["git_url"],
                git_branch=row["git_branch"],
                s3_key=row["s3_key"],
                description=row["description"],
                created_at=row["created_at"].isoformat(),
                updated_at=row["updated_at"].isoformat(),
                metadata=metadata,
                commit_sha=row["commit_sha"],
            )

    async def get_bundle(self, generation_id: UUID) -> dict | None:
        """Look up a single bundle by generation_id, with the same shape /
        repo enrichment as ``list_bundles`` returns. Used by the task-status
        endpoint to surface bundle metadata alongside Redis-derived state."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    db.id,
                    db.generation_id,
                    db.project_name,
                    db.name,
                    db.description,
                    db.repo_id,
                    db.created_at,
                    db.updated_at,
                    db.metadata,
                    r.name as repo_name,
                    r.source_type as repo_source_type,
                    r.git_url as repo_git_url,
                    r.git_branch as repo_git_branch
                FROM documentation_bundles db
                LEFT JOIN repositories r ON db.repo_id = r.repo_id
                WHERE db.generation_id = $1
                """,
                generation_id,
            )
            if not row:
                return None
            return {
                "id": row["id"],
                "generation_id": str(row["generation_id"]),
                "project_name": row["project_name"],
                "name": row["name"],
                "description": row["description"],
                "repo_id": str(row["repo_id"]) if row["repo_id"] else None,
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat(),
                "metadata": json.loads(row["metadata"])
                if isinstance(row["metadata"], str)
                else row["metadata"],
                "repo_name": row["repo_name"],
                "repo_source_type": row["repo_source_type"],
                "repo_git_url": row["repo_git_url"],
                "repo_git_branch": row["repo_git_branch"],
            }

    async def get_bundle_pages(self, generation_id: UUID) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    dp.page_id, dp.title, dp.summary, dp.status, dp.error,
                    dp.commit_sha, dp.created_at, dp.updated_at
                FROM documentation_pages dp
                JOIN documentation_bundles db ON dp.bundle_id = db.id
                WHERE db.generation_id = $1
                ORDER BY dp.created_at
                """,
                generation_id,
            )

            return [
                {
                    "page_id": row["page_id"],
                    "title": row["title"],
                    "summary": row["summary"],
                    "status": row["status"],
                    "error": row["error"],
                    "commit_sha": row["commit_sha"],
                    "created_at": row["created_at"].isoformat(),
                    "updated_at": row["updated_at"].isoformat(),
                }
                for row in rows
            ]

    async def get_bundle_pages_full(self, generation_id: UUID) -> list[dict]:
        """Full per-page records used by the iterative-mode classifier.

        Differs from ``get_bundle_pages`` (which is the wiki-list shape) in
        that it returns the persisted ``content`` jsonb, ``metadata``
        jsonb, ``source_files`` array and ``deprecated`` flag. The classifier
        needs ``source_files`` to bucket pages into direct/dead/unchanged;
        the rewriter needs ``content`` + ``metadata`` to seed update-mode.
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    dp.page_id, dp.title, dp.summary,
                    dp.content, dp.metadata, dp.commit_sha,
                    dp.source_files, dp.deprecated,
                    dp.status, dp.error,
                    db.id AS bundle_id
                FROM documentation_pages dp
                JOIN documentation_bundles db ON dp.bundle_id = db.id
                WHERE db.generation_id = $1
                ORDER BY dp.created_at
                """,
                generation_id,
            )
            out: list[dict] = []
            for row in rows:
                content = row["content"]
                if isinstance(content, str):
                    content = json.loads(content)
                metadata = row["metadata"]
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
                out.append(
                    {
                        "page_id": row["page_id"],
                        "title": row["title"],
                        "summary": row["summary"],
                        "content": content or {},
                        "metadata": metadata or {},
                        "commit_sha": row["commit_sha"],
                        "source_files": list(row["source_files"] or []),
                        "deprecated": bool(row["deprecated"]),
                        "status": row["status"],
                        "error": row["error"],
                        "bundle_id": row["bundle_id"],
                    }
                )
            return out

    async def copy_pages_to_bundle(
        self,
        *,
        src_generation_id: UUID,
        dst_bundle_id: int,
        page_ids: list[str] | None = None,
        new_commit_sha: str | None = None,
        mark_deprecated: bool = False,
    ) -> int:
        """Clone pages from a base generation's bundle into ``dst_bundle_id``.

        Used by iterative-mode to carry forward pages whose source files
        weren't touched. ``page_ids=None`` copies every page; passing an
        explicit list scopes the copy.

        ``new_commit_sha`` overrides the source row's ``commit_sha`` (the
        new bundle is "as of HEAD" so all carried-forward pages get
        retagged to the new commit). ``mark_deprecated=True`` sets the
        ``deprecated`` flag on the cloned rows — used for pages whose
        source files were entirely deleted between runs.

        Idempotent on ``(bundle_id, page_id)`` via the existing unique
        constraint: re-running just refreshes the row.
        """

        if page_ids is not None and not page_ids:
            return 0

        async with self.pool.acquire() as conn:
            if page_ids is None:
                rows = await conn.fetch(
                    """
                    INSERT INTO documentation_pages (
                        bundle_id, page_id, title, summary, content, metadata,
                        status, error, commit_sha, source_files, deprecated
                    )
                    SELECT
                        $1::int,
                        dp.page_id, dp.title, dp.summary, dp.content, dp.metadata,
                        dp.status, dp.error,
                        COALESCE($3, dp.commit_sha),
                        dp.source_files,
                        $4 OR dp.deprecated
                    FROM documentation_pages dp
                    JOIN documentation_bundles db ON dp.bundle_id = db.id
                    WHERE db.generation_id = $2
                    ON CONFLICT (bundle_id, page_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        summary = EXCLUDED.summary,
                        content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata,
                        status = EXCLUDED.status,
                        error = EXCLUDED.error,
                        commit_sha = EXCLUDED.commit_sha,
                        source_files = EXCLUDED.source_files,
                        deprecated = EXCLUDED.deprecated,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING page_id
                    """,
                    dst_bundle_id,
                    src_generation_id,
                    new_commit_sha,
                    mark_deprecated,
                )
            else:
                rows = await conn.fetch(
                    """
                    INSERT INTO documentation_pages (
                        bundle_id, page_id, title, summary, content, metadata,
                        status, error, commit_sha, source_files, deprecated
                    )
                    SELECT
                        $1::int,
                        dp.page_id, dp.title, dp.summary, dp.content, dp.metadata,
                        dp.status, dp.error,
                        COALESCE($3, dp.commit_sha),
                        dp.source_files,
                        $4 OR dp.deprecated
                    FROM documentation_pages dp
                    JOIN documentation_bundles db ON dp.bundle_id = db.id
                    WHERE db.generation_id = $2 AND dp.page_id = ANY($5)
                    ON CONFLICT (bundle_id, page_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        summary = EXCLUDED.summary,
                        content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata,
                        status = EXCLUDED.status,
                        error = EXCLUDED.error,
                        commit_sha = EXCLUDED.commit_sha,
                        source_files = EXCLUDED.source_files,
                        deprecated = EXCLUDED.deprecated,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING page_id
                    """,
                    dst_bundle_id,
                    src_generation_id,
                    new_commit_sha,
                    mark_deprecated,
                    page_ids,
                )
            copied = len(rows)
            logger.info(
                "pages_copied_to_bundle",
                src_generation_id=str(src_generation_id),
                dst_bundle_id=dst_bundle_id,
                copied=copied,
                mark_deprecated=mark_deprecated,
            )
            return copied

    async def get_page_links_for_generation(
        self, generation_id: UUID
    ) -> list[tuple[str, str, str, int]]:
        """Return ``(from_page_id, to_page_id, kind, weight)`` rows from
        ``page_links`` for the given generation. Iterative mode uses this
        to expand "direct" pages by 1 hop into transitive impact.
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT from_page_id, to_page_id, kind, weight
                FROM page_links
                WHERE generation_id = $1
                """,
                generation_id,
            )
            return [
                (row["from_page_id"], row["to_page_id"], row["kind"], row["weight"])
                for row in rows
            ]

    async def latest_bundle_for_repo(self, repo_id: UUID) -> dict | None:
        """Return the most recently created bundle row for ``repo_id``.

        Iterative mode falls back to this when the caller doesn't specify
        ``base_generation_id`` explicitly. Returns ``None`` for repos with
        no bundles yet (caller should error out — incremental requires a
        base).
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, generation_id, parent_generation_id, generation_mode,
                       created_at
                FROM documentation_bundles
                WHERE repo_id = $1
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                repo_id,
            )
            if row is None:
                return None
            return {
                "id": row["id"],
                "generation_id": str(row["generation_id"]),
                "parent_generation_id": str(row["parent_generation_id"])
                if row["parent_generation_id"]
                else None,
                "generation_mode": row["generation_mode"],
                "created_at": row["created_at"].isoformat(),
            }

    async def create_task(
        self,
        generation_id: UUID,
        repo_id: str,
        config_key: str,
        qdrant_collection: str,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO generation_tasks (
                    generation_id, repo_id, config_key, qdrant_collection, status, name, description
                )
                VALUES ($1, $2, $3, $4, 'pending', $5, $6)
                ON CONFLICT (generation_id) DO NOTHING
                """,
                generation_id,
                repo_id,
                config_key,
                qdrant_collection,
                name,
                description,
            )

    async def start_task(self, generation_id: UUID, worker_id: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE generation_tasks
                SET status = 'running', worker_id = $1, started_at = $2, last_heartbeat = $2
                WHERE generation_id = $3
                """,
                worker_id,
                dt.datetime.utcnow(),
                generation_id,
            )

    async def update_task_heartbeat(self, generation_id: UUID) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE generation_tasks
                SET last_heartbeat = $1
                WHERE generation_id = $2
                """,
                dt.datetime.now(dt.UTC),
                generation_id,
            )

    async def complete_task(self, generation_id: UUID) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE generation_tasks
                SET status = 'completed', completed_at = $1
                WHERE generation_id = $2
                """,
                dt.datetime.now(dt.UTC),
                generation_id,
            )

    async def fail_task(self, generation_id: UUID, error: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE generation_tasks
                SET status = 'failed', completed_at = $1, error_message = $2
                WHERE generation_id = $3
                """,
                dt.datetime.now(dt.UTC),
                error,
                generation_id,
            )

    async def recover_timeout_tasks(self, timeout_seconds: int) -> list[dict]:
        async with self.pool.acquire() as conn:
            timeout_threshold = dt.datetime.utcnow() - dt.timedelta(seconds=timeout_seconds)

            await conn.execute(
                """
                UPDATE generation_tasks
                SET status = 'timeout', completed_at = $1
                WHERE status = 'running' AND last_heartbeat < $2
                """,
                dt.datetime.now(dt.UTC),
                timeout_threshold,
            )

            rows = await conn.fetch(
                """
                SELECT generation_id, repo_id, config_key, qdrant_collection, retry_count
                FROM generation_tasks
                WHERE status = 'timeout' AND retry_count < 3
                ORDER BY created_at ASC
                """,
            )

            recovered = []
            for row in rows:
                await conn.execute(
                    """
                    UPDATE generation_tasks
                    SET status = 'pending', worker_id = NULL, retry_count = retry_count + 1
                    WHERE generation_id = $1
                    """,
                    row["generation_id"],
                )

                recovered.append(
                    {
                        "generation_id": row["generation_id"],
                        "repo_id": row["repo_id"],
                        "config_key": row["config_key"],
                        "qdrant_collection": row["qdrant_collection"],
                        "retry_count": row["retry_count"],
                    }
                )

            return recovered

    async def recover_stale_tasks(self, stale_threshold_seconds: int = 60) -> list[dict]:
        async with self.pool.acquire() as conn:
            stale_threshold = dt.datetime.utcnow() - dt.timedelta(seconds=stale_threshold_seconds)

            rows = await conn.fetch(
                """
                SELECT generation_id, repo_id, config_key, qdrant_collection, retry_count,
                       last_completed_step
                FROM generation_tasks
                WHERE status = 'running'
                  AND last_heartbeat < $1
                  AND retry_count < 3
                ORDER BY created_at ASC
                """,
                stale_threshold,
            )

            recovered = []
            for row in rows:
                await conn.execute(
                    """
                    UPDATE generation_tasks
                    SET status = 'pending', worker_id = NULL, retry_count = retry_count + 1
                    WHERE generation_id = $1
                    """,
                    row["generation_id"],
                )

                recovered.append(
                    {
                        "generation_id": row["generation_id"],
                        "repo_id": row["repo_id"],
                        "config_key": row["config_key"],
                        "qdrant_collection": row["qdrant_collection"],
                        "retry_count": row["retry_count"] + 1,
                        "last_completed_step": row["last_completed_step"],
                        "resume": True,
                    }
                )

            return recovered

    async def claim_pending_tasks(self, worker_id: str, limit: int = 1) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                UPDATE generation_tasks
                SET status = 'running', worker_id = $1, started_at = $2, last_heartbeat = $2
                WHERE generation_id IN (
                    SELECT generation_id
                    FROM generation_tasks
                    WHERE status = 'pending'
                    ORDER BY created_at ASC
                    LIMIT $3
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING generation_id, repo_id, config_key, qdrant_collection, retry_count,
                          last_completed_step
                """,
                worker_id,
                dt.datetime.now(dt.UTC),
                limit,
            )

            return [
                {
                    "generation_id": row["generation_id"],
                    "repo_id": row["repo_id"],
                    "config_key": row["config_key"],
                    "qdrant_collection": row["qdrant_collection"],
                    "retry_count": row["retry_count"],
                    "last_completed_step": row["last_completed_step"],
                    "resume": row["last_completed_step"] is not None,
                }
                for row in rows
            ]

    async def upsert_step(
        self,
        generation_id: UUID,
        step_name: str,
        status: str,
        attempt_number: int = 1,
        max_attempts: int = 3,
        error_message: str | None = None,
        error_type: str | None = None,
        error_is_transient: bool = False,
        step_data: dict | None = None,
    ) -> int:
        now = dt.datetime.now(dt.UTC)
        started_at = now if status == "running" else None
        completed_at = now if status in ("completed", "failed", "skipped") else None

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO generation_steps (
                    generation_id, step_name, status, started_at, completed_at,
                    error_message, error_type, error_is_transient,
                    attempt_number, max_attempts, step_data
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (generation_id, step_name) DO UPDATE
                SET status = EXCLUDED.status,
                    started_at = COALESCE(EXCLUDED.started_at, generation_steps.started_at),
                    completed_at = EXCLUDED.completed_at,
                    error_message = EXCLUDED.error_message,
                    error_type = EXCLUDED.error_type,
                    error_is_transient = EXCLUDED.error_is_transient,
                    attempt_number = EXCLUDED.attempt_number,
                    step_data = EXCLUDED.step_data
                RETURNING id
                """,
                generation_id,
                step_name,
                status,
                started_at,
                completed_at,
                error_message,
                error_type,
                error_is_transient,
                attempt_number,
                max_attempts,
                json.dumps(step_data or {}),
            )
            return row["id"]

    async def complete_step(
        self,
        generation_id: UUID,
        step_name: str,
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE generation_steps
                SET status = 'completed', completed_at = $1
                WHERE generation_id = $2 AND step_name = $3
                """,
                dt.datetime.now(dt.UTC),
                generation_id,
                step_name,
            )
            await conn.execute(
                """
                UPDATE generation_tasks
                SET last_completed_step = $1
                WHERE generation_id = $2
                """,
                step_name,
                generation_id,
            )

    async def fail_step(
        self,
        generation_id: UUID,
        step_name: str,
        error_message: str,
        error_type: str,
        error_is_transient: bool = False,
        attempt_number: int = 1,
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE generation_steps
                SET status = 'failed',
                    completed_at = $1,
                    error_message = $2,
                    error_type = $3,
                    error_is_transient = $4,
                    attempt_number = $5
                WHERE generation_id = $6 AND step_name = $7
                """,
                dt.datetime.now(dt.UTC),
                error_message,
                error_type,
                error_is_transient,
                attempt_number,
                generation_id,
                step_name,
            )

    async def get_steps(self, generation_id: UUID) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    step_name, status, started_at, completed_at,
                    error_message, error_type, error_is_transient,
                    attempt_number, max_attempts, step_data
                FROM generation_steps
                WHERE generation_id = $1
                ORDER BY created_at ASC
                """,
                generation_id,
            )

            return [
                {
                    "step_name": row["step_name"],
                    "status": row["status"],
                    "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                    "completed_at": row["completed_at"].isoformat()
                    if row["completed_at"]
                    else None,
                    "error_message": row["error_message"],
                    "error_type": row["error_type"],
                    "error_is_transient": row["error_is_transient"],
                    "attempt_number": row["attempt_number"],
                    "max_attempts": row["max_attempts"],
                    "step_data": json.loads(row["step_data"])
                    if isinstance(row["step_data"], str)
                    else row["step_data"],
                }
                for row in rows
            ]

    async def get_last_completed_step(self, generation_id: UUID) -> str | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT last_completed_step
                FROM generation_tasks
                WHERE generation_id = $1
                """,
                generation_id,
            )
            if row:
                return row["last_completed_step"]
            return None

    async def get_task_with_steps(self, generation_id: UUID) -> dict | None:
        async with self.pool.acquire() as conn:
            task_row = await conn.fetchrow(
                """
                SELECT
                    gt.generation_id, gt.worker_id, gt.status, gt.repo_id,
                    gt.started_at, gt.completed_at, gt.error_message,
                    gt.retry_count, gt.last_completed_step, gt.created_at, gt.updated_at,
                    gt.name, gt.description,
                    r.name as repo_name,
                    r.source_type as repo_source_type,
                    r.git_url as repo_git_url,
                    r.git_branch as repo_git_branch
                FROM generation_tasks gt
                LEFT JOIN repositories r ON gt.repo_id::uuid = r.repo_id
                WHERE gt.generation_id = $1
                """,
                generation_id,
            )

            if not task_row:
                return None

            steps = await self.get_steps(generation_id)

            return {
                "generation_id": str(task_row["generation_id"]),
                "worker_id": task_row["worker_id"],
                "status": task_row["status"],
                "repo_id": task_row["repo_id"],
                "name": task_row["name"],
                "description": task_row["description"],
                "started_at": task_row["started_at"].isoformat()
                if task_row["started_at"]
                else None,
                "completed_at": (
                    task_row["completed_at"].isoformat() if task_row["completed_at"] else None
                ),
                "error_message": task_row["error_message"],
                "retry_count": task_row["retry_count"],
                "last_completed_step": task_row["last_completed_step"],
                "created_at": task_row["created_at"].isoformat(),
                "updated_at": task_row["updated_at"].isoformat(),
                "steps": steps,
                "repository": {
                    "name": task_row["repo_name"],
                    "source_type": task_row["repo_source_type"],
                    "git_url": task_row["repo_git_url"],
                    "git_branch": task_row["repo_git_branch"],
                }
                if task_row["repo_name"]
                else None,
            }

    async def create_repository(
        self,
        repo_id: UUID,
        name: str,
        source_type: str,
        git_url: str | None = None,
        git_branch: str | None = None,
        s3_key: str | None = None,
        description: str | None = None,
        metadata: dict | None = None,
        commit_sha: str | None = None,
    ) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO repositories (
                    repo_id, name, source_type, git_url, git_branch, s3_key,
                    description, metadata, commit_sha
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (repo_id) DO UPDATE
                SET name = EXCLUDED.name,
                    source_type = EXCLUDED.source_type,
                    git_url = COALESCE(EXCLUDED.git_url, repositories.git_url),
                    git_branch = COALESCE(EXCLUDED.git_branch, repositories.git_branch),
                    s3_key = COALESCE(EXCLUDED.s3_key, repositories.s3_key),
                    description = COALESCE(EXCLUDED.description, repositories.description),
                    metadata = COALESCE(EXCLUDED.metadata, repositories.metadata),
                    commit_sha = COALESCE(EXCLUDED.commit_sha, repositories.commit_sha),
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                repo_id,
                name,
                source_type,
                git_url,
                git_branch,
                s3_key,
                description,
                json.dumps(metadata or {}),
                commit_sha,
            )
            logger.info("repository_created", repo_id=str(repo_id), name=name)
            return row["id"]

    async def get_repository(self, repo_id: UUID) -> RepositoryInfo | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    repo_id, name, source_type, git_url, git_branch,
                    s3_key, description, created_at, updated_at, metadata,
                    commit_sha
                FROM repositories
                WHERE repo_id = $1
                """,
                repo_id,
            )

            if not row:
                return None

            metadata = row["metadata"]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)

            return RepositoryInfo(
                repo_id=row["repo_id"],
                name=row["name"],
                source_type=row["source_type"],
                git_url=row["git_url"],
                git_branch=row["git_branch"],
                s3_key=row["s3_key"],
                description=row["description"],
                created_at=row["created_at"].isoformat(),
                updated_at=row["updated_at"].isoformat(),
                metadata=metadata,
                commit_sha=row["commit_sha"],
            )

    async def list_repositories(self, limit: int = 100, offset: int = 0) -> list[RepositoryInfo]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    repo_id, name, source_type, git_url, git_branch,
                    s3_key, description, created_at, updated_at, metadata,
                    commit_sha
                FROM repositories
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )

            result = []
            for row in rows:
                metadata = row["metadata"]
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)

                result.append(
                    RepositoryInfo(
                        repo_id=row["repo_id"],
                        name=row["name"],
                        source_type=row["source_type"],
                        git_url=row["git_url"],
                        git_branch=row["git_branch"],
                        s3_key=row["s3_key"],
                        description=row["description"],
                        created_at=row["created_at"].isoformat(),
                        updated_at=row["updated_at"].isoformat(),
                        metadata=metadata,
                        commit_sha=row["commit_sha"],
                    )
                )

            return result

    async def update_repository(
        self,
        repo_id: UUID,
        name: str | None = None,
        description: str | None = None,
        s3_key: str | None = None,
        metadata: dict | None = None,
        commit_sha: str | None = None,
        git_url: str | None = None,
        git_branch: str | None = None,
    ) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE repositories
                SET name = COALESCE($2, name),
                    description = COALESCE($3, description),
                    s3_key = COALESCE($4, s3_key),
                    metadata = COALESCE($5, metadata),
                    commit_sha = COALESCE($6, commit_sha),
                    git_url = COALESCE($7, git_url),
                    git_branch = COALESCE($8, git_branch),
                    updated_at = CURRENT_TIMESTAMP
                WHERE repo_id = $1
                """,
                repo_id,
                name,
                description,
                s3_key,
                json.dumps(metadata) if metadata else None,
                commit_sha,
                git_url,
                git_branch,
            )
            return result == "UPDATE 1"

    async def update_repository_metadata(
        self,
        repo_id: UUID,
        name: str | None = None,
        description: str | None = None,
        git_url: str | None = None,
        git_branch: str | None = None,
    ) -> bool:
        """Convenience wrapper used by the clone-refresh path: updates
        metadata only (no s3_key / commit_sha / metadata jsonb). The new
        ``s3_key`` and ``commit_sha`` are written by the worker after the
        re-clone completes.
        """
        return await self.update_repository(
            repo_id=repo_id,
            name=name,
            description=description,
            git_url=git_url,
            git_branch=git_branch,
        )

    async def delete_repository(self, repo_id: UUID) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM repositories
                WHERE repo_id = $1
                """,
                repo_id,
            )
            return result == "DELETE 1"

    # B2.4 / ТЗ ИНТ-04, ИНД-06 — per-file SHA-256 hashes for incremental
    # ingest. The pipeline reads ``get_file_hashes`` at the start of a run
    # to learn which files haven't changed since the last generation, then
    # writes a fresh snapshot via ``record_file_hashes`` at the end (one
    # row per file, scoped to the new ``generation_id``). Old rows are
    # never deleted — each generation has its own snapshot, and lookups
    # always pick the most recent hash per file.
    async def get_file_hashes(self, repository_id: UUID) -> dict[str, str]:
        """Return ``file_path → sha256`` from the most recent run per file.

        Picks the latest hash for each file across all past generations of
        the repo (ordered by ``indexed_at`` descending, ties broken by
        ``id``). First-run case returns ``{}`` so callers fall through to
        the full-reindex path.
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (file_path) file_path, content_sha256
                FROM repo_file_hashes
                WHERE repository_id = $1
                ORDER BY file_path, indexed_at DESC, id DESC
                """,
                repository_id,
            )
            return {row["file_path"]: row["content_sha256"] for row in rows}

    async def record_file_hashes(
        self,
        repository_id: UUID,
        generation_id: UUID,
        entries: list[FileHashEntry],
    ) -> None:
        """Bulk-insert one ``repo_file_hashes`` row per file for ``generation_id``.

        Idempotent on ``(generation_id, file_path)``: re-running the same
        ingest just refreshes ``content_sha256`` / ``chunks_count`` /
        ``indexed_at`` for the existing row. ``entries`` may be empty —
        we no-op rather than burn a transaction.
        """
        if not entries:
            return
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO repo_file_hashes (
                    repository_id, generation_id, file_path,
                    content_sha256, chunks_count, indexed_at
                )
                VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (generation_id, file_path) DO UPDATE
                SET content_sha256 = EXCLUDED.content_sha256,
                    chunks_count = EXCLUDED.chunks_count,
                    indexed_at = NOW()
                """,
                [
                    (
                        repository_id,
                        generation_id,
                        entry.file_path,
                        entry.content_sha256,
                        entry.chunks_count,
                    )
                    for entry in entries
                ],
            )
        logger.info(
            "repo_file_hashes_recorded",
            repository_id=str(repository_id),
            generation_id=str(generation_id),
            files=len(entries),
        )

    async def latest_generation_for_repo(self, repository_id: UUID) -> UUID | None:
        """Return the most recent ``generation_id`` recorded in ``repo_file_hashes``.

        Used by the incremental ingest path to discover the previous
        Qdrant collection (``docgen_{generation_id}``) so it can copy
        unchanged files' points across. Returns ``None`` for first-time
        ingests of a repo.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT generation_id
                FROM repo_file_hashes
                WHERE repository_id = $1
                ORDER BY indexed_at DESC, id DESC
                LIMIT 1
                """,
                repository_id,
            )
            if row is None:
                return None
            return row["generation_id"]

    async def list_bundle_generation_ids_for_repo(
        self,
        repo_id: UUID,
        limit: int = 10,
    ) -> list[str]:
        """Return generation_ids of bundles attached to ``repo_id``, newest first.

        Used by project-level RAG/search endpoints to map a repository to its
        Qdrant collection(s). The collection name follows the convention
        ``docgen_{generation_id}`` (see ``app.routes.tasks.service`` where it
        is minted at task creation).
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT generation_id
                FROM documentation_bundles
                WHERE repo_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                repo_id,
                limit,
            )
            return [str(row["generation_id"]) for row in rows]

    async def record_metric(
        self,
        generation_id: UUID,
        step: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: Decimal | float | None = None,
        step_started_at: dt.datetime | None = None,
        step_completed_at: dt.datetime | None = None,
        duration_ms: int | None = None,
        *,
        trace_id: str | None = None,
        extras: dict[str, tp.Any] | None = None,
    ) -> int:
        """Insert one token-usage / cost / timing row for a docgen agent run.

        Called from each handler (planner/writer/critic) after the
        Pydantic-AI agent completes. The ``total_tokens`` column is
        computed by Postgres (GENERATED ALWAYS AS).

        ``cost_usd`` is nullable: when the pricing map doesn't cover a
        model, we still persist the token counts so the API can show a
        partial total. The timing triplet is nullable for the same
        reason — older callers that don't capture wall-clock simply pass
        ``None`` and the row is excluded from p50/p95 aggregates.
        """
        cost_decimal: Decimal | None
        if cost_usd is None:
            cost_decimal = None
        elif isinstance(cost_usd, Decimal):
            cost_decimal = cost_usd
        else:
            cost_decimal = Decimal(str(cost_usd))

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO generation_metrics (
                    generation_id, step, model,
                    prompt_tokens, completion_tokens, cost_usd,
                    step_started_at, step_completed_at, duration_ms,
                    trace_id, extras
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING id
                """,
                generation_id,
                step,
                model,
                prompt_tokens,
                completion_tokens,
                cost_decimal,
                step_started_at,
                step_completed_at,
                duration_ms,
                trace_id,
                json.dumps(extras or {}),
            )
            metric_id = row["id"]
            logger.debug(
                "metric_recorded",
                generation_id=str(generation_id),
                step=step,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=str(cost_decimal) if cost_decimal is not None else None,
                duration_ms=duration_ms,
            )
            return metric_id

    async def get_metrics_for_generation(
        self,
        generation_id: UUID,
    ) -> list[GenerationMetric]:
        """Return every recorded metric row for a generation, oldest first."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id, generation_id, step, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    cost_usd, created_at,
                    step_started_at, step_completed_at, duration_ms,
                    trace_id, extras
                FROM generation_metrics
                WHERE generation_id = $1
                ORDER BY created_at ASC, id ASC
                """,
                generation_id,
            )
            return [_metric_from_row(row) for row in rows]

    async def find_generations_by_trace_id(self, trace_id: str) -> list[UUID]:
        """Return distinct ``generation_id``s whose metrics carry this ``trace_id`` (B13.4)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT generation_id
                FROM generation_metrics
                WHERE trace_id = $1
                ORDER BY generation_id
                """,
                trace_id,
            )
            return [row["generation_id"] for row in rows]

    async def get_metrics_by_trace_id(self, trace_id: str) -> list[GenerationMetric]:
        """Fetch all metric rows tagged with ``trace_id``, oldest step first (B13.4)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id, generation_id, step, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    cost_usd, created_at,
                    step_started_at, step_completed_at, duration_ms,
                    trace_id, extras
                FROM generation_metrics
                WHERE trace_id = $1
                ORDER BY COALESCE(step_started_at, created_at) ASC, id ASC
                """,
                trace_id,
            )
            return [_metric_from_row(row) for row in rows]

    async def get_metrics_aggregate(
        self,
        generation_id: UUID,
    ) -> dict[str, tp.Any]:
        """Return summed token usage + cost across all rows for a generation.

        Returns zeros (and a null ``cost_usd``) when no metrics have been
        recorded yet — callers can treat the result as "no usage data".
        ``cost_usd`` is the SUM of non-null cost rows; if every row had a
        null cost (no pricing entry), it's null.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    SUM(cost_usd) AS cost_usd
                FROM generation_metrics
                WHERE generation_id = $1
                """,
                generation_id,
            )
            return {
                "prompt_tokens": int(row["prompt_tokens"] or 0),
                "completion_tokens": int(row["completion_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "cost_usd": row["cost_usd"],
            }

    # B3.4 — Metrics dashboard bucket query.
    #
    # Mapping from the public ``group_by`` parameter to a SQL bucket
    # expression. ``day`` truncates the wall-clock completion time;
    # ``model`` and ``step`` group by the column directly. Whitelisted to
    # keep this query injection-safe — callers can only pass one of these
    # three keys.
    _METRICS_BUCKET_EXPR: tp.ClassVar[dict[str, str]] = {
        "day": "to_char(date_trunc('day', step_completed_at), 'YYYY-MM-DD')",
        "model": "model",
        "step": "step",
    }

    async def get_metrics_buckets(
        self,
        *,
        group_by: str,
        date_from: dt.datetime | None = None,
        date_to: dt.datetime | None = None,
    ) -> list[dict[str, tp.Any]]:
        """Return metrics aggregated into buckets for the dashboard (B3.4).

        Buckets are filtered by ``step_completed_at`` (so rows from older
        handlers without a completion timestamp are excluded — they have no
        date to bucket into). p50/p95 use ``percentile_cont`` over rows
        with a non-null ``duration_ms``.

        Returns an empty list when no rows fall in the range. The caller
        decides whether to render a chart or an empty-state. ``cost_usd``
        is a Decimal (or None for buckets where every row had a null cost)
        — the gateway service layer coerces it to float for JSON.
        """
        if group_by not in self._METRICS_BUCKET_EXPR:
            raise ValueError(
                f"group_by must be one of {sorted(self._METRICS_BUCKET_EXPR)}, got: {group_by}"
            )

        bucket_expr = self._METRICS_BUCKET_EXPR[group_by]
        order_clause = "bucket ASC" if group_by == "day" else "tokens DESC, bucket ASC"

        sql = f"""
            SELECT
                {bucket_expr} AS bucket,
                COALESCE(SUM(total_tokens), 0) AS tokens,
                SUM(cost_usd) AS cost_usd,
                percentile_cont(0.5) WITHIN GROUP (
                    ORDER BY duration_ms
                ) FILTER (WHERE duration_ms IS NOT NULL) AS duration_ms_p50,
                percentile_cont(0.95) WITHIN GROUP (
                    ORDER BY duration_ms
                ) FILTER (WHERE duration_ms IS NOT NULL) AS duration_ms_p95,
                COUNT(*) AS runs
            FROM generation_metrics
            WHERE step_completed_at IS NOT NULL
                AND ($1::TIMESTAMPTZ IS NULL OR step_completed_at >= $1)
                AND ($2::TIMESTAMPTZ IS NULL OR step_completed_at <  $2)
            GROUP BY {bucket_expr}
            ORDER BY {order_clause}
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, date_from, date_to)

        return [
            {
                "key": row["bucket"],
                "tokens": int(row["tokens"] or 0),
                "cost_usd": row["cost_usd"],
                "duration_ms_p50": (
                    int(row["duration_ms_p50"]) if row["duration_ms_p50"] is not None else None
                ),
                "duration_ms_p95": (
                    int(row["duration_ms_p95"]) if row["duration_ms_p95"] is not None else None
                ),
                "runs": int(row["runs"] or 0),
            }
            for row in rows
        ]

    # B6.5 — page-repository lookup for "View source" deep-links.
    async def get_page_repository(self, generation_id: UUID) -> dict | None:
        """Return the repository row attached to ``generation_id``'s bundle.

        Used by the page DTO to surface ``git_url`` and ``commit_sha`` so the
        UI can build "View source" deep-links. The commit SHA lives on the
        dedicated ``repositories.commit_sha`` column (migration 09; written
        by the repos worker after clone). Returns ``None`` if the bundle has
        no repository.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    r.name,
                    r.source_type,
                    r.git_url,
                    r.git_branch,
                    r.commit_sha
                FROM documentation_bundles db
                JOIN repositories r ON db.repo_id = r.repo_id
                WHERE db.generation_id = $1
                """,
                generation_id,
            )
            if not row:
                return None
            return {
                "name": row["name"],
                "source_type": row["source_type"],
                "git_url": row["git_url"],
                "git_branch": row["git_branch"],
                "commit_sha": row["commit_sha"],
            }

    # B6.2 — cross-page symbol-link index.
    async def record_page_symbols(
        self,
        generation_id: UUID,
        page_id: str,
        symbols: list[tuple[str, str]],
    ) -> None:
        """Bulk-insert ``(symbol, kind)`` pairs for a page.

        Idempotent per ``(generation_id, page_id)``: existing rows for the
        page are deleted first so re-running a generation doesn't accumulate
        stale entries. Empty/whitespace-only symbols are dropped before insert.
        """
        cleaned: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for sym, kind in symbols:
            sym_norm = (sym or "").strip()
            if not sym_norm:
                continue
            key = (sym_norm.lower(), kind)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append((sym_norm, kind))

        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM page_symbols WHERE generation_id = $1 AND page_id = $2",
                generation_id,
                page_id,
            )
            if cleaned:
                await conn.executemany(
                    """
                    INSERT INTO page_symbols (generation_id, page_id, symbol, kind)
                    VALUES ($1, $2, $3, $4)
                    """,
                    [(generation_id, page_id, sym, kind) for sym, kind in cleaned],
                )
        logger.info(
            "page_symbols_recorded",
            generation_id=str(generation_id),
            page_id=page_id,
            count=len(cleaned),
        )

    async def lookup_page_for_symbol(
        self,
        generation_id: UUID,
        symbol: str,
    ) -> tuple[str, str] | None:
        """Resolve ``symbol`` to ``(page_id, kind)`` (case-insensitive).

        ``page_title`` rows win over ``function``/``class``/``module`` if a
        symbol exists in multiple kinds (titles are the canonical home page).
        Returns ``None`` if no match.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT page_id, kind
                FROM page_symbols
                WHERE generation_id = $1 AND lower(symbol) = lower($2)
                ORDER BY CASE kind WHEN 'page_title' THEN 0 ELSE 1 END, id
                LIMIT 1
                """,
                generation_id,
                symbol,
            )
            if not row:
                return None
            return row["page_id"], row["kind"]

    async def list_page_symbols(self, generation_id: UUID) -> list[dict]:
        """Return every symbol recorded for ``generation_id``."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT symbol, page_id, kind
                FROM page_symbols
                WHERE generation_id = $1
                ORDER BY CASE kind WHEN 'page_title' THEN 1 ELSE 0 END, id
                """,
                generation_id,
            )
            return [
                {
                    "symbol": row["symbol"],
                    "page_id": row["page_id"],
                    "kind": row["kind"],
                }
                for row in rows
            ]

    # ------------------------------------------------------------------
    # B11.2 / ТЗ ГЕН-08 — append-only page-version history.
    #
    # ``page_versions`` is written alongside every successful
    # ``write_page`` call (one extra small INSERT per page). The current
    # ``documentation_pages`` row stays canonical for "latest" reads;
    # ``page_versions`` is only consulted when the UI explicitly asks
    # for a historical snapshot via ``get_page_version``.
    # ------------------------------------------------------------------
    async def record_page_version(
        self,
        page_id: str,
        generation_id: UUID,
        repository_id: UUID | None,
        commit_sha: str | None,
        body: dict[str, tp.Any],
        body_markdown: str | None,
        metadata: dict[str, tp.Any] | None,
    ) -> None:
        """Insert one snapshot row for ``(page_id, generation_id)``.

        Idempotent on the unique key — re-running the same generation
        (e.g. a worker recovery) just refreshes the body / markdown /
        metadata for the existing row instead of accumulating duplicates.
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO page_versions (
                    page_id, generation_id, repository_id, commit_sha,
                    body, body_markdown, metadata
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (page_id, generation_id) DO UPDATE
                SET repository_id = EXCLUDED.repository_id,
                    commit_sha = EXCLUDED.commit_sha,
                    body = EXCLUDED.body,
                    body_markdown = EXCLUDED.body_markdown,
                    metadata = EXCLUDED.metadata,
                    created_at = NOW()
                """,
                page_id,
                generation_id,
                repository_id,
                commit_sha,
                json.dumps(body),
                body_markdown,
                json.dumps(metadata) if metadata is not None else None,
            )
            logger.info(
                "page_version_recorded",
                page_id=page_id,
                generation_id=str(generation_id),
                commit_sha=commit_sha[:8] if commit_sha else None,
            )

    async def list_page_versions(
        self,
        page_id: str,
        limit: int = 20,
    ) -> list[PageVersionMeta]:
        """Return up to ``limit`` snapshots for ``page_id``, newest first.

        Used to populate the wiki's "Versions ▾" dropdown. The default 20
        is generous for the current docs-per-repo cadence — we'd rather
        hide the rare 21st-and-older entry than risk a slow scroll
        through hundreds of entries on a hot repo.
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT generation_id, commit_sha, created_at
                FROM page_versions
                WHERE page_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                page_id,
                limit,
            )
            return [
                PageVersionMeta(
                    generation_id=row["generation_id"],
                    commit_sha=row["commit_sha"],
                    created_at=row["created_at"].isoformat(),
                )
                for row in rows
            ]

    async def get_page_version(
        self,
        page_id: str,
        generation_id: UUID,
    ) -> PageVersionDetail | None:
        """Return the full snapshot for ``(page_id, generation_id)`` or ``None``.

        ``body`` and ``metadata`` JSONB columns are decoded to plain dicts
        so callers don't have to special-case asyncpg's return type
        (which can be either ``str`` or ``dict`` depending on codec
        registration).
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    page_id, generation_id, repository_id, commit_sha,
                    body, body_markdown, metadata, created_at
                FROM page_versions
                WHERE page_id = $1 AND generation_id = $2
                """,
                page_id,
                generation_id,
            )
            if row is None:
                return None

            body = row["body"]
            if isinstance(body, str):
                body = json.loads(body)
            metadata = row["metadata"]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)

            return PageVersionDetail(
                page_id=row["page_id"],
                generation_id=row["generation_id"],
                repository_id=row["repository_id"],
                commit_sha=row["commit_sha"],
                body=body or {},
                body_markdown=row["body_markdown"],
                metadata=metadata,
                created_at=row["created_at"].isoformat(),
            )

    # ------------------------------------------------------------------
    # B13.2 / ТЗ АГТ-06 (partial) — page-link graph.
    #
    # ``page_links`` records directed edges between pages within a
    # single generation. The finalize handler writes edges right after
    # ``record_page_symbols`` so the graph is rebuilt on every run; the
    # gateway exposes the result via /api/v1/wiki/{generation_id}/graph
    # and /api/v1/wiki/{generation_id}/pages/{page_id}/inbound.
    # ------------------------------------------------------------------
    async def record_page_links(
        self,
        generation_id: UUID,
        edges: list[PageLinkEntry],
    ) -> None:
        """Bulk-upsert directed edges for ``generation_id``.

        Self-loops (``from == to``) and entries with non-positive weight
        are dropped silently. Conflicts on
        ``(generation_id, from_page_id, to_page_id, kind)`` accumulate
        weight so multiple symbol mentions on the same page surface as a
        single, weighted edge instead of a flood of duplicates.
        """
        cleaned: list[PageLinkEntry] = []
        for edge in edges:
            if not edge.from_page_id or not edge.to_page_id:
                continue
            if edge.from_page_id == edge.to_page_id:
                continue
            if edge.weight <= 0:
                continue
            cleaned.append(edge)

        if not cleaned:
            return

        async with self.pool.acquire() as conn, conn.transaction():
            await conn.executemany(
                """
                INSERT INTO page_links (
                    generation_id, from_page_id, to_page_id, kind, weight
                )
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (generation_id, from_page_id, to_page_id, kind)
                DO UPDATE SET weight = page_links.weight + EXCLUDED.weight
                """,
                [
                    (
                        generation_id,
                        edge.from_page_id,
                        edge.to_page_id,
                        edge.kind,
                        edge.weight,
                    )
                    for edge in cleaned
                ],
            )
        logger.info(
            "page_links_recorded",
            generation_id=str(generation_id),
            count=len(cleaned),
        )

    async def list_page_links(self, generation_id: UUID) -> list[PageLink]:
        """Return every edge recorded for ``generation_id`` (graph view)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT from_page_id, to_page_id, kind, weight
                FROM page_links
                WHERE generation_id = $1
                ORDER BY from_page_id, to_page_id, kind
                """,
                generation_id,
            )
            return [
                PageLink(
                    from_page_id=row["from_page_id"],
                    to_page_id=row["to_page_id"],
                    kind=row["kind"],
                    weight=row["weight"],
                )
                for row in rows
            ]

    # ------------------------------------------------------------------
    # Migration 20 — append-only per-agent message history.
    #
    # ``record_agent_run`` is called from ``source2doc.agents.runner.run_agent``
    # on every Pydantic-AI ``agent.run()`` invocation (planner / subplanner
    # / writer / critic / diagrammer). Persistence is best-effort: a DB
    # outage must not sink a real generation, so the runner swallows
    # exceptions raised here.
    # ------------------------------------------------------------------
    async def record_agent_run(
        self,
        *,
        generation_id: UUID,
        agent_name: str,
        messages: dict | list[dict],
        page_id: str | None = None,
        section_id: str | None = None,
        attempt: int = 1,
        started_at: dt.datetime | None = None,
        finished_at: dt.datetime | None = None,
        duration_ms: int | None = None,
        success: bool = False,
        error_type: str | None = None,
        error_message: str | None = None,
        request_count: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        cost_usd: Decimal | float | None = None,
        output: tp.Any = None,
        trace_id: str | None = None,
    ) -> int:
        """INSERT one ``agent_runs`` row and return its ``id``.

        ``messages`` must be JSON-serialisable (the runner uses
        ``ModelMessagesTypeAdapter.dump_python(..., mode='json')``).
        ``output`` is dumped via ``json.dumps`` with a permissive default
        so non-JSON-native types (UUID, datetime, dataclasses) don't blow
        up persistence — they're stored as their string repr.
        """
        cost_decimal: Decimal | None
        if cost_usd is None:
            cost_decimal = None
        elif isinstance(cost_usd, Decimal):
            cost_decimal = cost_usd
        else:
            cost_decimal = Decimal(str(cost_usd))

        if total_tokens is None and (input_tokens is not None or output_tokens is not None):
            total_tokens = (input_tokens or 0) + (output_tokens or 0)

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO agent_runs (
                    generation_id, page_id, section_id, agent_name, attempt,
                    started_at, finished_at, duration_ms,
                    success, error_type, error_message,
                    request_count, input_tokens, output_tokens, total_tokens,
                    cost_usd, messages, output, trace_id
                )
                VALUES (
                    $1, $2, $3, $4, $5,
                    COALESCE($6, NOW()), $7, $8,
                    $9, $10, $11,
                    $12, $13, $14, $15,
                    $16, $17::jsonb, $18::jsonb, $19
                )
                RETURNING id
                """,
                generation_id,
                page_id,
                section_id,
                agent_name,
                attempt,
                started_at,
                finished_at,
                duration_ms,
                success,
                error_type,
                error_message,
                request_count,
                input_tokens,
                output_tokens,
                total_tokens,
                cost_decimal,
                json.dumps(messages, default=_json_default),
                json.dumps(output, default=_json_default) if output is not None else None,
                trace_id,
            )
            run_id = row["id"]
            logger.debug(
                "agent_run_recorded",
                run_id=run_id,
                generation_id=str(generation_id),
                agent=agent_name,
                page_id=page_id,
                section_id=section_id,
                attempt=attempt,
                success=success,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            return run_id

    async def list_agent_runs(
        self,
        generation_id: UUID,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AgentRunRecord]:
        """Return ``agent_runs`` for ``generation_id`` newest-first.

        Default limit is sized for the UI's table view: a typical
        generation lands ~30 rows (planner + N×subplanner + N×writer +
        N×critic + diagram fan-out), so 200 covers even the chatty cases
        without paging.
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id, generation_id, page_id, section_id, agent_name, attempt,
                    started_at, finished_at, duration_ms,
                    success, error_type, error_message,
                    request_count, input_tokens, output_tokens, total_tokens,
                    cost_usd, messages, output, trace_id
                FROM agent_runs
                WHERE generation_id = $1
                ORDER BY started_at DESC, id DESC
                LIMIT $2 OFFSET $3
                """,
                generation_id,
                limit,
                offset,
            )
            return [_agent_run_from_row(row) for row in rows]

    async def get_agent_run(self, run_id: int) -> AgentRunRecord | None:
        """Fetch one ``agent_runs`` row by primary key (used for the detail panel)."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    id, generation_id, page_id, section_id, agent_name, attempt,
                    started_at, finished_at, duration_ms,
                    success, error_type, error_message,
                    request_count, input_tokens, output_tokens, total_tokens,
                    cost_usd, messages, output, trace_id
                FROM agent_runs
                WHERE id = $1
                """,
                run_id,
            )
            if row is None:
                return None
            return _agent_run_from_row(row)

    async def list_inbound_links(
        self,
        generation_id: UUID,
        page_id: str,
    ) -> list[PageLink]:
        """Return edges where ``page_id`` is the *target* (referenced by …)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT from_page_id, to_page_id, kind, weight
                FROM page_links
                WHERE generation_id = $1 AND to_page_id = $2
                ORDER BY weight DESC, from_page_id
                """,
                generation_id,
                page_id,
            )
            return [
                PageLink(
                    from_page_id=row["from_page_id"],
                    to_page_id=row["to_page_id"],
                    kind=row["kind"],
                    weight=row["weight"],
                )
                for row in rows
            ]


def _json_default(value: tp.Any) -> tp.Any:
    """Permissive ``json.dumps`` fallback for ``record_agent_run``.

    Pydantic-AI's ``ModelMessagesTypeAdapter.dump_python(mode='json')``
    already returns JSON-native types, but the agent's structured
    ``output`` may be an arbitrary Pydantic model / dataclass / UUID /
    datetime. We coerce those instead of crashing — persistence is for
    debugging, lossy is fine.
    """
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except TypeError:
            return value.model_dump()
    if dc.is_dataclass(value) and not isinstance(value, type):
        return dc.asdict(value)
    if hasattr(value, "__dict__"):
        return {k: v for k, v in vars(value).items() if not k.startswith("_")}
    return repr(value)


def _agent_run_from_row(row: tp.Mapping[str, tp.Any]) -> AgentRunRecord:
    """Decode an ``agent_runs`` row into an ``AgentRunRecord`` dataclass.

    Both ``messages`` and ``output`` come back from asyncpg as either
    ``str`` (when the JSONB codec isn't registered) or already-decoded
    Python values. Normalise to plain dicts/lists so callers don't need
    to special-case asyncpg's return type.
    """
    messages = row["messages"]
    if isinstance(messages, str):
        try:
            messages = json.loads(messages)
        except (TypeError, ValueError):
            messages = []
    output = row["output"]
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except (TypeError, ValueError):
            output = None
    return AgentRunRecord(
        id=row["id"],
        generation_id=row["generation_id"],
        page_id=row["page_id"],
        section_id=row["section_id"],
        agent_name=row["agent_name"],
        attempt=row["attempt"],
        started_at=row["started_at"].isoformat() if row["started_at"] else "",
        finished_at=(row["finished_at"].isoformat() if row["finished_at"] else None),
        duration_ms=row["duration_ms"],
        success=row["success"],
        error_type=row["error_type"],
        error_message=row["error_message"],
        request_count=row["request_count"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        total_tokens=row["total_tokens"],
        cost_usd=row["cost_usd"],
        messages=messages if messages is not None else [],
        output=output,
        trace_id=row["trace_id"],
    )


def _metric_from_row(row: tp.Mapping[str, tp.Any]) -> GenerationMetric:
    """Map a ``generation_metrics`` row to a ``GenerationMetric`` dataclass."""
    extras = row["extras"]
    if isinstance(extras, str):
        try:
            extras = json.loads(extras)
        except (TypeError, ValueError):
            extras = {}
    if not isinstance(extras, dict):
        extras = {}
    return GenerationMetric(
        id=row["id"],
        generation_id=row["generation_id"],
        step=row["step"],
        model=row["model"],
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
        total_tokens=row["total_tokens"],
        cost_usd=row["cost_usd"],
        created_at=row["created_at"].isoformat() if row["created_at"] else "",
        step_started_at=(
            row["step_started_at"].isoformat() if row["step_started_at"] else None
        ),
        step_completed_at=(
            row["step_completed_at"].isoformat() if row["step_completed_at"] else None
        ),
        duration_ms=row["duration_ms"],
        trace_id=row["trace_id"],
        extras=extras,
    )
