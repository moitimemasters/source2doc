import json
import typing as tp
from urllib.parse import quote
import uuid

from fastapi.responses import StreamingResponse
import redis.asyncio as aioredis
import structlog

from source2doc.config import PostgresConfig
from source2doc.resilience import s3_retry
from source2doc.storage import S3Storage


@s3_retry()
async def _retrying_list_objects_v2(client, bucket: str, prefix: str):
    return await client.list_objects_v2(Bucket=bucket, Prefix=prefix)


@s3_retry()
async def _retrying_get_object(client, bucket: str, key: str):
    return await client.get_object(Bucket=bucket, Key=key)


BUNDLER_STREAM = "tasks:bundler"
BUNDLER_CONSUMER_GROUP = "bundler-workers"


def _set_logfire_trace_attribute(trace_id: str) -> None:
    """Best-effort tag the active logfire span with our trace_id."""
    try:
        import logfire

        logfire.current_span().set_attribute("trace_id", trace_id)
    except Exception:  # noqa: BLE001
        pass


async def create_bundle_export_task(
    request_data: dict,
    postgres_config: PostgresConfig,
    redis: aioredis.Redis,
) -> str:
    trace_id = uuid.uuid4().hex

    structlog.contextvars.bind_contextvars(
        trace_id=trace_id,
        bundle_id=str(request_data.get("bundle_id")),
        generation_id=str(request_data.get("generation_id")),
    )
    _set_logfire_trace_attribute(trace_id)

    try:
        task_info = {
            "bundle_id": request_data["bundle_id"],
            "generation_id": request_data["generation_id"],
            "trace_id": trace_id,
            "format": request_data["format"],
            "postgres_connection_string": postgres_config.connection_string,
            "s3_config": request_data.get("s3_config"),
            "mermaid_render": request_data.get("mermaid_render"),
        }

        await _ensure_consumer_group(redis, BUNDLER_STREAM, BUNDLER_CONSUMER_GROUP)

        await redis.xadd(
            BUNDLER_STREAM,
            {
                "type": "bundle.export_requested",
                "data": json.dumps(task_info),
            },
        )
        return trace_id
    finally:
        structlog.contextvars.clear_contextvars()


async def list_bundle_exports(s3: S3Storage, bundle_id: int) -> list[dict]:
    """List exported bundle archives from S3 for a given bundle.

    Bundler worker uploads with key: bundles/{bundle_id}/{format}.tar.gz
    See [_upload_bundle_to_s3()](core/worker/worker/bundler/processor.py:104).
    """

    prefix = f"bundles/{bundle_id}/"

    # aioboto3 typing stubs are incomplete; cast to Any for type checkers.
    client_cm = tp.cast(
        tp.Any,
        s3.session.client(
            "s3",
            endpoint_url=s3.config.endpoint_url,
        ),
    )

    async with client_cm as client:
        response = await _retrying_list_objects_v2(client, s3.config.bucket, prefix)

        exports: list[dict] = []
        for obj in response.get("Contents", []) or []:
            key = obj.get("Key")
            if not key or not key.endswith(".tar.gz"):
                continue

            # Expected: bundles/{bundle_id}/{format}.tar.gz
            filename = key.split("/")[-1]
            fmt = filename[: -len(".tar.gz")]

            exports.append(
                {
                    "bundle_id": bundle_id,
                    "format": fmt,
                    "s3_key": key,
                    "size": obj.get("Size"),
                    "last_modified": obj.get("LastModified").isoformat()
                    if obj.get("LastModified")
                    else None,
                }
            )

        exports.sort(key=lambda e: e.get("format") or "")
        return exports


async def download_bundle_export(s3: S3Storage, s3_key: str) -> StreamingResponse:
    """Stream a bundle export archive from S3.

    Note: we validate key prefix to avoid arbitrary object download.
    """

    if not s3_key.startswith("bundles/") or not s3_key.endswith(".tar.gz"):
        raise ValueError(f"Invalid export key: {s3_key}")

    async def _iterator():
        # aioboto3 typing stubs are incomplete; cast to Any for type checkers.
        client_cm = tp.cast(
            tp.Any,
            s3.session.client(
                "s3",
                endpoint_url=s3.config.endpoint_url,
            ),
        )

        async with client_cm as client:
            obj = await _retrying_get_object(client, s3.config.bucket, s3_key)
            body = obj["Body"]
            async for chunk in body.iter_chunks(chunk_size=1024 * 1024):
                yield chunk

    filename = s3_key.split("/")[-1]

    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "Content-Type": "application/gzip",
    }

    return StreamingResponse(_iterator(), headers=headers)


async def _ensure_consumer_group(
    redis: aioredis.Redis,
    stream_name: str,
    group_name: str,
) -> None:
    try:
        await redis.xgroup_create(
            name=stream_name,
            groupname=group_name,
            id="0",
            mkstream=True,
        )
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise
