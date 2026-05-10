import asyncio
import collections.abc as cabc

import redis.asyncio as aioredis
import redis.exceptions as aioredis_exc

from source2doc.logging import get_logger

from worker.streams import consumer as consumer_mod


logger = get_logger(__name__)


async def watch_streams(
    redis: aioredis.Redis,
    pattern: str,
    consumer_group: str,
    consumer_name: str,
    handler: consumer_mod.MessageHandler,
    running: cabc.Callable[[], bool],
    scan_interval_seconds: float = 5.0,
    block_ms: int = 1000,
    min_idle_time_ms: int = 120000,
    max_retries: int = 3,
    task_ttl: int = 86400,
    semaphore: asyncio.Semaphore | None = None,
    concurrency: int = 1,
) -> None:
    """Discover streams matching ``pattern`` and consume them concurrently.

    When ``semaphore`` is provided it caps the global number of in-flight
    message dispatches across *all* discovered streams in this watcher.
    """
    known_streams: set[str] = set()
    stream_tasks: dict[str, asyncio.Task] = {}

    async def dispatch(stream_name: str, msg: consumer_mod.StreamMessage) -> None:
        await consumer_mod.dispatch_message(
            redis, stream_name, consumer_group, msg, handler,
            consumer_name, max_retries, task_ttl,
        )

    async def gated_dispatch(stream_name: str, msg: consumer_mod.StreamMessage) -> None:
        assert semaphore is not None
        async with semaphore:
            await dispatch(stream_name, msg)

    async def process_stream(stream_name: str) -> None:
        in_flight: set[asyncio.Task] = set()

        def schedule(msg: consumer_mod.StreamMessage) -> None:
            coro = (
                gated_dispatch(stream_name, msg)
                if semaphore is not None
                else dispatch(stream_name, msg)
            )
            task = asyncio.create_task(coro)
            in_flight.add(task)
            task.add_done_callback(in_flight.discard)

        try:
            await consumer_mod.ensure_consumer_group(redis, stream_name, consumer_group)

            pending = await consumer_mod.claim_pending_messages(
                redis, stream_name, consumer_group, consumer_name, min_idle_time_ms
            )
            for msg in pending:
                if semaphore is None:
                    await dispatch(stream_name, msg)
                else:
                    schedule(msg)

            poll_count = 1 if semaphore is None else max(1, concurrency)

            while running():
                try:
                    messages = await consumer_mod.read_stream_messages(
                        redis,
                        {stream_name: ">"},
                        consumer_group,
                        consumer_name,
                        count=poll_count,
                        block_ms=block_ms,
                    )
                    for msg in messages:
                        if semaphore is None:
                            await dispatch(stream_name, msg)
                        else:
                            schedule(msg)
                except asyncio.CancelledError:
                    break
                except aioredis_exc.ResponseError as e:
                    # NOGROUP = the stream or its consumer group was removed (manual
                    # cleanup, cancelled generation, TTL expiry). Stop processing —
                    # the top-level watcher loop will notice it's gone via SCAN.
                    if "NOGROUP" in str(e):
                        logger.info("stream_gone", stream=stream_name)
                        return
                    logger.exception("stream_consumer_error", stream=stream_name, error=str(e))
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.exception("stream_consumer_error", stream=stream_name, error=str(e))
                    await asyncio.sleep(1)

            if in_flight:
                await asyncio.gather(*in_flight, return_exceptions=True)

        except asyncio.CancelledError:
            for t in in_flight:
                t.cancel()
            await asyncio.gather(*in_flight, return_exceptions=True)
        except Exception as e:
            logger.exception("stream_processor_error", stream=stream_name, error=str(e))

    while running():
        try:
            current_streams = await consumer_mod.discover_streams(redis, pattern)
            current_set = set(current_streams)

            new_streams = current_set - known_streams
            for stream_name in new_streams:
                logger.info("discovered_new_stream", stream=stream_name)
                task = asyncio.create_task(process_stream(stream_name))
                stream_tasks[stream_name] = task
                known_streams.add(stream_name)

            # Drop streams that disappeared (cleanup / TTL / cancellation) so a
            # later reappearance is re-discovered, and finished tasks are reaped.
            for stale in list(known_streams - current_set):
                task = stream_tasks.pop(stale, None)
                if task and not task.done():
                    task.cancel()
                known_streams.discard(stale)

            await asyncio.sleep(scan_interval_seconds)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("stream_watcher_error", error=str(e))
            await asyncio.sleep(scan_interval_seconds)

    for task in stream_tasks.values():
        task.cancel()

    await asyncio.gather(*stream_tasks.values(), return_exceptions=True)
