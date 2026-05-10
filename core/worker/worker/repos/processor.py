import asyncio
from pathlib import Path
from uuid import UUID

from source2doc import get_logger

from worker.repos.env import RepoWorkerEnv


logger = get_logger(__name__)


async def process_repository_upload(
    env: RepoWorkerEnv,
    task_info: dict,
) -> None:
    repo_id = task_info["repo_id"]
    source_type = task_info["source_type"]
    source_data = task_info["source_data"]

    logger.info(
        "processing_repository_upload",
        repo_id=repo_id,
        source_type=source_type,
    )

    commit_sha: str | None = None
    if source_type == "git":
        s3_key, commit_sha = await _process_git_repository(env, repo_id, source_data)
    elif source_type == "archive":
        s3_key, commit_sha = await _process_archive_repository(env, repo_id, source_data)
    else:
        raise ValueError(f"Unsupported source type: {source_type}")

    await env.pg_storage.update_repository(
        UUID(repo_id),
        s3_key=s3_key,
        commit_sha=commit_sha,
    )

    logger.info(
        "repository_upload_completed",
        repo_id=repo_id,
        s3_key=s3_key,
        commit_sha=commit_sha[:8] if commit_sha else None,
    )


async def _resolve_commit_sha(repo_path: Path) -> str | None:
    """Best-effort `git rev-parse HEAD` against an extracted repo.

    Returns ``None`` when the path is not a git working tree (typical for
    plain archive uploads) — the docgen pipeline tolerates a missing SHA
    and the UI just hides the link.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(repo_path),
            "rev-parse",
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.debug(
                "rev_parse_unavailable",
                path=str(repo_path),
                returncode=proc.returncode,
                stderr=stderr.decode(errors="replace").strip()[:200],
            )
            return None
        sha = stdout.decode(errors="replace").strip()
        return sha or None
    except FileNotFoundError:
        # `git` not on PATH — exceedingly unlikely in the worker container,
        # but treat the same as "no SHA available".
        logger.warning("git_binary_missing")
        return None


async def _process_git_repository(
    env: RepoWorkerEnv,
    repo_id: str,
    source_data: dict,
) -> tuple[str, str | None]:
    import tempfile

    git_url = source_data["url"]
    branch = source_data.get("branch") or None
    target_commit = source_data.get("commit_sha") or None

    logger.info(
        "cloning_git_repository",
        repo_id=repo_id,
        url=git_url,
        branch=branch or "<default>",
        target_commit=target_commit or "<HEAD>",
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        clone_path = temp_path / "repo"

        # Full clone (no --depth) so the docgen / codetour agents can later use
        # git blame and git log to ground their explanations in commit history.
        clone_args = ["git", "clone"]
        if branch:
            clone_args.extend(["--branch", branch])
        clone_args.extend([git_url, str(clone_path)])

        process = await asyncio.create_subprocess_exec(
            *clone_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode(errors="replace").strip() or "unknown error"
            logger.error(
                "git_clone_failed",
                repo_id=repo_id,
                url=git_url,
                branch=branch or "<default>",
                returncode=process.returncode,
                stderr=error_msg,
            )
            if branch and "Remote branch" in error_msg and "not found" in error_msg:
                raise RuntimeError(
                    f"Branch '{branch}' not found in {git_url}. "
                    f"Leave branch empty to use the repository's default branch."
                )
            raise RuntimeError(f"Git clone failed: {error_msg}")

        logger.info("git_clone_completed", repo_id=repo_id)

        # Optional pin to a specific commit / tag / SHA. We do this after
        # the full clone so the .git directory still has the full history
        # available for later git blame / log calls inside the docgen
        # agents — only the working tree moves to ``target_commit``.
        if target_commit:
            checkout = await asyncio.create_subprocess_exec(
                "git", "-C", str(clone_path), "checkout", "--detach", target_commit,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await checkout.communicate()
            if checkout.returncode != 0:
                error_msg = stderr.decode(errors="replace").strip() or "unknown error"
                logger.error(
                    "git_checkout_failed",
                    repo_id=repo_id,
                    target_commit=target_commit,
                    stderr=error_msg,
                )
                raise RuntimeError(
                    f"git checkout {target_commit!r} failed: {error_msg}"
                )
            logger.info(
                "git_checkout_completed",
                repo_id=repo_id,
                target_commit=target_commit,
            )

        # Resolve HEAD before we hand the directory off to the S3 uploader —
        # the upload doesn't move the tree but we want the SHA captured in
        # the same logical step so a later refactor of upload_repository
        # can't accidentally break the invariant.
        commit_sha = await _resolve_commit_sha(clone_path)
        if commit_sha is None:
            logger.warning(
                "git_clone_missing_head_sha",
                repo_id=repo_id,
                url=git_url,
            )

        s3_key = await env.s3_storage.upload_repository(repo_id, clone_path)
        return s3_key, commit_sha


async def _process_archive_repository(
    env: RepoWorkerEnv,
    repo_id: str,
    source_data: dict,
) -> tuple[str, str | None]:
    import tarfile
    import tempfile

    archive_path = Path(source_data["path"])

    logger.info("extracting_archive", repo_id=repo_id, path=str(archive_path))

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        extract_path = temp_path / "extracted"
        extract_path.mkdir()

        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(extract_path)

        extracted_dirs = [d for d in extract_path.iterdir() if d.is_dir()]
        if not extracted_dirs:
            raise ValueError("Archive must contain at least one directory")

        repo_path = extracted_dirs[0]

        # If the user happened to upload an archive with a `.git` directory,
        # capture HEAD just like for git-cloned sources. Otherwise this
        # silently returns None — the page-level commit_sha will be NULL.
        commit_sha = await _resolve_commit_sha(repo_path)

        s3_key = await env.s3_storage.upload_repository(repo_id, repo_path)
        return s3_key, commit_sha
