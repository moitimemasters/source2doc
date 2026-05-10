import asyncio
from pathlib import Path
import uuid

import structlog
import typer

from source2doc import RedisEventBus, get_logger
from source2doc.logging import configure_logging
from source2doc.pipelines import DOCGEN

from docgen_core.config import loader as config_loader
from docgen_core.observability import setup_logfire
from docgen_core.workers import docgen_worker


app = typer.Typer()


@app.command()
def generate(
    path: Path = typer.Argument(..., help="Path to codebase"),
    config: Path = typer.Option("configs/config.yaml", help="Path to config file"),
    output: Path = typer.Option("documentation", help="Output directory"),
    clear_qdrant: bool = typer.Option(
        False,
        "--clear-qdrant",
        help="Clear Qdrant collection before indexing",
    ),
) -> None:
    asyncio.run(_generate_async(path, config, output, clear_qdrant))


async def _generate_async(
    path: Path,
    config_path: Path,
    output_dir: Path,
    clear_qdrant: bool,
) -> None:
    config = config_loader.load_config(config_path)

    configure_logging(config.logging.level)
    logger = get_logger(__name__)

    setup_logfire(config.logfire)

    logger.info("config_loaded", config_path=str(config_path))

    generation_id = uuid.uuid4()
    structlog.contextvars.bind_contextvars(generation_id=str(generation_id))

    logger.info("generation_started", path=str(path), output=str(output_dir))

    event_bus = RedisEventBus(config.redis, generation_id, pipeline=DOCGEN)
    await event_bus.connect()

    try:
        async with docgen_worker(config, event_bus) as env:
            if clear_qdrant:
                logger.info("clearing_qdrant", collection=config.qdrant.collection)
                await env.vectorstore.clear()
                logger.info("qdrant_cleared")

            result = await _run_and_wait(event_bus, generation_id, path)

        logger.info(
            "generation_completed",
            output_dir=result.get("output_dir", str(output_dir)),
            pages_count=result.get("pages_count", 0),
        )

        print("\n✅ Documentation generated successfully!")
        print(f"📁 Output directory: {result.get('output_dir', output_dir)}")
        print(f"📄 Pages created: {result.get('pages_count', 0)}")

    finally:
        await event_bus.close()
        structlog.contextvars.clear_contextvars()


async def _run_and_wait(
    event_bus: RedisEventBus,
    generation_id: uuid.UUID,
    path: Path,
) -> dict:
    result = None

    async def on_complete(data: dict) -> None:
        nonlocal result
        result = data

    event_bus.subscribe("generation.completed", on_complete)

    await event_bus.emit(
        "generation.requested",
        {
            "generation_id": str(generation_id),
            "path": str(path),
        },
    )

    while result is None:
        await asyncio.sleep(1)

    return result


def main() -> None:
    app()


if __name__ == "__main__":
    main()
