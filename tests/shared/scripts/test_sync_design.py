import json
from pathlib import Path

import pytest

from scripts.sync_design import (
    ASSETS_DIR,
    DESIGN_DIR,
    REQUIRED_TOKENS,
    main,
    parse_token_blocks,
    planned_copies,
    stale_files,
    validate_manifest,
    validate_package,
    validate_tokens,
)

DARK_BLOCKS = """
[data-theme="dark"] { --bg: #000000; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { --bg: #000000; }
}
"""


def complete_tokens_css(extra_root: str = "") -> str:
    declarations = "\n".join(f"  {token}: 1px;" for token in REQUIRED_TOKENS)
    return f":root {{\n{declarations}\n{extra_root}}}\n{DARK_BLOCKS}"


def write_package(directory: Path, tokens_css: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "tokens.css").write_text(tokens_css, encoding="utf-8")
    (directory / "DESIGN.md").write_text("# Design\n", encoding="utf-8")
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": "od-design-system-project/v1",
                "id": "docs-to-ui",
                "name": "Docs-to-UI",
                "files": {"design": "DESIGN.md", "tokens": "tokens.css"},
            }
        ),
        encoding="utf-8",
    )


def test_required_tokens_cover_the_brief() -> None:
    assert len(REQUIRED_TOKENS) == 87
    assert len(set(REQUIRED_TOKENS)) == 87
    assert "--d2u-method-delete-bg" in REQUIRED_TOKENS


def test_repository_design_package_is_valid() -> None:
    assert validate_package(DESIGN_DIR) == []


def test_app_tokens_copy_matches_the_design_package() -> None:
    assert stale_files(planned_copies(DESIGN_DIR, ASSETS_DIR)) == []


def test_validate_tokens_accepts_a_complete_file() -> None:
    assert validate_tokens(complete_tokens_css()) == []


def test_validate_tokens_reports_missing_tokens() -> None:
    css = complete_tokens_css().replace("  --d2u-span-llm: 1px;\n", "")

    assert validate_tokens(css) == ["tokens.css :root is missing --d2u-span-llm."]


def test_validate_tokens_ignores_tokens_declared_only_in_comments() -> None:
    css = complete_tokens_css().replace(
        "  --d2u-span-llm: 1px;\n", "  /* --d2u-span-llm: 1px; */\n"
    )

    assert "tokens.css :root is missing --d2u-span-llm." in validate_tokens(css)


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ('[data-theme="dark"] { --bg: #000000; }', '[data-theme="dark"]'),
        (':root:not([data-theme="light"]) { --bg: #000000; }', "prefers-color-scheme"),
    ],
)
def test_validate_tokens_requires_both_dark_theme_blocks(
    block: str, message: str
) -> None:
    css = complete_tokens_css()
    if 'data-theme="dark"' in block:
        css = css.replace(block, "")
    else:
        css = css.replace(
            '@media (prefers-color-scheme: dark) {\n  :root:not([data-theme="light"]) { --bg: #000000; }\n}',
            "",
        )

    errors = validate_tokens(css)

    assert len(errors) == 1
    assert message in errors[0]


@pytest.mark.parametrize(
    "value",
    [
        "url('https://fonts.example.com/a.woff2')",
        'url("//cdn.example.com/a.woff2")',
        "url(http://example.com/a.woff2)",
    ],
)
def test_validate_tokens_rejects_network_urls(value: str) -> None:
    css = complete_tokens_css(extra_root=f"  --font-url: {value};\n")

    assert validate_tokens(css) == [
        "tokens.css has a url() that points to the network."
    ]


def test_validate_tokens_allows_local_urls() -> None:
    css = complete_tokens_css(extra_root="  --font-url: url('fonts/a.woff2');\n")

    assert validate_tokens(css) == []


def test_parse_token_blocks_reads_each_theme_block() -> None:
    blocks = parse_token_blocks(complete_tokens_css())

    assert "--bg" in blocks.root
    assert blocks.dark_attribute == {"--bg"}
    assert blocks.dark_media == {"--bg"}


def test_validate_manifest_reports_missing_fields(tmp_path: Path) -> None:
    errors = validate_manifest(
        {"schemaVersion": "other", "files": {"tokens": "missing.css"}}, tmp_path
    )

    assert errors == [
        "manifest.json schemaVersion must be 'od-design-system-project/v1'.",
        "manifest.json is missing 'id'.",
        "manifest.json is missing 'name'.",
        "manifest.json files.design is missing.",
        "manifest.json files.tokens points to a missing file: missing.css.",
    ]


def test_planned_copies_normalize_crlf_line_endings(tmp_path: Path) -> None:
    design = tmp_path / "design"
    write_package(design, complete_tokens_css().replace("\n", "\r\n"))

    copies = planned_copies(design, tmp_path / "assets")

    content = copies[tmp_path / "assets" / "css" / "tokens.css"]
    assert b"\r" not in content


def test_stale_files_detects_missing_and_changed_copies(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh.css"
    fresh.write_bytes(b"same")
    changed = tmp_path / "changed.css"
    changed.write_bytes(b"old")
    missing = tmp_path / "missing.css"

    stale = stale_files({fresh: b"same", changed: b"new", missing: b"x"})

    assert stale == [changed, missing]


def test_check_mode_passes_for_the_repository() -> None:
    assert main(["--check"]) == 0
