from __future__ import annotations

import json
import typing as tp
from uuid import UUID

import asyncpg

import source2doc.logging as logging


logger = logging.get_logger(__name__)


class CodetourStorage:
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.pool: asyncpg.Pool | None = None

    async def __aenter__(self) -> CodetourStorage:
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
            min_size=2,
            max_size=10,
        )
        logger.info("postgres_connected")

    async def close(self) -> None:
        if self.pool:
            logger.info("closing_postgres_connection")
            await self.pool.close()
            logger.info("postgres_closed")

    async def create_codetour(
        self,
        tour_id: UUID,
        generation_id: UUID,
        title: str,
        description: str,
        steps: list[dict[str, tp.Any]],
        metadata: dict[str, tp.Any],
    ) -> None:
        if not self.pool:
            raise RuntimeError("Connection pool not initialized")
        async with self.pool.acquire() as conn:
            steps_json = json.dumps(steps)
            metadata_json = json.dumps(metadata)

            await conn.execute(
                """
                INSERT INTO codetours (
                    tour_id, generation_id, title, description, steps, metadata
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                tour_id,
                generation_id,
                title,
                description,
                steps_json,
                metadata_json,
            )
            logger.info(
                "codetour_created",
                tour_id=str(tour_id),
                generation_id=str(generation_id),
            )

    async def create_pending_tour(
        self,
        tour_id: UUID,
        generation_id: UUID,
        request_payload: dict[str, tp.Any],
    ) -> None:
        if not self.pool:
            raise RuntimeError("Connection pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO codetours (
                    tour_id, generation_id, title, description, steps, metadata,
                    status, request_payload, created_at
                )
                VALUES (
                    $1, $2, '', '', '[]'::jsonb, '{}'::jsonb,
                    'pending', $3::jsonb, NOW()
                )
                ON CONFLICT (tour_id) DO NOTHING
                """,
                tour_id,
                generation_id,
                json.dumps(request_payload),
            )
            logger.info(
                "codetour_pending_created",
                tour_id=str(tour_id),
                generation_id=str(generation_id),
            )

    async def mark_running(self, tour_id: UUID) -> None:
        if not self.pool:
            raise RuntimeError("Connection pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE codetours
                SET status = 'running',
                    started_at = COALESCE(started_at, NOW())
                WHERE tour_id = $1 AND status IN ('pending', 'running')
                """,
                tour_id,
            )

    async def mark_completed(
        self,
        tour_id: UUID,
        title: str,
        description: str,
        steps: list[dict[str, tp.Any]],
        metadata: dict[str, tp.Any],
    ) -> None:
        if not self.pool:
            raise RuntimeError("Connection pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE codetours
                SET status = 'completed',
                    finished_at = NOW(),
                    title = $2,
                    description = $3,
                    steps = $4::jsonb,
                    metadata = $5::jsonb,
                    error_message = NULL
                WHERE tour_id = $1
                """,
                tour_id,
                title,
                description,
                json.dumps(steps),
                json.dumps(metadata),
            )
            logger.info("codetour_completed_persisted", tour_id=str(tour_id))

    async def mark_failed(self, tour_id: UUID, error_message: str) -> None:
        if not self.pool:
            raise RuntimeError("Connection pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE codetours
                SET status = 'failed',
                    finished_at = NOW(),
                    error_message = $2
                WHERE tour_id = $1
                """,
                tour_id,
                error_message,
            )
            logger.info("codetour_failed_persisted", tour_id=str(tour_id))

    async def append_followup_steps(
        self,
        tour_id: UUID,
        new_steps: list[dict[str, tp.Any]],
    ) -> None:
        """Append additional steps to an existing tour without resetting status.

        Used by Phase B follow-up generation: the original ``steps`` array is
        kept, and ``new_steps`` are concatenated. Tour metadata is left intact.
        """
        if not self.pool:
            raise RuntimeError("Connection pool not initialized")
        if not new_steps:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE codetours
                SET steps = (
                    COALESCE(steps, '[]'::jsonb) || $2::jsonb
                )
                WHERE tour_id = $1
                """,
                tour_id,
                json.dumps(new_steps),
            )
            logger.info(
                "codetour_followup_appended",
                tour_id=str(tour_id),
                appended=len(new_steps),
            )

    async def mark_cancelled(self, tour_id: UUID) -> None:
        if not self.pool:
            raise RuntimeError("Connection pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE codetours
                SET status = 'cancelled',
                    finished_at = NOW()
                WHERE tour_id = $1 AND status IN ('pending', 'running')
                """,
                tour_id,
            )

    async def get_codetour(self, tour_id: UUID) -> dict[str, tp.Any] | None:
        if not self.pool:
            raise RuntimeError("Connection pool not initialized")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT tour_id, generation_id, title, description, steps, created_at,
                       metadata, status, error_message, started_at, finished_at,
                       request_payload
                FROM codetours
                WHERE tour_id = $1
                """,
                tour_id,
            )

            if not row:
                return None

            def _maybe_json(value: tp.Any) -> tp.Any:
                return json.loads(value) if isinstance(value, str) else value

            return {
                "tour_id": str(row["tour_id"]),
                "generation_id": str(row["generation_id"]),
                "title": row["title"],
                "description": row["description"],
                "steps": _maybe_json(row["steps"]),
                "created_at": row["created_at"].isoformat(),
                "metadata": _maybe_json(row["metadata"]),
                "status": row["status"],
                "error_message": row["error_message"],
                "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
                "request_payload": _maybe_json(row["request_payload"]),
            }

    async def list_codetours_by_generation(self, generation_id: UUID) -> list[dict[str, tp.Any]]:
        if not self.pool:
            raise RuntimeError("Connection pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT tour_id, title, description, created_at, status
                FROM codetours
                WHERE generation_id = $1
                ORDER BY created_at DESC
                """,
                generation_id,
            )

            return [
                {
                    "tour_id": str(row["tour_id"]),
                    "title": row["title"],
                    "description": row["description"],
                    "created_at": row["created_at"].isoformat(),
                    "status": row["status"],
                }
                for row in rows
            ]

    async def list_all_codetours(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, tp.Any]]:
        if not self.pool:
            raise RuntimeError("Connection pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT tour_id, generation_id, title, description, created_at, status
                FROM codetours
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )

            return [
                {
                    "tour_id": str(row["tour_id"]),
                    "generation_id": str(row["generation_id"]),
                    "title": row["title"],
                    "description": row["description"],
                    "created_at": row["created_at"].isoformat(),
                    "status": row["status"],
                }
                for row in rows
            ]
