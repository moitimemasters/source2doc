"""Language directive appended to every agent's ``instructions``.

Every ``create_*_agent`` factory (writer, critic, diagrammer, planner,
subplanner, normalizer) calls :func:`build_directive` with the per-task
``output_language`` and appends the result to ``prompt_config.instructions``
before constructing the Pydantic-AI agent. This is the single source of
truth for "render output in language X" — keeping it out of per-prompt
Jinja templates means we don't have to touch every j2 / inline-string
prompt builder when languages or wording change.

Anthropic prompt-caching still works: the directive becomes part of the
stable ``instructions`` segment, so the cache-control breakpoint covers
it just like the rest of the YAML.
"""

from __future__ import annotations


_LANG_NAMES: dict[str, dict[str, str]] = {
    "en": {"name_en": "English", "name_native": "English"},
    "ru": {"name_en": "Russian", "name_native": "русский"},
}


_CRITIC_RULE = (
    "ADDITIONAL CRITIC RULE: if any heading / paragraph / list-item / "
    "callout text / table-cell content of the reviewed page is NOT in "
    "{name_en}, you MUST treat that as a serious quality defect — lower "
    "the page score, set ``decision`` to ``revision_requested``, and add "
    "a finding with reason ``wrong_output_language`` describing which "
    "blocks drifted. Code identifiers, file paths, library names and "
    "CLI flags are exempt — only natural-language prose counts."
)


def build_directive(output_language: str, role: str) -> str:
    """Return a system-prompt suffix instructing the agent to produce
    natural-language output in ``output_language``.

    ``role`` is the agent role ("writer", "critic", ...). The critic gets
    an extra rule that turns wrong-language output into a review finding;
    other agents just get the language directive.

    Unknown language codes fall back to English (defensive — schema
    validation upstream restricts it to the supported set).
    """
    lang = _LANG_NAMES.get(output_language) or _LANG_NAMES["en"]
    name_en = lang["name_en"]
    name_native = lang["name_native"]

    base = (
        f"\n\nOUTPUT LANGUAGE\n"
        f"All natural-language content you produce — page titles, descriptions, "
        f"paragraphs, list items, table cells, callout text, diagram intent "
        f"strings, critic findings, section / page summaries — MUST be written "
        f"in {name_en} ({name_native}). Code identifiers, file paths, library "
        f"names, CLI flags, JSON field names, URLs and other technical tokens "
        f"keep their original form regardless of the chosen language.\n"
        f"This rule overrides any examples or instructions above written in a "
        f"different language: if your system prompt is in Russian but "
        f"output_language is 'en', emit English; vice versa for 'ru'."
    )

    if role == "critic":
        return base + "\n\n" + _CRITIC_RULE.format(name_en=name_en)
    return base
