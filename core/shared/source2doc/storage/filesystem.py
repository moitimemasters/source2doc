import abc
import asyncio
from fnmatch import fnmatch
import os
from pathlib import Path
import shutil
import tempfile

import aioboto3
import botocore.exceptions
import pathspec
from boto3.s3.transfer import TransferConfig
from botocore.config import Config as BotoConfig

from source2doc.config import S3Config
from source2doc.logging import get_logger
from source2doc.resilience import s3_retry


_BOTO_CONFIG = BotoConfig(
    request_checksum_calculation="when_required",
    response_checksum_validation="when_required",
)

# LocalStack returns CRC32 trailers that aiobotocore tries to verify against
# its own (incorrect) recompute. Force single-part GET so the checksum
# validation path is not exercised for archive downloads.
_TRANSFER_CONFIG = TransferConfig(
    multipart_threshold=5 * 1024 * 1024 * 1024,
    multipart_chunksize=5 * 1024 * 1024 * 1024,
    use_threads=False,
)


logger = get_logger(__name__)


# Directory names that are always pruned during the walk: VCS internals,
# dependency caches, build artefacts, IDE state. Filtered before any
# .gitignore processing because they are unconditionally noise.
EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        ".next",
        "dist",
        "build",
        "target",
        ".turbo",
        ".cache",
    }
)

# Lock files: huge, machine-generated, no documentation value.
LOCK_FILES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "uv.lock",
        "poetry.lock",
        "Cargo.lock",
        "Gemfile.lock",
        "composer.lock",
        "Pipfile.lock",
    }
)

# Binary extensions that the chunker / embedder cannot process meaningfully.
BINARY_EXTS = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff", ".heic",
        ".mp3", ".mp4", ".wav", ".ogg", ".webm", ".mov", ".avi", ".mkv", ".flac",
        ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
        ".so", ".dylib", ".dll", ".exe", ".bin", ".o", ".a", ".lib",
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
        ".pyc", ".pyo", ".class", ".jar", ".war",
        ".db", ".sqlite", ".sqlite3",
        ".wasm",
    }
)

# Per-file size cap. Skips minified bundles and big checked-in fixtures
# without breaking on the embedder.
MAX_FILE_BYTES = 1_000_000

# Extension → language label used downstream (chunk metadata, prompts).
LANGUAGE_BY_EXT: dict[str, str] = {
    ".py": "python", ".pyi": "python",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin", ".kts": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
    ".c": "c", ".h": "c",
    ".swift": "swift",
    ".scala": "scala", ".sc": "scala",
    ".clj": "clojure", ".cljs": "clojure", ".cljc": "clojure",
    ".ex": "elixir", ".exs": "elixir",
    ".erl": "erlang", ".hrl": "erlang",
    ".ml": "ocaml", ".mli": "ocaml",
    ".fs": "fsharp", ".fsx": "fsharp",
    ".vue": "vue",
    ".svelte": "svelte",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".fish": "shell",
    ".ps1": "powershell",
    ".lua": "lua",
    ".dart": "dart",
    ".r": "r", ".rmd": "r",
    ".jl": "julia",
    ".pl": "perl", ".pm": "perl",
    ".nim": "nim",
    ".zig": "zig",
    ".v": "v",
    ".sol": "solidity",
    ".md": "markdown", ".mdx": "markdown", ".markdown": "markdown",
    ".rst": "rst",
    ".json": "json", ".jsonc": "json", ".json5": "json",
    ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini", ".cfg": "ini",
    ".html": "html", ".htm": "html",
    ".css": "css",
    ".scss": "scss", ".sass": "sass", ".less": "less",
    ".sql": "sql",
    ".graphql": "graphql", ".gql": "graphql",
    ".proto": "protobuf",
    ".tf": "terraform", ".hcl": "hcl",
    ".dockerfile": "dockerfile",
    ".xml": "xml",
    ".tex": "latex",
}

