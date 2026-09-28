"""Markdown rendering for untrusted text (LLM output and source descriptions)."""

import nh3
from markdown_it import MarkdownIt
from markupsafe import Markup

# No <img>: an image would make exported pages fetch from the network.
ALLOWED_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "em",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}
ALLOWED_ATTRIBUTES = {"a": {"href", "title"}}
ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}

_markdown = MarkdownIt("commonmark", {"html": False}).enable("table")


def render_markdown(text: str | None) -> Markup:
    """Render Markdown to HTML and sanitize it.

    Raw HTML in the input is escaped by the renderer, and the output is then
    cleaned with nh3, so the result is safe to insert into a page.
    """
    if not text:
        return Markup("")
    html = _markdown.render(text)
    clean = nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer",
    )
    return Markup(clean)
