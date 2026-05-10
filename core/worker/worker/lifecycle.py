import asyncio
import signal
from typing import Protocol

from source2doc.logging import get_logger

from worker.health import HealthState, WorkerHealthServer


# Heartbeat tick interval. The HealthState defaults to a 30s staleness
# threshold, so 5s gives 6 ticks of headroom before a probe trips.
_HEARTBEAT_INTERVAL_S: float = 5.0


class Worker(Protocol):
    async def async_init(self) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class WorkerLifecycle:
    def __init__(
        self,
        worker: Worker,
        health_server: WorkerHealthServer | None = None,
        health_state: HealthState | None = None,
    ):
        self.worker = worker
        self.health_server = health_server
        self.health_state = health_state
        self.shutdown_event = asyncio.Event()
        self.logger = get_logger(__name__)
        self.loop: asyncio.AbstractEventLoop | None = None

    def _setup_signals(self) -> None:
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, sig: int, frame) -> None:
        self.logger.info("shutdown_signal_received", signal=sig)

        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.shutdown_event.set)
        else:
            self.shutdown_event.set()

    async def _wait_for_shutdown(
        self,
        worker_task: asyncio.Task,
        extra_tasks: list[asyncio.Task] | None = None,
    ) -> None:
        shutdown_wait_task = asyncio.create_task(self.shutdown_event.wait())

        watch_tasks: list[asyncio.Task] = [worker_task, shutdown_wait_task]
        if extra_tasks:
            watch_tasks.extend(extra_tasks)

        done, pending = await asyncio.wait(
            watch_tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if self.shutdown_event.is_set():
            await self._graceful_shutdown(worker_task)

        await self._cancel_pending(pending)

    async def _graceful_shutdown(self, worker_task: asyncio.Task) -> None:
        self.logger.info("graceful_shutdown_started")
        await self.worker.stop()

        if not worker_task.done():
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

        self.logger.info("graceful_shutdown_completed")

    async def _cancel_pending(self, tasks: set[asyncio.Task]) -> None:
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _heartbeat_loop(self) -> None:
        """Tick the shared HealthState while the lifecycle is alive.

        We rely on a periodic tick rather than instrumenting every consumer
        iteration: any wedge in the asyncio loop will pause this task too,
        and the probe will trip on its own.
        """
        if self.health_state is None:
            return
        try:
            while True:
                self.health_state.mark_alive()
                await asyncio.sleep(_HEARTBEAT_INTERVAL_S)
        except asyncio.CancelledError:
            return

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()

        await self.worker.async_init()
        self._setup_signals()

        health_task: asyncio.Task | None = None
        heartbeat_task: asyncio.Task | None = None
        if self.health_server is not None:
            await self.health_server.start()
            health_task = asyncio.create_task(self.health_server.serve_forever())
        if self.health_state is not None:
            heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        worker_task = asyncio.create_task(self.worker.start())

        extras: list[asyncio.Task] = []
        if health_task is not None:
            extras.append(health_task)
        if heartbeat_task is not None:
            extras.append(heartbeat_task)

        try:
            await self._wait_for_shutdown(worker_task, extras or None)
        except Exception as e:
            self.logger.exception("lifecycle_error", error=str(e))
            await self.worker.stop()
            raise
        finally:
            for task in (heartbeat_task, health_task):
                if task is not None and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    except Exception as exc:  # noqa: BLE001
                        self.logger.warning("lifecycle_extra_task_cleanup_error", error=str(exc))
            if self.health_server is not None:
                await self.health_server.stop()
