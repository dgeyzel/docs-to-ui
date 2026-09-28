"""Standalone HTML export: one file with every style and script inlined."""

from markupsafe import Markup
from plain.runtime import APP_PATH
from plain.templates import Template

from app.generations.models import Generation
from app.generations.presentation import PageView

EXPORT_STYLESHEETS = ("css/tokens.css", "css/components.css")
EXPORT_SCRIPTS = ("js/docpage.js",)


def _read_asset(relative_path: str) -> str:
    with (APP_PATH / "assets" / relative_path).open(encoding="utf-8") as handle:
        return handle.read()


def render_export_html(*, page_view: PageView) -> str:
    """Render the doc page as a self-contained HTML document.

    The file makes no network requests and contains no HTMX, app links,
    feedback controls or theme toggle.
    """
    styles = "\n".join(_read_asset(path) for path in EXPORT_STYLESHEETS)
    scripts = "\n".join(_read_asset(path) for path in EXPORT_SCRIPTS)
    return Template("generations/export.html").render(
        {
            "page": page_view,
            "inline_styles": Markup(styles),
            "inline_scripts": Markup(scripts),
        }
    )


def export_filename(generation: Generation, extension: str) -> str:
    """Download filename for an export, e.g. `docs-12.html`."""
    return f"docs-{generation.id}.{extension}"
