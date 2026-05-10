import abc
import datetime as dt
from uuid import UUID

import pydantic as pyd


class DocIndex(pyd.BaseModel):
    version: str
    generated_at: dt.datetime
    navigation: dict


class DocPage(pyd.BaseModel):
    title: str
    summary: str
    content: dict
    metadata: dict


class StorageBackend(abc.ABC):
    @abc.abstractmethod
    async def connect(self) -> None:
        pass

    @abc.abstractmethod
    async def close(self) -> None:
        pass

    @abc.abstractmethod
    async def create_bundle(self, generation_id: UUID, project_name: str | None = None) -> int:
        pass

    @abc.abstractmethod
    async def write_index(self, bundle_id: int, index: DocIndex) -> None:
        pass

    @abc.abstractmethod
    async def write_page(
        self,
        bundle_id: int,
        page_id: str,
        page: DocPage,
        commit_sha: str | None = None,
    ) -> None:
        pass

    @abc.abstractmethod
    async def get_index(self, generation_id: UUID) -> DocIndex | None:
        pass

    @abc.abstractmethod
    async def get_page(self, generation_id: UUID, page_id: str) -> DocPage | None:
        pass

    @abc.abstractmethod
    async def list_bundles(self, limit: int = 100, offset: int = 0) -> list[dict]:
        pass

    @abc.abstractmethod
    async def get_bundle_pages(self, generation_id: UUID) -> list[dict]:
        pass
