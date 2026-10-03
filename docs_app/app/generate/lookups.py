"""Finding a generation, and its page, for a request."""

from typing import Any

from d2u.generations.models import Generation, GenerationStatus
from d2u.schemas.docpage import DocPage
from plain.http import NotFoundError404


def get_generation_or_404(url_kwargs: dict[str, Any]) -> Generation:
    """The generation named by the URL's `id`.

    Raises:
        NotFoundError404: No generation has that id.
    """
    generation = Generation.query.get_or_none(int(url_kwargs["id"]))
    if generation is None:
        raise NotFoundError404()
    return generation


def succeeded_page(generation: Generation) -> DocPage | None:
    """The generation's page, or None until it has succeeded."""
    if generation.status != GenerationStatus.SUCCEEDED or generation.doc_json is None:
        return None
    return DocPage.model_validate(generation.doc_json)


def succeeded_page_or_404(generation: Generation) -> DocPage:
    """The generation's page.

    Raises:
        NotFoundError404: The generation hasn't succeeded.
    """
    page = succeeded_page(generation)
    if page is None:
        raise NotFoundError404()
    return page
