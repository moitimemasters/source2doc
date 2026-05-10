import dataclasses as dc
import typing as tp


PLACEHOLDER_VALUES = {"", "code", "example", "todo", "tbd", "...", "…"}


@dc.dataclass
class ValidationResult:
    is_valid: bool
    reason: str | None = None
    line_drift: bool = False
    cleaned_step: tp.Any = None
    """If validation succeeds, may carry a step copy with sanitised
    ``highlights`` / ``connects_to`` (out-of-range entries removed)."""


def _is_placeholder(code: str) -> bool:
    cleaned = code.strip().lower()
    if cleaned in PLACEHOLDER_VALUES:
        return True
    if len([line for line in code.splitlines() if line.strip()]) < 3:
        return True
    return False


def _sanitise_highlights(step, slice_start: int, slice_end: int):
    """Drop highlights pointing outside the slice; clamp at the boundaries."""
    cleaned = []
    for hl in step.highlights:
        if slice_start <= hl.line <= slice_end:
            cleaned.append(hl)
    return cleaned


def _sanitise_connects(connects, total_steps: int, own_index: int) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for c in connects:
        if not isinstance(c, int):
            continue
        if c == own_index:
            continue
        if 0 <= c < total_steps and c not in seen:
            out.append(c)
            seen.add(c)
    return out


async def validate_step(
    step,
    filesystem,
    *,
    own_index: int = 0,
    total_steps: int = 1,
) -> ValidationResult:
    """Validate a CodeTourStep against the real filesystem and the surrounding
    tour. Highlights that fall outside the step's code range and self-references
    in ``connects_to`` are silently dropped (the step itself is still returned
    via ``cleaned_step``).
    """

    code = step.code or ""
    if _is_placeholder(code):
        return ValidationResult(False, "code is a placeholder or shorter than 3 non-empty lines")

    if not await filesystem.file_exists(step.file):
        return ValidationResult(False, f"file '{step.file}' does not exist")

    content = await filesystem.read_file(step.file)
    lines = content.splitlines()
    line = max(1, step.line)
    end = step.end_line if step.end_line is not None else line + len(code.splitlines())
    end = min(end, len(lines))
    slice_text = "\n".join(lines[line - 1 : end])

    needle = code.strip()
    line_drift = False
    if needle in slice_text:
        pass
    elif needle in content:
        line_drift = True
    else:
        return ValidationResult(False, "code snippet not found in file")

    cleaned_highlights = _sanitise_highlights(step, line, end)
    cleaned_connects = _sanitise_connects(step.connects_to, total_steps, own_index)

    cleaned = step.model_copy(
        update={"highlights": cleaned_highlights, "connects_to": cleaned_connects}
    )
    return ValidationResult(is_valid=True, line_drift=line_drift, cleaned_step=cleaned)
