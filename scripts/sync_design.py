"""Validate the OpenDesign package and copy its tokens into the app's assets.

Usage:
    uv run python scripts/sync_design.py          # validate and copy
    uv run python scripts/sync_design.py --check  # validate; fail if the copy is stale

The design package in `design/docs-to-ui/` is read only; it is never modified.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DESIGN_DIR = REPO_ROOT / "design" / "docs-to-ui"
ASSETS_DIR = REPO_ROOT / "app" / "assets"
MANIFEST_SCHEMA_VERSION = "od-design-system-project/v1"

# DESIGN_BRIEF.md §6.1: OpenDesign's shared token contract.
SHARED_TOKENS = (
    "--bg",
    "--surface",
    "--surface-warm",
    "--fg",
    "--fg-2",
    "--muted",
    "--meta",
    "--border",
    "--border-soft",
    "--accent",
    "--accent-on",
    "--accent-hover",
    "--accent-active",
    "--success",
    "--warn",
    "--danger",
    "--font-display",
    "--font-body",
    "--font-mono",
    "--text-xs",
    "--text-sm",
    "--text-base",
    "--text-lg",
    "--text-xl",
    "--text-2xl",
    "--text-3xl",
    "--text-4xl",
    "--leading-body",
    "--leading-tight",
    "--tracking-display",
    "--space-1",
    "--space-2",
    "--space-3",
    "--space-4",
    "--space-5",
    "--space-6",
    "--space-8",
    "--space-12",
    "--section-y-desktop",
    "--section-y-tablet",
    "--section-y-phone",
    "--radius-sm",
    "--radius-md",
    "--radius-lg",
    "--radius-pill",
    "--elev-flat",
    "--elev-ring",
    "--elev-raised",
    "--focus-ring",
    "--motion-fast",
    "--motion-base",
    "--ease-standard",
    "--container-max",
    "--container-gutter-desktop",
    "--container-gutter-tablet",
    "--container-gutter-phone",
)

_METHODS = ("get", "post", "put", "patch", "delete", "other")

# DESIGN_BRIEF.md §6.2: Docs-to-UI extensions.
EXTENSION_TOKENS = (
    "--d2u-info",
    *(f"--d2u-method-{method}" for method in _METHODS),
    *(f"--d2u-method-{method}-bg" for method in _METHODS),
    "--d2u-code-bg",
    "--d2u-code-fg",
    "--d2u-code-border",
    "--d2u-syntax-keyword",
    "--d2u-syntax-string",
    "--d2u-syntax-number",
    "--d2u-syntax-comment",
    "--d2u-syntax-function",
    "--d2u-syntax-type",
    "--d2u-syntax-punctuation",
    "--d2u-sidebar-width",
    "--d2u-header-height",
    "--d2u-span-request",
    "--d2u-span-job",
    "--d2u-span-llm",
    "--d2u-span-db",
    "--d2u-span-stage",
    "--d2u-span-error",
)

REQUIRED_TOKENS = SHARED_TOKENS + EXTENSION_TOKENS

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_DECLARATION = re.compile(r"(--[A-Za-z0-9-]+)\s*:")
_NETWORK_URL = re.compile(r"url\(\s*['\"]?\s*(https?:|//)", re.IGNORECASE)
_DARK_ATTRIBUTE = '[data-theme="dark"]'
_DARK_MEDIA = "@media (prefers-color-scheme: dark)"


@dataclass(frozen=True, slots=True)
class TokenBlocks:
    """Custom properties declared in each theme block of `tokens.css`."""

    root: frozenset[str]
    dark_attribute: frozenset[str]
    dark_media: frozenset[str]


def validate_manifest(manifest: object, design_dir: Path) -> list[str]:
    """Return problems with `manifest.json` (empty when valid).

    Args:
        manifest: The parsed manifest.
        design_dir: Directory the manifest's file entries are relative to.
    """
    if not isinstance(manifest, dict):
        return ["manifest.json must contain a JSON object."]
    errors = []
    if manifest.get("schemaVersion") != MANIFEST_SCHEMA_VERSION:
        errors.append(
            f"manifest.json schemaVersion must be {MANIFEST_SCHEMA_VERSION!r}."
        )
    for key in ("id", "name"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            errors.append(f"manifest.json is missing {key!r}.")
    files = manifest.get("files")
    if not isinstance(files, dict):
        return [*errors, "manifest.json is missing 'files'."]
    for key in ("design", "tokens"):
        name = files.get(key)
        if not isinstance(name, str) or not name:
            errors.append(f"manifest.json files.{key} is missing.")
        elif not (design_dir / name).is_file():
            errors.append(
                f"manifest.json files.{key} points to a missing file: {name}."
            )
    return errors


def _top_level_blocks(css: str) -> list[tuple[str, str]]:
    """Split CSS into (prelude, body) pairs for each top-level block."""
    blocks = []
    depth = 0
    prelude_start = 0
    body_start = 0
    for index, char in enumerate(css):
        if char == "{":
            if depth == 0:
                prelude = css[prelude_start:index]
                body_start = index + 1
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                blocks.append((prelude.strip(), css[body_start:index]))
                prelude_start = index + 1
    return blocks


def parse_token_blocks(css: str) -> TokenBlocks:
    """Collect the custom properties declared in each theme block."""
    css = _COMMENT.sub("", css)
    root: set[str] = set()
    dark_attribute: set[str] = set()
    dark_media: set[str] = set()
    for prelude, body in _top_level_blocks(css):
        if prelude == ":root":
            root.update(_DECLARATION.findall(body))
        elif prelude == _DARK_ATTRIBUTE:
            dark_attribute.update(_DECLARATION.findall(body))
        elif " ".join(prelude.split()) == _DARK_MEDIA:
            for _, inner in _top_level_blocks(body):
                dark_media.update(_DECLARATION.findall(inner))
    return TokenBlocks(
        root=frozenset(root),
        dark_attribute=frozenset(dark_attribute),
        dark_media=frozenset(dark_media),
    )


def validate_tokens(css: str) -> list[str]:
    """Return problems with `tokens.css` (empty when valid)."""
    blocks = parse_token_blocks(css)
    errors = [
        f"tokens.css :root is missing {token}."
        for token in REQUIRED_TOKENS
        if token not in blocks.root
    ]
    if not blocks.dark_attribute:
        errors.append(f"tokens.css has no {_DARK_ATTRIBUTE} block.")
    if not blocks.dark_media:
        errors.append(f"tokens.css has no {_DARK_MEDIA} block.")
    if _NETWORK_URL.search(_COMMENT.sub("", css)):
        errors.append("tokens.css has a url() that points to the network.")
    return errors


def normalize_newlines(text: str) -> str:
    """Convert CRLF and CR line endings to LF."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def planned_copies(design_dir: Path, assets_dir: Path) -> dict[Path, bytes]:
    """Map each destination file to the content it should have."""
    tokens = normalize_newlines((design_dir / "tokens.css").read_text(encoding="utf-8"))
    copies = {assets_dir / "css" / "tokens.css": tokens.encode("utf-8")}
    fonts_dir = design_dir / "fonts"
    if fonts_dir.is_dir():
        for font in sorted(fonts_dir.glob("*.woff2")):
            copies[assets_dir / "fonts" / font.name] = font.read_bytes()
    return copies


