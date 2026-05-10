from pathlib import Path
import shutil
import tarfile
import tempfile
from uuid import UUID

from source2doc.config import S3Config
from source2doc.logging import get_logger
from source2doc.models import docs as doc_models
from source2doc.resilience import s3_retry
from source2doc.storage import PostgresStorage, S3Storage

from worker.bundler import mermaid as mermaid_render
from worker.bundler import toc as toc_mod
from worker.bundler.env import BundlerWorkerEnv
from worker.bundler.formatters import gfm, mkdocs, nextra, sphinx, yfm
from worker.bundler.formatters.gfm_formatter import GFMFormatter
from worker.bundler.formatters.mkdocs_formatter import MkDocsFormatter
from worker.bundler.formatters.nextra_formatter import NextraFormatter
from worker.bundler.formatters.sphinx_formatter import SphinxFormatter
from worker.bundler.formatters.yfm_formatter import YFMFormatter


logger = get_logger(__name__)


async def process_bundle_export(
    env: BundlerWorkerEnv,
    task_info: dict,
) -> None:
    bundle_id = task_info["bundle_id"]
    generation_id = UUID(task_info["generation_id"])
    output_format = task_info["format"]
    s3_config = task_info.get("s3_config")
    postgres_connection_string = task_info["postgres_connection_string"]
    mermaid_render_mode = _resolve_mermaid_mode(
        task_info.get("mermaid_render"),
        output_format,
    )
    toc_max_depth = _resolve_toc_max_depth(env, task_info)

    logger.info(
        "processing_bundle_export",
        bundle_id=bundle_id,
        generation_id=str(generation_id),
        format=output_format,
        mermaid_render=mermaid_render_mode,
        toc_max_depth=toc_max_depth,
    )

    storage = PostgresStorage(postgres_connection_string)
    await storage.connect()

    try:
        index, pages = await _fetch_bundle_data(storage, generation_id)
        archive_path, temp_dir = await _create_bundle_archive(
            bundle_id,
            output_format,
            index,
            pages,
            mermaid_render_mode,
            toc_max_depth=toc_max_depth,
        )
        try:
            s3_key = await _upload_bundle_to_s3(
                env,
                bundle_id,
                output_format,
                archive_path,
                s3_config,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        logger.info("bundle_export_completed", bundle_id=bundle_id, s3_key=s3_key)

    finally:
        await storage.close()


async def _fetch_bundle_data(
    storage: PostgresStorage,
    generation_id: UUID,
) -> tuple[doc_models.DocIndex, dict[str, doc_models.DocPage]]:
    index = await storage.get_index(generation_id)
    if not index:
        raise ValueError(f"Index not found for generation {generation_id}")

    pages = {}
    for page_id in _collect_page_ids(index.navigation):
        page = await storage.get_page(generation_id, page_id)
        if page:
            pages[page_id] = page

    return index, pages


def _collect_page_ids(navigation: dict[str, str | dict]) -> list[str]:
    """Recursively collect all leaf page IDs from a navigation tree.

    Navigation entries that are plain strings or dicts without ``children``
    are leaf pages.  Entries with ``children`` are group sections — their
    children are the actual pages.

    Example::

        navigation = {
            "overview": "Overview",
            "bot-commands": {
                "title": "Bot Commands",
                "children": {
                    "find-command": "Find Command",
                    "stop-command": "Stop Command",
                }
            }
        }
        # returns ["overview", "find-command", "stop-command"]
    """
    ids: list[str] = []
    for page_id, data in navigation.items():
        if isinstance(data, dict) and "children" in data:
            # Group section — recurse into children.
            ids.extend(_collect_page_ids(data["children"]))
        else:
            ids.append(page_id)
    return ids


async def _create_bundle_archive(
    bundle_id: str,
    output_format: str,
    index: doc_models.DocIndex,
    pages: dict[str, doc_models.DocPage],
    mermaid_render_mode: mermaid_render.MermaidRenderMode,
    *,
    toc_max_depth: int = 2,
) -> tuple[Path, Path]:
    temp_dir = Path(tempfile.mkdtemp())
    try:
        output_dir = temp_dir / "bundle"
        output_dir.mkdir()

        await _format_bundle(output_format, index, pages, output_dir, mermaid_render_mode)

        # Postprocessing: walk the formatter's output and emit a unified
        # ``toc.json`` + ``_toc.md`` next to the format-specific index.
        toc_mod.generate_toc_files(output_dir, max_depth=toc_max_depth)

        archive_path = temp_dir / f"{bundle_id}.tar.gz"
        _create_tarball(output_dir, archive_path)
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    return archive_path, temp_dir


def _resolve_toc_max_depth(env: BundlerWorkerEnv, task_info: dict) -> int:
    """Resolve ToC depth from ``task_info`` override → worker config → default.

    A task may carry an explicit ``toc_max_depth`` override (useful for ad-hoc
    exports from the gateway).  When absent we fall back to
    ``config.bundler.toc_max_depth`` and finally to ``2`` if the worker has no
    config attached (e.g. unit tests).
    """
    override = task_info.get("toc_max_depth")
    if isinstance(override, int):
        return max(0, override)
    config = getattr(env, "config", None)
    bundler_config = getattr(config, "bundler", None)
    if bundler_config is not None:
        return bundler_config.toc_max_depth
    return 2


def _create_tarball(source_dir: Path, archive_path: Path) -> None:
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(source_dir, arcname=".")


@s3_retry()
async def _retrying_upload_fileobj(s3, fileobj, bucket: str, key: str) -> None:
    await s3.upload_fileobj(fileobj, bucket, key)


async def _upload_bundle_to_s3(
    env: BundlerWorkerEnv,
    bundle_id: str,
    output_format: str,
    archive_path: Path,
    s3_config: dict | None,
) -> str:
    s3_key = f"bundles/{bundle_id}/{output_format}.tar.gz"
    s3_storage = _get_s3_storage(env, s3_config)

    async with s3_storage.session.client(
        "s3",
        endpoint_url=s3_storage.config.endpoint_url,
    ) as s3:
        logger.info("uploading_to_s3", bundle_id=bundle_id, key=s3_key)

        with open(archive_path, "rb") as f:
            await _retrying_upload_fileobj(s3, f, s3_storage.config.bucket, s3_key)

    return s3_key


def _get_s3_storage(env: BundlerWorkerEnv, s3_config: dict | None) -> S3Storage:
    if s3_config:
        return S3Storage(S3Config(**s3_config))
    return env.s3_storage


async def _format_bundle(
    output_format: str,
    index: doc_models.DocIndex,
    pages: dict[str, doc_models.DocPage],
    output_dir: Path,
    mermaid_render_mode: mermaid_render.MermaidRenderMode = "fence",
) -> None:
    format_lower = output_format.lower()

    match format_lower:
        case "mkdocs":
            formatter = MkDocsFormatter()
            await mkdocs.format_bundle(formatter, index, pages, output_dir, mermaid_render_mode)
            await mkdocs.generate_config(
                formatter,
                output_dir,
                {"navigation": index.navigation},
            )
            await mkdocs.generate_dockerfile(formatter, output_dir)
        case "nextra":
            formatter = NextraFormatter()
            await nextra.format_bundle(formatter, index, pages, output_dir, mermaid_render_mode)
            await nextra.generate_config(
                formatter,
                output_dir,
                {"project_name": "documentation", "navigation": index.navigation},
            )
            await nextra.generate_dockerfile(formatter, output_dir)
        case "sphinx":
            formatter = SphinxFormatter()
            await sphinx.format_bundle(formatter, index, pages, output_dir, mermaid_render_mode)
            await sphinx.generate_config(
                formatter,
                output_dir,
                {"project_name": "Documentation"},
            )
            await sphinx.generate_dockerfile(formatter, output_dir)
        case "gfm":
            formatter = GFMFormatter()
            await gfm.format_bundle(formatter, index, pages, output_dir, mermaid_render_mode)
        case "yfm":
            formatter = YFMFormatter()
            await yfm.format_bundle(formatter, index, pages, output_dir, mermaid_render_mode)
            await yfm.generate_config(
                formatter,
                output_dir,
                {
                    "site_name": "Documentation",
                    "navigation": index.navigation,
                    "pages": pages,
                },
            )
            await yfm.generate_dockerfile(formatter, output_dir)
        case _:
            raise ValueError(f"Unsupported format: {output_format}")


def _resolve_mermaid_mode(
    requested: str | None,
    output_format: str,
) -> mermaid_render.MermaidRenderMode:
    """Decide the effective Mermaid render mode for a bundle.

    When the client doesn't send ``mermaid_render`` we pick a per-format
    default: ``svg`` for GFM and Sphinx (likely consumed by static viewers
    that don't run Mermaid), and ``fence`` for MkDocs/Nextra (their themes
    ship a JS-side renderer).
    """
    if requested in ("fence", "svg", "png"):
        return requested  # type: ignore[return-value]

    fmt = output_format.lower()
    if fmt in ("gfm", "sphinx"):
        return "svg"
    return "fence"
