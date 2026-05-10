"""Light wrapper around git that lets agents pull blame / log information
for a specific line range. The underlying repo is the unpacked tar.gz the
worker mounted via :class:`S3FileSystem`. If the repository was uploaded
without a ``.git`` directory, every method returns ``None`` so callers can
gracefully degrade — the agent is told via tools that history is unavailable.
"""

from __future__ import annotations

import asyncio
import dataclasses as dc
import datetime as dt
import re
from pathlib import Path

from source2doc.logging import get_logger


logger = get_logger(__name__)


@dc.dataclass
class CommitRef:
    sha: str
    short_sha: str
    author: str
    date: str  # ISO-8601
    message: str

    def to_dict(self) -> dict:
        return dc.asdict(self)


@dc.dataclass
class AuthorshipInfo:
    primary_author: str
    primary_share: float  # 0..1, fraction of lines authored by primary
    last_modified_at: str  # ISO-8601
    last_commit: str
    contributors: list[str]  # ordered desc by count

    def to_dict(self) -> dict:
        return dc.asdict(self)


class GitContext:
    """Async-friendly façade over ``git`` invocations against an extracted
    repo path. Methods return ``None`` if the directory is not a git repo,
    so they can be safely chained without ``try/except`` everywhere.
    """

    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path
        self._is_git_repo: bool | None = None

    async def is_available(self) -> bool:
        if self._is_git_repo is not None:
            return self._is_git_repo
        # `git rev-parse --is-inside-work-tree` returns 'true' / non-zero
        rc, out, _ = await self._run("rev-parse", "--is-inside-work-tree")
        self._is_git_repo = rc == 0 and out.strip() == "true"
        if not self._is_git_repo:
            logger.info("git_context_unavailable", path=str(self.repo_path))
        return self._is_git_repo

    async def authorship(
        self, file: str, start_line: int, end_line: int | None = None
    ) -> AuthorshipInfo | None:
        if not await self.is_available():
            return None
        end = end_line if end_line is not None else start_line
        end = max(end, start_line)
        rc, out, err = await self._run(
            "blame",
            "--porcelain",
            f"-L{start_line},{end}",
            "--",
            file,
        )
        if rc != 0:
            logger.info("git_blame_failed", file=file, returncode=rc, stderr=err.strip())
            return None
        return _parse_blame_porcelain(out)

    async def history(
        self,
        file: str,
        start_line: int,
        end_line: int | None = None,
        limit: int = 5,
    ) -> list[CommitRef] | None:
        if not await self.is_available():
            return None
        end = end_line if end_line is not None else start_line
        end = max(end, start_line)
        # `-L start,end:file` walks the history of that exact line range.
        rc, out, err = await self._run(
            "log",
            f"-L{start_line},{end}:{file}",
            "--no-patch",
            f"--max-count={limit}",
            "--pretty=format:%H%x09%an%x09%aI%x09%s",
        )
        if rc != 0:
            logger.info(
                "git_log_failed",
                file=file,
                returncode=rc,
                stderr=err.strip()[:200],
            )
            return None
        commits: list[CommitRef] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t", 3)
            if len(parts) != 4:
                continue
            sha, author, date_iso, message = parts
            commits.append(
                CommitRef(
                    sha=sha,
                    short_sha=sha[:8],
                    author=author,
                    date=date_iso,
                    message=message,
                )
            )
        return commits

    async def diff_changed_files(
        self,
        from_sha: str,
        to_sha: str,
    ) -> tuple[list[str], list[str]]:
        """Compute ``(changed, deleted)`` file lists between two commits.

        Used by the iterative-docgen CI flow when the caller hands us a
        commit range instead of an explicit file list. Returns:

          * ``changed`` — files added (``A``) or modified (``M``) or
            renamed-and-changed (``R``-as-new-path) between ``from_sha``
            and ``to_sha``;
          * ``deleted`` — files removed (``D``) or the old-path side of
            a rename.

        Returns ``([], [])`` and logs a warning when:

          * ``is_available()`` is False (archive uploads have no .git);
          * either SHA is not present in the local repo;
          * the underlying ``git diff`` fails for any reason.

        We deliberately do not surface git-level errors as exceptions — the
        gateway endpoint that calls us treats an empty diff as "nothing to
        rewrite, fall back to ``changed_files`` from the request body".
        """
        if not await self.is_available():
            logger.warning("git_diff_unavailable_no_repo", repo_path=str(self.repo_path))
            return [], []

        rc, stdout, stderr = await self._run(
            "diff",
            "--name-status",
            "-z",
            f"{from_sha}..{to_sha}",
        )
        if rc != 0:
            logger.warning(
                "git_diff_failed",
                from_sha=from_sha,
                to_sha=to_sha,
                rc=rc,
                stderr=stderr.strip()[:500],
            )
            return [], []

        # ``-z`` separates records with NUL and uses the *path* as the next
        # field (no quoting, no escaping). For renames the format is:
        #     R<score>\0<old_path>\0<new_path>\0
        # For everything else:
        #     <STATUS>\0<path>\0
        changed: list[str] = []
        deleted: list[str] = []
        tokens = stdout.split("\0")
        i = 0
        while i < len(tokens):
            status = tokens[i]
            if not status:
                i += 1
                continue
            kind = status[0]
            if kind in ("R", "C"):  # rename / copy
                old_path = tokens[i + 1] if i + 1 < len(tokens) else ""
                new_path = tokens[i + 2] if i + 2 < len(tokens) else ""
                if old_path:
                    deleted.append(old_path)
                if new_path:
                    changed.append(new_path)
                i += 3
            elif kind == "D":
                path = tokens[i + 1] if i + 1 < len(tokens) else ""
                if path:
                    deleted.append(path)
                i += 2
            elif kind in ("A", "M", "T", "U"):  # added, modified, type-change, unmerged
                path = tokens[i + 1] if i + 1 < len(tokens) else ""
                if path:
                    changed.append(path)
                i += 2
            else:
                # Unknown status — skip the path field and keep going so
                # one weird record doesn't drop the rest of the diff.
                i += 2
        return changed, deleted

    async def _run(self, *args: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(self.repo_path),
            "--no-pager",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )


_PORCELAIN_HEADER = re.compile(r"^([0-9a-f]{40}) ")


# Recognise the common shapes of an HTTPS git URL so we can build a
# blob/<sha>/<path>#L<n>-L<m> deep-link. We deliberately keep this
# permissive on the host side (any subdomain/host) and strict on the
# scheme: SSH (``git@github.com:org/repo.git``) URLs are rejected because
# they cannot be opened in a browser.
_HTTPS_GIT_URL = re.compile(
    r"^https?://(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/?#]+?)(?:\.git)?/?$"
)


def build_source_url(
    git_url: str | None,
    commit_sha: str | None,
    file_path: str | None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str | None:
    """Build a browser-openable URL pointing at ``file_path`` at ``commit_sha``
    in the repository identified by ``git_url``.

    Pure / synchronous: takes everything as input, performs no I/O. Returns
    ``None`` (and the UI should render nothing) when:

    * any of ``git_url``, ``commit_sha`` or ``file_path`` is missing/empty;
    * ``git_url`` is not parseable as ``https://<host>/<owner>/<repo>``
      (notably: ``git@host:owner/repo.git`` SSH URLs and bare local paths);
    * line numbers are non-positive.

    The fragment is omitted when no line range is given. When only
    ``start_line`` is supplied (or ``end_line == start_line``), the fragment
    is ``#L<n>``; when both differ, ``#L<start>-L<end>`` — which is the
    syntax accepted by both GitHub and GitLab.
    """

    if not git_url or not commit_sha or not file_path:
        return None

    match = _HTTPS_GIT_URL.match(git_url.strip())
    if match is None:
        return None

    host = match.group("host")
    owner = match.group("owner")
    repo = match.group("repo")
    if not host or not owner or not repo:
        return None

    # Repo paths are stored as POSIX (forward slashes) by both git and our
    # ingestion pipeline; strip a leading "./" or "/" if present so the URL
    # ends up clean (`/blob/<sha>/src/foo.py` rather than `/blob/<sha>//src…`).
    # Use prefix stripping (not lstrip-charset) so a legitimate name beginning
    # with a dot like ``.github/workflows/ci.yml`` is preserved.
    clean_path = file_path
    while clean_path.startswith("./"):
        clean_path = clean_path[2:]
    while clean_path.startswith("/"):
        clean_path = clean_path[1:]
    if not clean_path:
        return None

    base = f"https://{host}/{owner}/{repo}/blob/{commit_sha}/{clean_path}"

    fragment = ""
    if start_line is not None and start_line > 0:
        if end_line is not None and end_line > start_line:
            fragment = f"#L{start_line}-L{end_line}"
        else:
            fragment = f"#L{start_line}"

    return base + fragment


def _parse_blame_porcelain(text: str) -> AuthorshipInfo | None:
    """Parse `git blame --porcelain` output into AuthorshipInfo.

    Porcelain format chunks each line with a header
    ``<sha> <orig_line> <final_line> [<group_size>]`` followed by
    metadata lines (``author``, ``author-time``, ``summary`` …) and the
    actual code line prefixed by a tab. We only need authors and dates.
    """

    if not text.strip():
        return None

    authors: list[str] = []
    by_sha_meta: dict[str, dict[str, str]] = {}
    last_sha: str | None = None
    line_to_sha: list[str] = []

    for raw in text.splitlines():
        m = _PORCELAIN_HEADER.match(raw)
        if m:
            last_sha = m.group(1)
            line_to_sha.append(last_sha)
            by_sha_meta.setdefault(last_sha, {})
            continue
        if last_sha is None:
            continue
        if raw.startswith("\t"):
            continue
        if " " in raw:
            key, _, value = raw.partition(" ")
            by_sha_meta[last_sha][key] = value

    if not line_to_sha:
        return None

    for sha in line_to_sha:
        author = by_sha_meta.get(sha, {}).get("author", "?")
        authors.append(author)

    counts: dict[str, int] = {}
    for a in authors:
        counts[a] = counts.get(a, 0) + 1
    primary, primary_count = max(counts.items(), key=lambda kv: kv[1])
    primary_share = primary_count / len(authors) if authors else 0.0

    last_sha = line_to_sha[-1]
    last_meta = by_sha_meta.get(last_sha, {})
    author_time = last_meta.get("author-time")
    last_modified_iso = ""
    if author_time and author_time.isdigit():
        ts = int(author_time)
        last_modified_iso = dt.datetime.fromtimestamp(ts, tz=dt.UTC).isoformat()

    contributors_sorted = [
        a for a, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    ]

    return AuthorshipInfo(
        primary_author=primary,
        primary_share=round(primary_share, 3),
        last_modified_at=last_modified_iso,
        last_commit=last_sha,
        contributors=contributors_sorted,
    )