def stale_files(copies: dict[Path, bytes]) -> list[Path]:
    """Destinations whose content differs from what they should contain."""
    return [
        path
        for path, content in copies.items()
        if not path.is_file() or path.read_bytes() != content
    ]


def validate_package(design_dir: Path) -> list[str]:
    """Validate the manifest and tokens of a design package."""
    manifest_path = design_dir / "manifest.json"
    if not manifest_path.is_file():
        return [f"{manifest_path} does not exist."]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"manifest.json is not valid JSON: {exc}."]
    errors = validate_manifest(manifest, design_dir)
    tokens_path = design_dir / "tokens.css"
    if tokens_path.is_file():
        errors.extend(validate_tokens(tokens_path.read_text(encoding="utf-8")))
    return errors


def main(argv: list[str] | None = None) -> int:
    """Run the sync. Returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate and fail if the app's copy is stale, without writing.",
    )
    args = parser.parse_args(argv)

    errors = validate_package(DESIGN_DIR)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    copies = planned_copies(DESIGN_DIR, ASSETS_DIR)
    stale = stale_files(copies)
    if args.check:
        for path in stale:
            print(f"stale: {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        if stale:
            print("Run: uv run python scripts/sync_design.py", file=sys.stderr)
            return 1
        print("Design tokens are in sync.")
        return 0

    fonts_dir = ASSETS_DIR / "fonts"
    if fonts_dir.is_dir():
        wanted = {path for path in copies if path.parent == fonts_dir}
        for existing in fonts_dir.glob("*.woff2"):
            if existing not in wanted:
                existing.unlink()
    for path in stale:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(copies[path])
        print(f"wrote: {path.relative_to(REPO_ROOT)}")
    if not stale:
        print("Design tokens already in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
