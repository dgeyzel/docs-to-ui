from d2u.sources.registry import display_name
from plain.templates import register_template_filter


@register_template_filter
def language_name(name: str) -> str:
    """Display name for an adapter name, or "—" when unknown yet."""
    return display_name(name) if name else "—"
