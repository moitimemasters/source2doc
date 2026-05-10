"""Tests for the iterative-docgen page classifier + orphan planner.

Covers ``classify_pages``, ``find_orphan_files`` and
``decide_orphan_actions`` — the storage-agnostic heart of iterative mode.
The handler-level orchestrator (``workers/handlers/incremental.py``) is
exercised end-to-end from the smoke runs in the dev environment; here we
guarantee the bucketing rules don't drift silently.
"""

from __future__ import annotations

from docgen_core.pipeline import incremental_docs as ID


def _page(page_id: str, source_files: list[str]) -> dict:
    return {"page_id": page_id, "source_files": source_files}


# ---------------------------------------------------------------------------
# classify_pages
# ---------------------------------------------------------------------------


def test_classify_direct_when_changed_overlaps() -> None:
    base = [_page("auth", ["src/auth.py"]), _page("api", ["src/api/users.py"])]
    impact = ID.classify_pages(base, ["src/auth.py"], [])
    assert impact.direct == ["auth"]
    assert impact.unchanged == ["api"]
    assert impact.dead == []
    assert impact.transitive == []


def test_classify_dead_when_all_sources_deleted() -> None:
    base = [_page("legacy", ["old/foo.py", "old/bar.py"]), _page("auth", ["src/auth.py"])]
    impact = ID.classify_pages(
        base,
        changed_files=[],
        deleted_files=["old/foo.py", "old/bar.py"],
    )
    assert impact.dead == ["legacy"]
    assert impact.unchanged == ["auth"]
    assert impact.direct == []


def test_classify_partial_delete_keeps_page_direct() -> None:
    """If only some of a page's source files are deleted, the page lives —
    but it gets re-written because at least one file changed (the
    remaining live ones may need updates referencing the gap)."""
    base = [_page("p", ["a.py", "b.py"])]
    impact = ID.classify_pages(base, changed_files=["b.py"], deleted_files=["a.py"])
    assert impact.direct == ["p"]
    assert impact.dead == []


def test_classify_unchanged_when_no_overlap() -> None:
    base = [_page("auth", ["src/auth.py"]), _page("api", ["src/api.py"])]
    impact = ID.classify_pages(base, changed_files=["unrelated.py"], deleted_files=[])
    assert impact.direct == []
    assert impact.unchanged == ["api", "auth"]


def test_classify_empty_source_files_treated_as_direct_when_anything_changed() -> None:
    """Pages with no recorded source_files are conservatively rewritten —
    we don't know what they cover, so it's safer to refresh."""
    base = [_page("opaque", [])]
    impact = ID.classify_pages(base, changed_files=["any.py"], deleted_files=[])
    assert impact.direct == ["opaque"]


def test_classify_empty_source_files_unchanged_when_nothing_changed() -> None:
    base = [_page("opaque", [])]
    impact = ID.classify_pages(base, changed_files=[], deleted_files=[])
    assert impact.unchanged == ["opaque"]
    assert impact.direct == []


def test_classify_normalises_leading_dot_slash() -> None:
    """``./src/foo.py`` and ``src/foo.py`` must match — writer-supplied
    paths sometimes carry the prefix, caller-supplied paths usually
    don't."""
    base = [_page("p", ["./src/foo.py"])]
    impact = ID.classify_pages(base, changed_files=["src/foo.py"], deleted_files=[])
    assert impact.direct == ["p"]


def test_classify_transitive_promotes_via_page_links() -> None:
    base = [
        _page("auth", ["src/auth.py"]),
        _page("api", ["src/api.py"]),
        _page("docs", ["docs/intro.md"]),
    ]
    # api page links to auth with weight 2
    links = [("api", "auth", "symbol", 2)]
    impact = ID.classify_pages(
        base,
        changed_files=["src/auth.py"],
        page_links=links,
    )
    assert impact.direct == ["auth"]
    assert impact.transitive == ["api"]
    assert impact.unchanged == ["docs"]


