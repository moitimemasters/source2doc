"""Tiny asyncio HTTP server that answers ``GET /health`` for a worker.

Workers are not HTTP services, so we deliberately avoid pulling in FastAPI /
Starlette / aiohttp just to expose a single liveness endpoint. The server
runs as a background task alongside the Redis-stream consumer loop and
shuts down cleanly when the lifecycle cancels it.

Liveness model
--------------

A :class:`HealthState` is shared between:

* the worker's main loop (the ``WorkerLifecycle`` ticks
  :meth:`HealthState.mark_alive` on every shutdown-event poll, and the
  consumer loop's ``running()`` callback ticks it on every iteration) and
* this HTTP server (returns ``200`` while ``last_heartbeat`` is recent,
  ``503`` once it goes stale).

If the consumer loop wedges, deadlocks, or stops scheduling, the timestamp
stops advancing and the probe trips. Dependency health (postgres / redis /
qdrant / s3) is the gateway's job — see :mod:`source2doc.health`.

Response body (200)::

    {"status": "ok", "worker": "<mode>", "worker_id": "<id>"}

Response body (503, stale heartbeat)::

    {"status": "stale", "worker": "<mode>", "worker_id": "<id>",
     "last_heartbeat_age_s": 31.4}
"""

from __future__ import annotations

import asyncio
import dataclasses as dc
import json
import time
import typing as tp

from source2doc.logging import get_logger


logger = get_logger(__name__)


DEFAULT_HEALTH_PORT: int = 8080
DEFAULT_HEARTBEAT_STALE_AFTER_S: float = 30.0


@dc.dataclass
class HealthState:
    """Mutable liveness state shared between the consumer loop and the HTTP server."""

    worker_mode: str
    worker_id: str
    started_at: float = dc.field(default_factory=time.monotonic)
    last_heartbeat: float = dc.field(default_factory=time.monotonic)
    stale_after_s: float = DEFAULT_HEARTBEAT_STALE_AFTER_S

    def mark_alive(self) -> None:
        self.last_heartbeat = time.monotonic()

    def heartbeat_age_s(self) -> float:
        return time.monotonic() - self.last_heartbeat

    def is_fresh(self) -> bool:
        return self.heartbeat_age_s() <= self.stale_after_s


def _build_response(status_code: int, body: dict[str, tp.Any]) -> bytes:
    payload = json.dumps(body).encode("utf-8")
    reason = "OK" if status_code == 200 else _STATUS_REASONS.get(status_code, "Error")
    headers = (
        f"HTTP/1.1 {status_code} {reason}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("ascii")
    return headers + payload


_STATUS_REASONS: dict[int, str] = {
    200: "OK",
    404: "Not Found",
    503: "Service Unavailable",
}


class WorkerHealthServer:
    """Background HTTP listener serving ``GET /health`` for one worker."""

    def __init__(
        self,
        state: HealthState,
        host: str = "0.0.0.0",
        port: int = DEFAULT_HEALTH_PORT,
    ) -> None:
        self.state = state
        self.host = host
        self.port = port
        self._server: asyncio.base_events.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection,
            host=self.host,
            port=self.port,
        )
        logger.info(
            "health_server_started",
            worker=self.state.worker_mode,
            worker_id=self.state.worker_id,
            host=self.host,
            port=self.port,
        )

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        try:
            await self._server.wait_closed()
        except Exception as exc:  # noqa: BLE001 — never raise during shutdown
            logger.warning("health_server_close_error", error=str(exc))
        self._server = None
        logger.info(
            "health_server_stopped",
            worker=self.state.worker_mode,
            worker_id=self.state.worker_id,
        )

    async def serve_forever(self) -> None:
        if self._server is None:
            raise RuntimeError("WorkerHealthServer.start() must be awaited first")
        async with self._server:
            await self._server.serve_forever()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            try:
                request_head = await asyncio.wait_for(
                    reader.readuntil(b"\r\n\r\n"),
                    timeout=2.0,
                )
            except (TimeoutError, asyncio.IncompleteReadError, ValueError):
                return

            request_line = request_head.split(b"\r\n", 1)[0]
            parts = request_line.split(b" ")
            method = parts[0] if parts else b""
            target = parts[1] if len(parts) > 1 else b""

            response = self._dispatch(method, target)
            writer.write(response)
            try:
                await writer.drain()
            except (ConnectionError, OSError):
                # Client hung up before we finished writing — fine for a probe.
                return
        except Exception as exc:  # noqa: BLE001 — never crash the server task
            logger.warning("health_request_handler_error", error=str(exc))
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    def _dispatch(self, method: bytes, target: bytes) -> bytes:
        if method != b"GET":
            return _build_response(404, {"error": "not_found"})
        path_only = target.split(b"?", 1)[0]
        if path_only != b"/health":
            return _build_response(404, {"error": "not_found"})

        fresh = self.state.is_fresh()
        body: dict[str, tp.Any] = {
            "status": "ok" if fresh else "stale",
            "worker": self.state.worker_mode,
            "worker_id": self.state.worker_id,
            "uptime_s": round(time.monotonic() - self.state.started_at, 3),
            "last_heartbeat_age_s": round(self.state.heartbeat_age_s(), 3),
        }
        return _build_response(200 if fresh else 503, body)