_SPECIAL_FILENAMES: dict[str, str] = {
    "dockerfile": "dockerfile",
    "containerfile": "dockerfile",
    "makefile": "makefile",
    "gnumakefile": "makefile",
    "rakefile": "ruby",
    "gemfile": "ruby",
    "vagrantfile": "ruby",
    "cmakelists.txt": "cmake",
    "justfile": "make",
}


def detect_language(file_path: str) -> str:
    """Best-effort language tag from path. Falls back to ``text``."""

    p = Path(file_path)
    suffix = p.suffix.lower()
    if suffix in LANGUAGE_BY_EXT:
        return LANGUAGE_BY_EXT[suffix]
    name = p.name.lower()
    if name in _SPECIAL_FILENAMES:
        return _SPECIAL_FILENAMES[name]
    return "text"


def _load_gitignore_spec(base_path: Path) -> pathspec.PathSpec | None:
    lines: list[str] = []

    for candidate in (base_path / ".gitignore", base_path / ".git" / "info" / "exclude"):
        if not candidate.is_file():
            continue
        try:
            lines.extend(candidate.read_text(encoding="utf-8").splitlines())
        except (UnicodeDecodeError, OSError):
            continue

    if not lines:
        return None
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)


def _walk_repo_files(base_path: Path, pattern: str = "*") -> list[str]:
    """Walk ``base_path`` and return relative paths for documentable files.

    Excludes VCS dirs / dep caches / build artefacts (``EXCLUDED_DIRS``),
    files matched by the repo's root ``.gitignore`` + ``.git/info/exclude``,
    common lockfiles, and binary / oversized files. ``pattern`` applies as
    an additional fnmatch filter on the basename (default ``*``).
    """

    spec = _load_gitignore_spec(base_path)
    matched: list[str] = []

    for dirpath, dirnames, filenames in os.walk(base_path):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]

        rel_dir = Path(dirpath).relative_to(base_path)

        if spec is not None:
            kept_dirs = []
            for d in dirnames:
                rel_str = str(rel_dir / d) if str(rel_dir) != "." else d
                if not spec.match_file(rel_str + "/"):
                    kept_dirs.append(d)
            dirnames[:] = kept_dirs

        for filename in filenames:
            if filename in LOCK_FILES:
                continue

            rel = rel_dir / filename if str(rel_dir) != "." else Path(filename)
            rel_str = str(rel)

            if Path(filename).suffix.lower() in BINARY_EXTS:
                continue

            if spec is not None and spec.match_file(rel_str):
                continue

            if pattern != "*" and not fnmatch(filename, pattern):
                continue

            full = Path(dirpath) / filename
            try:
                if full.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue

            matched.append(rel_str)

    return matched


class FileSystem(abc.ABC):
    @abc.abstractmethod
    async def list_files(self, path: str = ".", pattern: str = "*") -> list[str]:
        pass

    @abc.abstractmethod
    async def read_file(self, path: str) -> str:
        pass

    @abc.abstractmethod
    async def file_exists(self, path: str) -> bool:
        pass


class LocalFileSystem(FileSystem):
    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path

    async def list_files(self, path: str = ".", pattern: str = "*") -> list[str]:
        full_path = self.base_path / path
        if full_path.is_file():
            rel = full_path.relative_to(self.base_path)
            if full_path.suffix.lower() in BINARY_EXTS or full_path.name in LOCK_FILES:
                return []
            return [str(rel)]

        return _walk_repo_files(full_path, pattern)

    async def read_file(self, path: str) -> str:
        full_path = self.base_path / path
        return full_path.read_text(encoding="utf-8")

    async def file_exists(self, path: str) -> bool:
        full_path = self.base_path / path
        return full_path.exists() and full_path.is_file()


