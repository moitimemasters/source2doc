"""asyncpg storage for PR microdoc summaries (table ``prdoc_summaries``).

Mirrors the shape of :class:`source2doc.storage.codetour.CodetourStorage` —
its own connection pool so the gateway and the prdoc worker can each open
the resource they need without dragging the rest of ``PostgresStorage``.
"""

from __future__ import annotations

import json
import typing as tp
from uuid import UUID

import asyncpg

import source2doc.logging as logging


logger = logging.get_logger(__name__)


class PRDocStorage:
    def __init__(self, connection_string: str) -> None:
        self.connection_string = connection_string
        self.pool: asyncpg.Pool | None = None

    async def __aenter__(self) -> PRDocStorage:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: tp.Any,
    ) -> None:
        await self.close()

    async def connect(self) -> None:
        logger.info("connecting_to_postgres")
        self.pool = await asyncpg.create_pool(
            self.connection_string,
            min_size=1,
            max_size=5,
        )
        logger.info("postgres_connected")

    async def close(self) -> None:
        if self.pool is not None:
            logger.info("closing_postgres_connection")
            await self.pool.close()
            logger.info("postgres_closed")

    async def create_pending(
        self,
        generation_id: UUID,
        repo_id: UUID | None,
        base_sha: str | None,
        head_sha: str | None,
        title: str | None,
    ) -> None:
        if self.pool is None:
            raise RuntimeError("Connection pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO prdoc_summaries (
                    generation_id, repo_id, base_sha, head_sha, title, status, created_at
                )
                VALUES ($1, $2, $3, $4, $5, 'pending', NOW())
                ON CONFLICT (generation_id) DO NOTHING
                """,
                generation_id,
                repo_id,
                base_sha,
                head_sha,
                title,
            )
            logger.info(
                "prdoc_pending_created",
                generation_id=str(generation_id),
                repo_id=str(repo_id) if repo_id else None,
            )

    async def mark_running(self, generation_id: UUID) -> None:
        if self.pool is None:
            raise RuntimeError("Connection pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE prdoc_summaries
                SET status = 'running',
                    started_at = COALESCE(started_at, NOW())
                WHERE generation_id = $1 AND status IN ('pending', 'running')
                """,
                generation_id,
            )

    async def mark_completed(
        self,
        generation_id: UUID,
        summary: str,
        highlights: list[str],
        concerns: list[str],
        files_summarised: int,
    ) -> None:
        if self.pool is None:
            raise RuntimeError("Connection pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE prdoc_summaries
                SET status = 'completed',
                    finished_at = NOW(),
                    summary = $2,
                    highlights = $3::jsonb,
                    concerns = $4::jsonb,
                    files_summarised = $5,
                    error_message = NULL
                WHERE generation_id = $1
                """,
                generation_id,
                summary,
                json.dumps(highlights),
                json.dumps(concerns),
                files_summarised,
            )
            logger.info("prdoc_completed_persisted", generation_id=str(generation_id))

    async def mark_failed(self, generation_id: UUID, error_message: str) -> None:
        if self.pool is None:
            raise RuntimeError("Connection pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE prdoc_summaries
                SET status = 'failed',
                    finished_at = NOW(),
                    error_message = $2
                WHERE generation_id = $1
                """,
                generation_id,
                error_message,
            )
            logger.info("prdoc_failed_persisted", generation_id=str(generation_id))

    async def get(self, generation_id: UUID) -> dict[str, tp.Any] | None:
        if self.pool is None:
            raise RuntimeError("Connection pool not initialized")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT generation_id, repo_id, base_sha, head_sha, title,
                       summary, highlights, concerns, files_summarised,
                       status, error_message, created_at, started_at, finished_at
                FROM prdoc_summaries
                WHERE generation_id = $1
                """,
                generation_id,
            )
            if row is None:
                return None

            def _maybe_json(value: tp.Any) -> tp.Any:
                return json.loads(value) if isinstance(value, str) else value

            return {
                "generation_id": str(row["generation_id"]),
                "repo_id": str(row["repo_id"]) if row["repo_id"] else None,
                "base_sha": row["base_sha"],
                "head_sha": row["head_sha"],
                "title": row["title"],
                "summary_markdown": row["summary"],
                "highlights": _maybe_json(row["highlights"]) or [],
                "concerns": _maybe_json(row["concerns"]) or [],
                "files_summarised": row["files_summarised"],
                "status": row["status"],
                "error_message": row["error_message"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
            }
