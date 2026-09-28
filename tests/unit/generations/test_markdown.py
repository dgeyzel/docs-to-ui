import pytest

from app.generations.markdown import render_markdown


@pytest.mark.parametrize("text", [None, ""])
def test_render_markdown_returns_empty_markup_for_no_text(text: str | None) -> None:
    assert render_markdown(text) == ""


def test_render_markdown_renders_basic_markdown() -> None:
    html = render_markdown("Use **bold** and `code`.\n\n- one\n- two")

    assert "<strong>bold</strong>" in html
    assert "<code>code</code>" in html
    assert "<li>one</li>" in html


def test_render_markdown_escapes_raw_html() -> None:
    html = render_markdown("<script>alert(1)</script> and <b>bold</b>")

    assert "<script>" not in html
    assert "<b>" not in html
    assert "&lt;script&gt;" in html


def test_render_markdown_drops_javascript_links() -> None:
    html = render_markdown("[click](javascript:alert(1))")

    assert "<a" not in html
    assert 'href="javascript' not in html


def test_render_markdown_keeps_http_links_with_safe_rel() -> None:
    html = render_markdown("[docs](https://example.com)")

    assert 'href="https://example.com"' in html
    assert 'rel="noopener noreferrer"' in html


def test_render_markdown_drops_images_so_exports_make_no_requests() -> None:
    html = render_markdown("![tracker](https://example.com/pixel.png)")

    assert "<img" not in html
    assert "example.com/pixel.png" not in html


def test_render_markdown_renders_tables() -> None:
    html = render_markdown("| a | b |\n|---|---|\n| 1 | 2 |")

    assert "<table>" in html
    assert "<td>1</td>" in html