class S3FileSystem(FileSystem):
    def __init__(self, config: S3Config, repo_id: str) -> None:
        self.config = config
        self.resilience = config.resilience
        self.repo_id = repo_id
        self.session = aioboto3.Session(
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name=config.region,
        )
        self._extracted_path: Path | None = None
        self._temp_dir: Path | None = None
        # Multiple tool calls can race and call _ensure_extracted() concurrently.
        # Guard extraction so we don't download/extract the same repo multiple times.
        self._extract_lock = asyncio.Lock()

    @s3_retry()
    async def _download_fileobj(self, s3, bucket: str, key: str, fileobj) -> None:
        await s3.download_fileobj(bucket, key, fileobj, Config=_TRANSFER_CONFIG)

    async def _ensure_extracted(self) -> Path:
        if self._extracted_path is not None:
            return self._extracted_path

        async with self._extract_lock:
            # Re-check under the lock in case another coroutine already extracted.
            if self._extracted_path is not None:
                return self._extracted_path

            s3_key = f"repos/{self.repo_id}.tar.gz"
            temp_dir = Path(tempfile.mkdtemp(prefix=f"repo-{self.repo_id}-"))
            self._temp_dir = temp_dir

            try:
                async with self.session.client(
                    "s3",
                    endpoint_url=self.config.endpoint_url,
                    config=_BOTO_CONFIG,
                ) as s3:
                    logger.info("downloading_repo", repo_id=self.repo_id, key=s3_key)

                    archive_path = temp_dir / "repo.tar.gz"

                    try:
                        with open(archive_path, "wb") as f:
                            await self._download_fileobj(
                                s3,
                                self.config.bucket,
                                s3_key,
                                f,
                            )
                    except botocore.exceptions.ClientError as e:
                        if e.response["Error"]["Code"] == "404":
                            raise FileNotFoundError(
                                f"Repository not found: {self.repo_id}"
                            )
                        raise

                    import tarfile

                    logger.info("extracting_repo", repo_id=self.repo_id)
                    extract_path = temp_dir / "extracted"
                    extract_path.mkdir()

                    with tarfile.open(archive_path, "r:gz") as tar:
                        tar.extractall(extract_path)

                    extracted_dirs = [d for d in extract_path.iterdir() if d.is_dir()]
                    if not extracted_dirs:
                        raise RuntimeError(
                            f"No directory found after extraction: {extract_path}"
                        )

                    self._extracted_path = extracted_dirs[0]
                    logger.info(
                        "repo_ready",
                        repo_id=self.repo_id,
                        path=str(self._extracted_path),
                    )

                    return self._extracted_path
            except BaseException:
                # Drop the temp dir on any failure so partial extractions cannot
                # accumulate. cleanup() is normally called from the finalize
                # handler, which never runs if extraction itself raises.
                shutil.rmtree(temp_dir, ignore_errors=True)
                self._temp_dir = None
                raise

    async def list_files(self, path: str = ".", pattern: str = "*") -> list[str]:
        base_path = await self._ensure_extracted()
        full_path = base_path / path

        if full_path.is_file():
            rel = full_path.relative_to(base_path)
            if full_path.suffix.lower() in BINARY_EXTS or full_path.name in LOCK_FILES:
                return []
            return [str(rel)]

        return _walk_repo_files(full_path, pattern)

    async def read_file(self, path: str) -> str:
        base_path = await self._ensure_extracted()
        full_path = base_path / path
        return full_path.read_text(encoding="utf-8")

    async def file_exists(self, path: str) -> bool:
        base_path = await self._ensure_extracted()
        full_path = base_path / path
        return full_path.exists() and full_path.is_file()

    def cleanup(self) -> None:
        temp_dir = self._temp_dir
        if temp_dir is None:
            return
        shutil.rmtree(temp_dir, ignore_errors=True)
        self._temp_dir = None
        self._extracted_path = None
        logger.info("cleanup_completed", repo_id=self.repo_id)

    def __del__(self) -> None:
        # Last-resort safety net: if the handler crashed before cleanup() ran,
        # GC will at least drop the temp dir. shutil is captured at module
        # scope above so this stays usable during interpreter shutdown.
        temp_dir = getattr(self, "_temp_dir", None)
        if temp_dir is not None:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
