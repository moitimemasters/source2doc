"""Navigation traversal tests for the bundler.

PMI-mapping: 6.2.6 (Экспорт бандла документации) — bundler must visit every
leaf page in the navigation tree, including nested groups, before invoking
formatter conversion.
"""

from worker.bundler.processor import _collect_page_ids


def test_flat_navigation_yields_all_ids() -> None:
    nav: dict[str, str | dict] = {"intro": "Intro", "usage": "Usage", "api": "API"}
    assert sorted(_collect_page_ids(nav)) == ["api", "intro", "usage"]


def test_nested_group_recurses_into_children() -> None:
    nav: dict[str, str | dict] = {
        "overview": "Overview",
        "commands": {
            "title": "Commands",
            "children": {
                "find": "Find",
                "stop": "Stop",
            },
        },
    }
    assert sorted(_collect_page_ids(nav)) == ["find", "overview", "stop"]


def test_dict_without_children_is_treated_as_leaf() -> None:
    nav: dict[str, str | dict] = {"overview": {"title": "Overview"}}
    assert _collect_page_ids(nav) == ["overview"]


def test_empty_navigation_yields_empty_list() -> None:
    nav: dict[str, str | dict] = {}
    assert _collect_page_ids(nav) == []


def test_deeply_nested_groups_are_flattened() -> None:
    nav: dict[str, str | dict] = {
        "level1": {
            "title": "L1",
            "children": {
                "level2a": {
                    "title": "L2A",
                    "children": {"deep1": "Deep 1", "deep2": "Deep 2"},
                },
                "level2b": "Leaf",
            },
        }
    }
    assert sorted(_collect_page_ids(nav)) == ["deep1", "deep2", "level2b"]
