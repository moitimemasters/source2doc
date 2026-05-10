import asyncio
import os
from pathlib import Path
import sys

import typer

from worker.bundler.worker import BundlerWorker
from worker.codetour.worker import CodetourWorker
from worker.config import DEFAULT_HEALTH_PORTS, GatewayWorkerConfig, get_worker_config
from worker.docgen.service.worker import DocGenServiceWorker
from worker.health import HealthState, WorkerHealthServer
from worker.lifecycle import WorkerLifecycle
from worker.prdoc.worker import PRDocWorker
from worker.repos.worker import RepoWorker


app = typer.Typer()


def _resolve_health_port(config: GatewayWorkerConfig, mode: str) -> int:
    # Resolution order: explicit config.health_port → $HEALTH_PORT env →
    # per-mode default. The env var is the docker-compose-friendly knob.
    if config.health_port is not None:
        return config.health_port
    env_port = os.environ.get("HEALTH_PORT")
    if env_port:
        return int(env_port)
    return DEFAULT_HEALTH_PORTS[mode]


def _build_health(config: GatewayWorkerConfig, mode: str) -> tuple[HealthState, WorkerHealthServer]:
    port = _resolve_health_port(config, mode)
    state = HealthState(worker_mode=mode, worker_id=config.worker_id)
    server = WorkerHealthServer(state=state, host=config.health_host, port=port)
    return state, server


def _run_with_lifecycle(worker, config: GatewayWorkerConfig, mode: str) -> None:
    health_state, health_server = _build_health(config, mode)
    lifecycle = WorkerLifecycle(
        worker,
        health_server=health_server,
        health_state=health_state,
    )

    try:
        asyncio.run(lifecycle.run())
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        sys.exit(1)


@app.command()
def docgen(
    config_file: Path = typer.Option(
        "config.yaml",
        help="Path to config file",
    ),
) -> None:
    config = get_worker_config(config_file)
    worker = DocGenServiceWorker(config)
    _run_with_lifecycle(worker, config, "docgen")


@app.command()
def repos(
    config_file: Path = typer.Option(
        "config.yaml",
        help="Path to config file",
    ),
) -> None:
    config = get_worker_config(config_file)
    worker = RepoWorker(config)
    _run_with_lifecycle(worker, config, "repos")


@app.command()
def bundler(
    config_file: Path = typer.Option(
        "config.yaml",
        help="Path to config file",
    ),
) -> None:
    config = get_worker_config(config_file)
    worker = BundlerWorker(config)
    _run_with_lifecycle(worker, config, "bundler")


@app.command()
def codetour(
    config_file: Path = typer.Option(
        "config.yaml",
        help="Path to config file",
    ),
) -> None:
    config = get_worker_config(config_file)
    worker = CodetourWorker(config)
    _run_with_lifecycle(worker, config, "codetour")


@app.command()
def prdoc(
    config_file: Path = typer.Option(
        "config.yaml",
        help="Path to config file",
    ),
) -> None:
    """Generate PR microdoc summaries from diff snapshots (closes ИНТ-02 / ГЕН-06)."""
    config = get_worker_config(config_file)
    worker = PRDocWorker(config)
    _run_with_lifecycle(worker, config, "prdoc")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