def test_classify_transitive_disabled_when_links_none() -> None:
    base = [_page("auth", ["src/auth.py"]), _page("api", ["src/api.py"])]
    links = [("api", "auth", "symbol", 5)]
    impact = ID.classify_pages(
        base,
        changed_files=["src/auth.py"],
        page_links=None,  # explicitly off
    )
    assert impact.transitive == []
    assert impact.unchanged == ["api"]


def test_classify_transitive_below_min_weight_ignored() -> None:
    base = [_page("auth", ["src/auth.py"]), _page("api", ["src/api.py"])]
    links = [("api", "auth", "mention", 1)]
    impact = ID.classify_pages(
        base,
        changed_files=["src/auth.py"],
        page_links=links,
        transitive_min_weight=3,
    )
    assert impact.transitive == []
    assert impact.unchanged == ["api"]


def test_classify_all_affected_concatenates_direct_and_transitive() -> None:
    base = [_page("a", ["a.py"]), _page("b", ["b.py"])]
    links = [("b", "a", "symbol", 5)]
    impact = ID.classify_pages(base, changed_files=["a.py"], page_links=links)
    assert impact.all_affected() == ["a", "b"]


# ---------------------------------------------------------------------------
# find_orphan_files
# ---------------------------------------------------------------------------


def test_find_orphan_files_returns_changed_minus_covered() -> None:
    base = [_page("p", ["src/known.py"])]
    orphans = ID.find_orphan_files(
        base,
        changed_files=["src/known.py", "src/new.py", "src/another.py"],
    )
    assert orphans == ["src/another.py", "src/new.py"]


def test_find_orphan_files_empty_when_all_covered() -> None:
    base = [_page("p", ["a.py", "b.py"])]
    orphans = ID.find_orphan_files(base, changed_files=["a.py", "b.py"])
    assert orphans == []


# ---------------------------------------------------------------------------
# decide_orphan_actions
# ---------------------------------------------------------------------------


def test_decide_orphan_actions_groups_by_directory() -> None:
    plan = ID.decide_orphan_actions(
        ["src/auth/login.py", "src/auth/logout.py", "src/api/users.py"],
    )
    assert len(plan.page_specs) == 2
    by_dir = {spec["title"]: spec for spec in plan.page_specs}
    assert "src/auth (new files)" in by_dir
    assert "src/api (new files)" in by_dir
    assert by_dir["src/auth (new files)"]["source_files"] == [
        "src/auth/login.py",
        "src/auth/logout.py",
    ]


def test_decide_orphan_actions_splits_oversize_directory() -> None:
    files = [f"src/big/file{i}.py" for i in range(12)]
    plan = ID.decide_orphan_actions(files, max_files_per_page=5)
    # 12 files / 5 per page → 3 specs
    assert len(plan.page_specs) == 3
    # First two specs full, last spec has the remainder
    assert all(len(s["source_files"]) <= 5 for s in plan.page_specs)
    assert sum(len(s["source_files"]) for s in plan.page_specs) == 12


def test_decide_orphan_actions_root_files_get_root_title() -> None:
    plan = ID.decide_orphan_actions(["README.md", "Makefile"])
    assert len(plan.page_specs) == 1
    assert plan.page_specs[0]["title"] == "Repository root files"


def test_decide_orphan_actions_empty_input_returns_empty_plan() -> None:
    plan = ID.decide_orphan_actions([])
    assert plan.page_specs == []
    assert plan.skipped_files == []


def test_decide_orphan_actions_page_id_is_stable_for_same_input() -> None:
    files = ["src/a.py", "src/b.py"]
    plan_a = ID.decide_orphan_actions(files, page_id_seed="seed1")
    plan_b = ID.decide_orphan_actions(files, page_id_seed="seed1")
    assert plan_a.page_specs[0]["page_id"] == plan_b.page_specs[0]["page_id"]


def test_decide_orphan_actions_page_id_changes_with_seed() -> None:
    files = ["src/a.py"]
    plan_a = ID.decide_orphan_actions(files, page_id_seed="seed1")
    plan_b = ID.decide_orphan_actions(files, page_id_seed="seed2")
    assert plan_a.page_specs[0]["page_id"] != plan_b.page_specs[0]["page_id"]
