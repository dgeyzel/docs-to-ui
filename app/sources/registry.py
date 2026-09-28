"""The language adapter registry and language detection."""

import logging
from functools import cache
from pathlib import PurePosixPath

from app.sources.adapters.base import LanguageAdapter
from app.sources.adapters.openapi import OpenApiAdapter
from app.sources.adapters.python import PythonAdapter
from app.sources.bundle import SkippedFile, SourceBundle, SourceFile
from app.sources.exceptions import InputError

logger = logging.getLogger(__name__)

# Adapters are stateless, so one shared instance of each is enough.
ADAPTERS: dict[str, LanguageAdapter] = {
    adapter.name: adapter for adapter in (OpenApiAdapter(), PythonAdapter())
}


def enabled_adapters(names: list[str]) -> list[LanguageAdapter]:
    """Return the adapters named in `names`, in order.

    Unknown names are skipped with a warning so a stale setting does not
    stop the app from starting.
    """
    adapters: list[LanguageAdapter] = []
    for name in names:
        adapter = ADAPTERS.get(name)
        if adapter is None:
            _warn_unknown_adapter(name)
            continue
        adapters.append(adapter)
    return adapters


@cache
def _warn_unknown_adapter(name: str) -> None:
    logger.warning("Skipping unknown language adapter %s", name)


def display_name(name: str) -> str:
    """Human name for an adapter name, e.g. "openapi" -> "OpenAPI".

    Unknown names are returned unchanged.
    """
    adapter = ADAPTERS.get(name)
    return adapter.display_name if adapter else name


def excluded_by(adapter: LanguageAdapter, path: str) -> str | None:
    """The first of the adapter's default exclude globs matching `path`."""
    pure = PurePosixPath(path)
    for pattern in adapter.default_excludes:
        if pure.full_match(pattern):
            return pattern
    return None


def select_files(
    bundle: SourceBundle, adapter: LanguageAdapter
) -> tuple[SourceBundle, list[SkippedFile]]:
    """Keep the files an adapter reads; report the rest with a reason.

    Only multi-file (zip) bundles are filtered; a single pasted or uploaded
    file is always handed to the adapter, which reports a precise error if
    it can't read it.
    """
    if bundle.origin != "zip":
        return bundle, []
    kept: list[SourceFile] = []
    skipped: list[SkippedFile] = []
    for file in bundle.files:
        pattern = excluded_by(adapter, file.path)
        if pattern is not None:
            skipped.append(SkippedFile(path=file.path, reason=f"excluded: {pattern}"))
        elif not adapter.includes(file.path):
            article = "an" if adapter.display_name[:1].upper() in "AEIOU" else "a"
            reason = f"not {article} {adapter.display_name} file"
            skipped.append(SkippedFile(path=file.path, reason=reason))
        else:
            kept.append(file)
    return SourceBundle(files=kept, origin=bundle.origin, entry=bundle.entry), skipped


def get_adapter(*, name: str, adapters: list[LanguageAdapter]) -> LanguageAdapter:
    """Return the enabled adapter called `name`.

    Raises:
        InputError: No enabled adapter has that name.
    """
    for adapter in adapters:
        if adapter.name == name:
            return adapter
    raise InputError(path="", line=None, message=f"Unsupported language {name!r}.")


def detect(*, bundle: SourceBundle, adapters: list[LanguageAdapter]) -> LanguageAdapter:
    """Return the adapter with the highest sniff score for the bundle.

    Ties go to the adapter listed first.

    Raises:
        InputError: No adapter recognizes the bundle.
    """
    best: LanguageAdapter | None = None
    best_score = 0.0
    for adapter in adapters:
        score = adapter.sniff(bundle)
        if score > best_score:
            best, best_score = adapter, score
    if best is None:
        raise InputError(
            path="",
            line=None,
            message="Could not detect the input language; choose one explicitly.",
        )
    return best
