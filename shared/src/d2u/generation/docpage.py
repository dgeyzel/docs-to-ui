"""Building pages and overviews without the LLM."""

from collections.abc import Callable

from d2u.schemas.docpage import ApiSurface, DocPage, Operation, Overview


def fallback_overview(
    *, surface: ApiSurface, group_of: Callable[[Operation], str], display_name: str
) -> Overview:
    """A deterministic overview: one sentence, groups in first-seen order.

    Args:
        surface: The extracted API surface.
        group_of: The adapter's grouping function.
        display_name: Human name of the source language, used in the sentence.
    """
    groups: dict[str, list[str]] = {}
    for op in surface.operations:
        groups.setdefault(group_of(op), []).append(op.id)

    count = len(surface.operations)
    noun = "operation" if count == 1 else "operations"
    overview_md = (
        f"This page documents {count} {noun} extracted from the {display_name} "
        "source. Descriptions are shown as written in the source."
    )
    return Overview(overview_md=overview_md, groups=groups)


def build_unenriched_docpage(
    *, surface: ApiSurface, group_of: Callable[[Operation], str], display_name: str
) -> DocPage:
    """Return a page that shows only what was extracted from the source.

    Every operation is rendered as "not enriched".
    """
    return DocPage(
        surface=surface,
        overview=fallback_overview(
            surface=surface, group_of=group_of, display_name=display_name
        ),
        operations=[],
    )
