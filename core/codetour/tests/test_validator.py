"""CodeTour step validator tests.

PMI-mapping: 6.2.9 (Создание и просмотр CodeTour). The validator is the
critical gatekeeper that prevents the LLM agent from emitting tour steps
that point at lines/snippets that don't exist in the real source. It also
sanitises out-of-range highlights and self-referencing ``connects_to``
indices.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from codetour_core.models import CodeTourStep, StepHighlight
from codetour_core.validator import _is_placeholder, validate_step


def _step(**overrides) -> CodeTourStep:
    base = dict(
        title="t",
        description="d",
        file="src/main.py",
        line=1,
        end_line=None,
        code=None,
        kind="transition",
        highlights=[],
        connects_to=[],
    )
    base.update(overrides)
    return CodeTourStep(**base)


def _fake_fs(content: str, exists: bool = True):
    return SimpleNamespace(
        file_exists=AsyncMock(return_value=exists),
        read_file=AsyncMock(return_value=content),
    )


# --------------------------------------------------------------------------- #
# placeholder detection
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("code", ["", "code", "...", "todo", "TBD", "code"])
def test_placeholder_strings_are_rejected(code: str) -> None:
    assert _is_placeholder(code) is True


def test_too_few_nonempty_lines_is_placeholder() -> None:
    assert _is_placeholder("a\n\nb") is True


def test_real_snippet_is_not_placeholder() -> None:
    snippet = "def f():\n    x = 1\n    return x\n"
    assert _is_placeholder(snippet) is False


# --------------------------------------------------------------------------- #
# validate_step
# --------------------------------------------------------------------------- #


async def test_step_with_placeholder_code_rejected() -> None:
    fs = _fake_fs("...")
    step = _step(code="...")
    result = await validate_step(step, fs)
    assert result.is_valid is False
    assert "placeholder" in (result.reason or "")


async def test_step_with_missing_file_rejected() -> None:
    fs = _fake_fs("", exists=False)
    step = _step(code="line1\nline2\nline3", file="missing.py")
    result = await validate_step(step, fs)
    assert result.is_valid is False
    assert "does not exist" in (result.reason or "")


async def test_step_with_snippet_at_correct_line_passes() -> None:
    file_content = "import os\n\ndef hello():\n    return 'hi'\n    print('done')\n"
    snippet = "def hello():\n    return 'hi'\n    print('done')"
    fs = _fake_fs(file_content)

    step = _step(line=3, end_line=5, code=snippet)
    result = await validate_step(step, fs)

    assert result.is_valid is True
    assert result.line_drift is False
    assert result.cleaned_step is not None


async def test_step_with_drifted_snippet_marked() -> None:
    """If the snippet exists in the file but at a different line, the
    validator passes but flags ``line_drift`` so the agent can re-anchor."""

    file_content = "# header\n# header2\ndef hello():\n    return 'x'\n    print('y')\n"
    snippet = "def hello():\n    return 'x'\n    print('y')"
    fs = _fake_fs(file_content)

    # Wrong line — snippet is at line 3 but step claims line 1.
    step = _step(line=1, end_line=3, code=snippet)
    result = await validate_step(step, fs)

    assert result.is_valid is True
    assert result.line_drift is True


async def test_step_with_completely_missing_snippet_rejected() -> None:
    fs = _fake_fs("def real():\n    pass\n    return\n")
    step = _step(line=1, end_line=3, code="def fabricated():\n    return 0\n    pass")
    result = await validate_step(step, fs)
    assert result.is_valid is False
    assert "not found" in (result.reason or "")


async def test_out_of_range_highlights_dropped() -> None:
    file_content = "a\nb\nc\nd\ne\nf\ng\n"
    snippet = "b\nc\nd"
    fs = _fake_fs(file_content)

    step = _step(
        line=2,
        end_line=4,
        code=snippet,
        highlights=[
            StepHighlight(line=3, note="in range"),
            StepHighlight(line=99, note="way past EOF"),
            StepHighlight(line=1, note="before start"),
        ],
    )
    result = await validate_step(step, fs)

    assert result.is_valid is True
    cleaned = result.cleaned_step
    assert len(cleaned.highlights) == 1
    assert cleaned.highlights[0].line == 3


async def test_self_reference_in_connects_to_dropped() -> None:
    file_content = "x\ny\nz\n"
    snippet = "x\ny\nz"
    fs = _fake_fs(file_content)

    step = _step(line=1, end_line=3, code=snippet, connects_to=[0, 1, 2])
    result = await validate_step(step, fs, own_index=1, total_steps=3)

    cleaned = result.cleaned_step
    assert cleaned.connects_to == [0, 2], "own index 1 must be removed"


async def test_out_of_range_connects_to_dropped() -> None:
    file_content = "x\ny\nz\n"
    snippet = "x\ny\nz"
    fs = _fake_fs(file_content)

    step = _step(line=1, end_line=3, code=snippet, connects_to=[0, 5, 10, -1, 2])
    result = await validate_step(step, fs, own_index=1, total_steps=3)

    cleaned = result.cleaned_step
    assert cleaned.connects_to == [0, 2]
