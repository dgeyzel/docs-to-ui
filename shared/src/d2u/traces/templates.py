from plain.templates import register_template_global
from plain.urls import NoReverseMatch, reverse


@register_template_global
def generation_url(generation_id: int) -> str:
    """Link to a generation's page, or "" in an app without that page.

    The trace viewer is shared by both apps, but only the Docs app serves
    generation pages.
    """
    try:
        return reverse("generations:detail", id=generation_id)
    except NoReverseMatch:
        return ""
