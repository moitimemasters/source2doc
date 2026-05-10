from pathlib import Path
import tarfile
import tempfile
import typing as tp

import aioboto3
import botocore.exceptions
from boto3.s3.transfer import TransferConfig
from botocore.config import Config as BotoConfig

from source2doc.config import S3Config
from source2doc.logging import get_logger
from source2doc.resilience import s3_retry


# LocalStack 4.x rejects the new aioboto3 default that adds a CRC32 trailer to
# multipart UploadPart requests. Force the legacy "only when the operation
# actually requires a checksum" behaviour so dev S3 (LocalStack / MinIO) works.
_BOTO_CONFIG = BotoConfig(
    request_checksum_calculation="when_required",
    response_checksum_validation="when_required",
)

# Bypass multipart entirely: with a 5 GiB single-part threshold the SDK uses
# put_object for any practical archive, sidestepping the broken UploadPart
# checksum negotiation against LocalStack.
_TRANSFER_CONFIG = TransferConfig(
    multipart_threshold=5 * 1024 * 1024 * 1024,
    multipart_chunksize=5 * 1024 * 1024 * 1024,
    use_threads=False,
)


logger = get_logger(__name__)


class S3Storage:
    def __init__(self, config: S3Config) -> None:
        self.config = config
        self.resilience = config.resilience
        self.session = aioboto3.Session(
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name=config.region,
        )

    @s3_retry()
    async def _upload_fileobj(self, s3: tp.Any, fileobj: tp.Any, bucket: str, key: str) -> None:
        await s3.upload_fileobj(fileobj, bucket, key, Config=_TRANSFER_CONFIG)

    @s3_retry()
    async def _download_fileobj(self, s3: tp.Any, bucket: str, key: str, fileobj: tp.Any) -> None:
        await s3.download_fileobj(bucket, key, fileobj, Config=_TRANSFER_CONFIG)

    @s3_retry()
    async def _head_object(self, s3: tp.Any, bucket: str, key: str) -> tp.Any:
        return await s3.head_object(Bucket=bucket, Key=key)

    @s3_retry()
    async def _delete_object(self, s3: tp.Any, bucket: str, key: str) -> tp.Any:
        return await s3.delete_object(Bucket=bucket, Key=key)

    @s3_retry()
    async def _list_objects_v2(self, s3: tp.Any, bucket: str, prefix: str) -> tp.Any:
        return await s3.list_objects_v2(Bucket=bucket, Prefix=prefix)

    async def upload_repository(
        self,
        repo_id: str,
        source_path: Path,
    ) -> str:
        if not source_path.exists() or not source_path.is_dir():
            raise ValueError(f"Source path does not exist or is not a directory: {source_path}")

        # delete=False so we can reopen the file for upload after the writer
        # closes the tar; unlink in a finally so a mid-flight failure does
        # not leave a stale archive in /tmp.
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)

        try:
            logger.info("creating_archive", repo_id=repo_id, source=str(source_path))

            with tarfile.open(tmp_path, "w:gz") as tar:
                tar.add(source_path, arcname=source_path.name)

            s3_key = f"repos/{repo_id}.tar.gz"

            async with self.session.client(
                "s3",
                endpoint_url=self.config.endpoint_url,
            ) as s3:
                logger.info("uploading_to_s3", repo_id=repo_id, key=s3_key)

                with open(tmp_path, "rb") as f:
                    await self._upload_fileobj(s3, f, self.config.bucket, s3_key)

            logger.info("upload_completed", repo_id=repo_id, key=s3_key)
            return s3_key
        finally:
            tmp_path.unlink(missing_ok=True)

    async def download_repository(
        self,
        repo_id: str,
        target_path: Path,
    ) -> Path:
        s3_key = f"repos/{repo_id}.tar.gz"

        async with self.session.client(
            "s3",
            endpoint_url=self.config.endpoint_url,
            config=_BOTO_CONFIG,
        ) as s3:
            logger.info("downloading_from_s3", repo_id=repo_id, key=s3_key)

            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp_file:
                tmp_path = Path(tmp_file.name)

            try:
                with open(tmp_path, "wb") as fout:
                    try:
                        await self._download_fileobj(s3, self.config.bucket, s3_key, fout)
                    except botocore.exceptions.ClientError as e:
                        if e.response["Error"]["Code"] == "404":
                            raise FileNotFoundError(
                                f"Repository not found: {repo_id}"
                            )
                        raise

                logger.info(
                    "extracting_archive",
                    repo_id=repo_id,
                    target=str(target_path),
                )

                target_path.mkdir(parents=True, exist_ok=True)

                with tarfile.open(tmp_path, "r:gz") as tar:
                    tar.extractall(target_path)
            finally:
                tmp_path.unlink(missing_ok=True)

            extracted_dirs = [d for d in target_path.iterdir() if d.is_dir()]
            if not extracted_dirs:
                raise RuntimeError(f"No directory found after extraction: {target_path}")

            extracted_path = extracted_dirs[0]
            logger.info("download_completed", repo_id=repo_id, path=str(extracted_path))

            return extracted_path

    async def repository_exists(self, repo_id: str) -> bool:
        s3_key = f"repos/{repo_id}.tar.gz"

        async with self.session.client(
            "s3",
            endpoint_url=self.config.endpoint_url,
            config=_BOTO_CONFIG,
        ) as s3:
            try:
                await self._head_object(s3, self.config.bucket, s3_key)
                return True
            except botocore.exceptions.ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    return False
                raise

    async def delete_repository(self, repo_id: str) -> None:
        s3_key = f"repos/{repo_id}.tar.gz"

        async with self.session.client(
            "s3",
            endpoint_url=self.config.endpoint_url,
            config=_BOTO_CONFIG,
        ) as s3:
            logger.info("deleting_from_s3", repo_id=repo_id, key=s3_key)
            await self._delete_object(s3, self.config.bucket, s3_key)
            logger.info("delete_completed", repo_id=repo_id)

    async def list_repositories(self) -> list[str]:
        async with self.session.client(
            "s3",
            endpoint_url=self.config.endpoint_url,
            config=_BOTO_CONFIG,
        ) as s3:
            response = await self._list_objects_v2(s3, self.config.bucket, "repos/")

            if "Contents" not in response:
                return []

            repo_ids = []
            for obj in response["Contents"]:
                key = obj["Key"]
                if key.startswith("repos/") and key.endswith(".tar.gz"):
                    repo_id = key[6:-7]
                    repo_ids.append(repo_id)

            return repo_ids
