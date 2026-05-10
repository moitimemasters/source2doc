from pathlib import Path
import typing as tp

from source2doc.models import docs as doc_models


class BundleFormatter(tp.Protocol):
    async def format_bundle(
        self,
        index: doc_models.DocIndex,
        pages: dict[str, doc_models.DocPage],
        output_dir: Path,
    ) -> None: ...

    def get_file_extension(self) -> str: ...
