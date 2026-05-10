from pathlib import Path

from source2doc import DocIndex, DocPage, get_logger


logger = get_logger(__name__)


class DocumentationWriter:
    """Writes documentation files to disk."""

    def __init__(self, output_dir: Path):
        """Initialize writer with output directory."""
        self.output_dir = output_dir
        self.pages_dir = output_dir / "pages"

    def write_index(self, index: DocIndex) -> None:
        """Write index.json file."""
        self.pages_dir.mkdir(parents=True, exist_ok=True)

        index_path = self.output_dir / "index.json"
        content = index.model_dump_json(indent=2, exclude_none=True)
        index_path.write_text(content, encoding="utf-8")

        logger.info("index_written", path=str(index_path))

    def write_page(self, page_id: str, page: DocPage) -> None:
        """Write a documentation page."""
        self.pages_dir.mkdir(parents=True, exist_ok=True)

        page_path = self.pages_dir / f"{page_id}.json"
        content = page.model_dump_json(indent=2, exclude_none=True)
        page_path.write_text(content, encoding="utf-8")

        logger.info("page_written", page_id=page_id, path=str(page_path))
