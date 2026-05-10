from __future__ import annotations

import asyncio
from pathlib import Path
import uuid

import qdrant_client
import structlog
import typer

import source2doc.logging as logging
import source2doc.storage.codetour as codetour_storage

from codetour_core.config import loader
import codetour_core.generator as generator
import codetour_core.models as models


app = typer.Typer()


@app.command()
def generate(
    query: str = typer.Argument(..., help="User query for the code tour"),
    generation_id: str = typer.Argument(..., help="Generation ID from documentation generation"),
    config_path: Path = typer.Option("config.yaml", help="Path to config file"),
    prompt_path: Path = typer.Option(
        "configs/agents/codetour_generator.yaml",
        help="Path to prompt config",
    ),
    max_steps: int = typer.Option(10, help="Maximum number of steps in the tour"),
) -> None:
    asyncio.run(generate_async(query, generation_id, config_path, prompt_path, max_steps))


async def generate_async(
    query: str,
    generation_id_str: str,
    config_path: Path,
    prompt_path: Path,
    max_steps: int,
) -> None:
    app_config = loader.load_config(config_path)
    prompt_config = loader.load_prompt(prompt_path)

    logging.configure_logging(app_config.logging.level)
    logger = logging.get_logger(__name__)

    generation_id = uuid.UUID(generation_id_str)
    tour_id = uuid.uuid4()
    structlog.contextvars.bind_contextvars(tour_id=str(tour_id), generation_id=str(generation_id))

    logger.info(
        "codetour_generation_started",
        tour_id=str(tour_id),
        generation_id=str(generation_id),
        max_steps=max_steps,
    )

    qdrant = qdrant_client.QdrantClient(
        url=app_config.qdrant.url,
        api_key=app_config.qdrant.api_key,
    )

    storage = codetour_storage.CodetourStorage(app_config.postgres.connection_string)

    await storage.connect()

    try:
        gen = generator.CodetourGenerator(
            llm_config=app_config.llm,
            qdrant_client=qdrant,
            storage=storage,
            prompt_config=prompt_config,
        )

        request = models.CodeTourGenerationRequest(
            tour_id=tour_id,
            query=query,
            generation_id=generation_id,
            qdrant_collection=app_config.qdrant.collection,
            max_steps=max_steps,
        )

        tour = await gen.generate(request)

        logger.info(
            "codetour_generation_completed",
            tour_id=str(tour.tour_id),
            generation_id=str(generation_id),
            title=tour.title,
            steps_count=len(tour.steps),
        )

    finally:
        await storage.close()
        structlog.contextvars.clear_contextvars()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
