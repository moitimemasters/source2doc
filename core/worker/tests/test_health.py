"""Worker liveness HTTP server tests (TZ РЗВ-03)."""

from __future__ import annotations

import asyncio
import json
import socket

import pytest

from worker.health import HealthState, WorkerHealthServer


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _http_get(host: str, port: int, path: str) -> tuple[int, bytes]:
    reader, writer = await asyncio.open_connection(host, port)
    request = f"GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode()
    writer.write(request)
    await writer.drain()
    raw = await reader.read()
    writer.close()
    await writer.wait_closed()

    head, _, body = raw.partition(b"\r\n\r\n")
    status_line = head.split(b"\r\n", 1)[0]
    status_code = int(status_line.split(b" ", 2)[1])
    return status_code, body


async def _start_server(state: HealthState, port: int) -> tuple[WorkerHealthServer, asyncio.Task]:
    server = WorkerHealthServer(state=state, host="127.0.0.1", port=port)
    await server.start()
    serve_task = asyncio.create_task(server.serve_forever())
    return server, serve_task


async def _stop_server(server: WorkerHealthServer, serve_task: asyncio.Task) -> None:
    await server.stop()
    serve_task.cancel()
    try:
        await serve_task
    except (asyncio.CancelledError, Exception):
        pass


@pytest.mark.asyncio
async def test_health_returns_ok_payload_when_heartbeat_fresh() -> None:
    port = _free_port()
    state = HealthState(worker_mode="docgen", worker_id="worker-test-1")
    server, serve_task = await _start_server(state, port)

    try:
        status, body = await _http_get("127.0.0.1", port, "/health")
        assert status == 200
        payload = json.loads(body)
        assert payload["status"] == "ok"
        assert payload["worker"] == "docgen"
        assert payload["worker_id"] == "worker-test-1"
    finally:
        await _stop_server(server, serve_task)


@pytest.mark.asyncio
async def test_health_returns_503_when_heartbeat_stale() -> None:
    port = _free_port()
    state = HealthState(worker_mode="repos", worker_id="worker-test-stale")
    # Force the heartbeat to be ancient so the probe trips immediately.
    state.last_heartbeat = state.last_heartbeat - 1000.0
    server, serve_task = await _start_server(state, port)

    try:
        status, body = await _http_get("127.0.0.1", port, "/health")
        assert status == 503
        payload = json.loads(body)
        assert payload["status"] == "stale"
    finally:
        await _stop_server(server, serve_task)


@pytest.mark.asyncio
async def test_unknown_path_returns_404() -> None:
    port = _free_port()
    state = HealthState(worker_mode="bundler", worker_id="worker-test-2")
    server, serve_task = await _start_server(state, port)

    try:
        status, _ = await _http_get("127.0.0.1", port, "/unknown")
        assert status == 404
    finally:
        await _stop_server(server, serve_task)
