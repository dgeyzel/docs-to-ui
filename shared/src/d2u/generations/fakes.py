"""Fixture answers for the fake model, shared by both apps (tests only)."""

from functools import cache
from pathlib import Path

from plain.runtime import APP_PATH, settings

from d2u.generation.client import FakeResponses

# Both apps live one level below the repository root, where fixtures are.
REPO_ROOT = APP_PATH.parent.parent


def fake_responses() -> FakeResponses | None:
    """Fixture answers for the fake model, when `GENERATIONS_FAKE_RESPONSES` is set."""
    if not settings.GENERATIONS_FAKE_RESPONSES:
        return None
    return _load_fake_responses(settings.GENERATIONS_FAKE_RESPONSES)


@cache
def _load_fake_responses(configured: str) -> FakeResponses:
    path = Path(configured)
    return FakeResponses.from_file(path if path.is_absolute() else REPO_ROOT / path)
