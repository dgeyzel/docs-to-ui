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


@register_template_global
def trace_settings_url() -> str:
    """Link to the page where trace backends are chosen, or "" in the Docs app.

    Only the Tuning app changes runtime settings (SPEC §19).
    """
    try:
        return reverse("settings:index")
    except NoReverseMatch:
        return ""


@register_template_global
def eval_run_url(eval_run_id: int) -> str:
    """Link to an eval run's page, or "" in an app without eval runs."""
    try:
        return reverse("evals:detail", id=eval_run_id)
    except NoReverseMatch:
        return ""
