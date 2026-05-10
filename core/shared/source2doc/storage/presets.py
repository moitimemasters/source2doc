from __future__ import annotations

import dataclasses as dc
import typing as tp

import asyncpg

from source2doc.logging import get_logger


logger = get_logger(__name__)


@dc.dataclass
class PresetMeta:
    id: int
    name: str
    is_default: bool
    description: str | None
    created_at: str
    updated_at: str


@dc.dataclass
class Preset:
    id: int
    name: str
    is_default: bool
    description: str | None
    encrypted_config: str
    created_at: str
    updated_at: str


class ConfigPresetStorage:
    def __init__(self, connection_string: str) -> None:
        self.connection_string = connection_string
        self.pool: asyncpg.Pool | None = None

    async def __aenter__(self) -> ConfigPresetStorage:
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
        logger.info("connecting_preset_storage")
        self.pool = await asyncpg.create_pool(self.connection_string, min_size=1, max_size=4)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    def _require_pool(self) -> asyncpg.Pool:
        if not self.pool:
            raise RuntimeError("Preset storage pool not initialized")
        return self.pool

    async def list(self) -> list[PresetMeta]:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, name, is_default, description, created_at, updated_at
                FROM config_presets
                ORDER BY is_default DESC, name ASC
                """
            )
            return [
                PresetMeta(
                    id=row["id"],
                    name=row["name"],
                    is_default=row["is_default"],
                    description=row["description"],
                    created_at=row["created_at"].isoformat(),
                    updated_at=row["updated_at"].isoformat(),
                )
                for row in rows
            ]

    async def get(self, preset_id: int) -> Preset | None:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, name, is_default, description, encrypted_config, created_at, updated_at
                FROM config_presets
                WHERE id = $1
                """,
                preset_id,
            )
            return _row_to_preset(row) if row else None

    async def get_by_name(self, name: str) -> Preset | None:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, name, is_default, description, encrypted_config, created_at, updated_at
                FROM config_presets
                WHERE name = $1
                """,
                name,
            )
            return _row_to_preset(row) if row else None

    async def get_default(self) -> Preset | None:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, name, is_default, description, encrypted_config, created_at, updated_at
                FROM config_presets
                WHERE is_default = TRUE
                LIMIT 1
                """
            )
            return _row_to_preset(row) if row else None

    async def create(
        self,
        *,
        name: str,
        encrypted_config: str,
        description: str | None,
        is_default: bool,
    ) -> int:
        pool = self._require_pool()
        async with pool.acquire() as conn, conn.transaction():
            if is_default:
                await conn.execute("UPDATE config_presets SET is_default = FALSE")
            row = await conn.fetchrow(
                """
                INSERT INTO config_presets (name, encrypted_config, description, is_default)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                name,
                encrypted_config,
                description,
                is_default,
            )
            return row["id"]

    async def update(
        self,
        preset_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        encrypted_config: str | None = None,
        is_default: bool | None = None,
    ) -> bool:
        pool = self._require_pool()
        async with pool.acquire() as conn, conn.transaction():
            if is_default is True:
                await conn.execute(
                    "UPDATE config_presets SET is_default = FALSE WHERE id <> $1",
                    preset_id,
                )
            result = await conn.execute(
                """
                UPDATE config_presets
                SET name = COALESCE($2, name),
                    description = COALESCE($3, description),
                    encrypted_config = COALESCE($4, encrypted_config),
                    is_default = COALESCE($5, is_default),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = $1
                """,
                preset_id,
                name,
                description,
                encrypted_config,
                is_default,
            )
            return result == "UPDATE 1"

    async def delete(self, preset_id: int) -> bool:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM config_presets WHERE id = $1", preset_id)
            return result == "DELETE 1"

    async def set_default(self, preset_id: int) -> bool:
        pool = self._require_pool()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("UPDATE config_presets SET is_default = FALSE")
            result = await conn.execute(
                "UPDATE config_presets SET is_default = TRUE WHERE id = $1",
                preset_id,
            )
            return result == "UPDATE 1"


def _row_to_preset(row: asyncpg.Record) -> Preset:
    return Preset(
        id=row["id"],
        name=row["name"],
        is_default=row["is_default"],
        description=row["description"],
        encrypted_config=row["encrypted_config"],
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )
