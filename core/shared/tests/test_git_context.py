"""Tests for ``source2doc.git_context.build_source_url``.

The helper is a pure URL builder used by the gateway and the UI to render
"View source" deep-links. SSH URLs and missing inputs must return ``None``
so the UI can render nothing.
"""

from __future__ import annotations

import pytest

from source2doc.git_context import build_source_url


class TestBuildSourceUrlHttps:
    def test_github_with_line_range(self) -> None:
        url = build_source_url(
            git_url="https://github.com/acme/widget.git",
            commit_sha="0123456789abcdef0123456789abcdef01234567",
            file_path="src/foo.py",
            start_line=10,
            end_line=30,
        )
        assert url == (
            "https://github.com/acme/widget/blob/"
            "0123456789abcdef0123456789abcdef01234567/src/foo.py#L10-L30"
        )

    def test_github_without_dot_git_suffix(self) -> None:
        url = build_source_url(
            git_url="https://github.com/acme/widget",
            commit_sha="abc123",
            file_path="README.md",
            start_line=1,
            end_line=1,
        )
        # end == start collapses to a single-line anchor (#L1, not #L1-L1)
        assert url == "https://github.com/acme/widget/blob/abc123/README.md#L1"

    def test_gitlab_self_hosted(self) -> None:
        url = build_source_url(
            git_url="https://gitlab.example.com/team/project.git",
            commit_sha="deadbeef",
            file_path="lib/mod.rb",
            start_line=42,
        )
        # No end_line → single-line fragment
        assert url == "https://gitlab.example.com/team/project/blob/deadbeef/lib/mod.rb#L42"

    def test_no_line_range_no_fragment(self) -> None:
        url = build_source_url(
            git_url="https://github.com/acme/widget.git",
            commit_sha="abc",
            file_path="docs/index.md",
        )
        assert url == "https://github.com/acme/widget/blob/abc/docs/index.md"

    def test_strips_leading_slash_and_dotslash(self) -> None:
        url = build_source_url(
            git_url="https://github.com/a/b.git",
            commit_sha="sha",
            file_path="./src/x.py",
            start_line=5,
        )
        assert url == "https://github.com/a/b/blob/sha/src/x.py#L5"

        url2 = build_source_url(
            git_url="https://github.com/a/b.git",
            commit_sha="sha",
            file_path="/src/x.py",
            start_line=5,
        )
        assert url2 == "https://github.com/a/b/blob/sha/src/x.py#L5"

    def test_preserves_dotfile_paths(self) -> None:
        # Don't eat the leading dot of `.github/...` while normalising paths.
        url = build_source_url(
            git_url="https://github.com/a/b.git",
            commit_sha="sha",
            file_path=".github/workflows/ci.yml",
            start_line=3,
        )
        assert url == "https://github.com/a/b/blob/sha/.github/workflows/ci.yml#L3"

    def test_trailing_slash_in_git_url(self) -> None:
        url = build_source_url(
            git_url="https://github.com/acme/widget/",
            commit_sha="sha",
            file_path="x.py",
        )
        assert url == "https://github.com/acme/widget/blob/sha/x.py"


class TestBuildSourceUrlReturnsNone:
    @pytest.mark.parametrize(
        "git_url",
        [
            None,
            "",
            "git@github.com:acme/widget.git",
            "ssh://git@github.com/acme/widget.git",
            "/local/path/to/repo",
            "not a url",
            "https://github.com/",  # no owner/repo
            "https://github.com/just-owner",  # no repo
        ],
    )
    def test_unparseable_or_non_https(self, git_url: str | None) -> None:
        assert (
            build_source_url(
                git_url=git_url,
                commit_sha="abc",
                file_path="x.py",
                start_line=1,
            )
            is None
        )

    def test_missing_commit_sha(self) -> None:
        assert (
            build_source_url(
                git_url="https://github.com/a/b.git",
                commit_sha=None,
                file_path="x.py",
            )
            is None
        )

    def test_empty_commit_sha(self) -> None:
        assert (
            build_source_url(
                git_url="https://github.com/a/b.git",
                commit_sha="",
                file_path="x.py",
            )
            is None
        )

    def test_missing_file_path(self) -> None:
        assert (
            build_source_url(
                git_url="https://github.com/a/b.git",
                commit_sha="sha",
                file_path=None,
            )
            is None
        )

    def test_empty_file_path_after_normalisation(self) -> None:
        assert (
            build_source_url(
                git_url="https://github.com/a/b.git",
                commit_sha="sha",
                file_path="/",
            )
            is None
        )

    def test_non_positive_start_line_omits_fragment(self) -> None:
        # Negative or zero line numbers are silently dropped (no fragment),
        # rather than producing a malformed #L0 anchor.
        url = build_source_url(
            git_url="https://github.com/a/b.git",
            commit_sha="sha",
            file_path="x.py",
            start_line=0,
            end_line=10,
        )
        assert url == "https://github.com/a/b/blob/sha/x.py"
