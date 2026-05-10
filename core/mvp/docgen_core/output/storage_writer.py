from uuid import UUID

from source2doc import DocIndex, DocPage, get_logger
from source2doc.storage.base import StorageBackend


logger = get_logger(__name__)


class StorageDocumentationWriter:
    def __init__(
        self,
        storage: StorageBackend,
        generation_id: UUID,
        project_name: str | None = None,
    ):
        self.storage = storage
        self.generation_id = generation_id
        self.project_name = project_name
        self.bundle_id: int | None = None

    async def initialize(self) -> None:
        self.bundle_id = await self.storage.create_bundle(self.generation_id, self.project_name)
        logger.info(
            "storage_writer_initialized",
            bundle_id=self.bundle_id,
            generation_id=str(self.generation_id),
        )

    async def write_index(self, index: DocIndex) -> None:
        if self.bundle_id is None:
            raise RuntimeError("Writer not initialized. Call initialize() first.")

        await self.storage.write_index(self.bundle_id, index)
        logger.info("index_written_to_storage", bundle_id=self.bundle_id)

    async def write_page(
        self,
        page_id: str,
        page: DocPage,
        commit_sha: str | None = None,
    ) -> None:
        if self.bundle_id is None:
            raise RuntimeError("Writer not initialized. Call initialize() first.")

        await self.storage.write_page(self.bundle_id, page_id, page, commit_sha=commit_sha)
        logger.info("page_written_to_storage", bundle_id=self.bundle_id, page_id=page_id)
