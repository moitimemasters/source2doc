from __future__ import annotations

import dataclasses as dc
import datetime as dt
import typing as tp

import asyncpg

from source2doc.logging import get_logger


logger = get_logger(__name__)


@dc.dataclass
class AdminSession:
    token_hash: str
    created_at: dt.datetime
    expires_at: dt.datetime
    last_seen_at: dt.datetime


class AdminSessionStorage:
    def __init__(self, connection_string: str) -> None:
        self.connection_string = connection_string
        self.pool: asyncpg.Pool | None = None

    async def __aenter__(self) -> AdminSessionStorage:
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
        logger.info("connecting_admin_session_storage")
        self.pool = await asyncpg.create_pool(self.connection_string, min_size=1, max_size=4)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    def _require_pool(self) -> asyncpg.Pool:
        if not self.pool:
            raise RuntimeError("Admin session pool not initialized")
        return self.pool

    async def create(self, token_hash: str, expires_at: dt.datetime) -> None:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO admin_sessions (token_hash, expires_at)
                VALUES ($1, $2)
                """,
                token_hash,
                expires_at,
            )

    async def get(self, token_hash: str) -> AdminSession | None:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE admin_sessions
                SET last_seen_at = CURRENT_TIMESTAMP
                WHERE token_hash = $1 AND expires_at > CURRENT_TIMESTAMP
                RETURNING token_hash, created_at, expires_at, last_seen_at
                """,
                token_hash,
            )
            if not row:
                return None
            return AdminSession(
                token_hash=row["token_hash"],
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                last_seen_at=row["last_seen_at"],
            )

    async def delete(self, token_hash: str) -> bool:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM admin_sessions WHERE token_hash = $1",
                token_hash,
            )
            return result == "DELETE 1"

    async def purge_expired(self) -> int:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM admin_sessions WHERE expires_at <= CURRENT_TIMESTAMP"
            )
            try:
                return int(result.split()[-1])
            except (ValueError, IndexError):
                return 0
