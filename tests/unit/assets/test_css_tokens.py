import re
from pathlib import Path

import pytest

CSS_DIR = Path(__file__).resolve().parents[3] / "app" / "assets" / "css"
COMPONENT_CSS = sorted(
    path for path in CSS_DIR.glob("*.css") if path.name != "tokens.css"
)

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_COLOR_FUNCTION = re.compile(
    r"\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(", re.IGNORECASE
)
_NAMED_COLOR = re.compile(
    r":\s*[^;]*\b(white|black|red|green|blue|gray|grey|silver|orange|purple|yellow)\b",
    re.IGNORECASE,
)


def css_without_comments(path: Path) -> str:
    return _COMMENT.sub("", path.read_text(encoding="utf-8"))


def test_component_stylesheets_exist() -> None:
    assert [path.name for path in COMPONENT_CSS] == ["components.css"]


@pytest.mark.parametrize("path", COMPONENT_CSS, ids=lambda path: path.name)
@pytest.mark.parametrize(
    "pattern", [_HEX, _COLOR_FUNCTION, _NAMED_COLOR], ids=["hex", "function", "named"]
)
def test_component_css_uses_no_raw_color_literals(
    path: Path, pattern: re.Pattern
) -> None:
    assert pattern.findall(css_without_comments(path)) == []


@pytest.mark.parametrize("path", COMPONENT_CSS, ids=lambda path: path.name)
def test_component_css_has_no_theme_specific_rules(path: Path) -> None:
    css = css_without_comments(path)

    assert "data-theme" not in css
    assert "prefers-color-scheme" not in css
