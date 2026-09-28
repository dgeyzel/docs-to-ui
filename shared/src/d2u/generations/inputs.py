"""Input handling configured from settings, shared by both apps."""

from plain.runtime import settings

from d2u.sources.adapters.base import LanguageAdapter
from d2u.sources.archive import ArchiveLimits
from d2u.sources.intake import PreparedInput, RawInput, prepare_input
from d2u.sources.registry import enabled_adapters


def available_adapters() -> list[LanguageAdapter]:
    """The adapters enabled by `SOURCES_ENABLED_ADAPTERS`."""
    return enabled_adapters(settings.SOURCES_ENABLED_ADAPTERS)


def archive_limits() -> ArchiveLimits:
    """Zip limits from the `SOURCES_ZIP_*` settings."""
    return ArchiveLimits(
        max_uncompressed_bytes=settings.SOURCES_ZIP_MAX_UNCOMPRESSED_BYTES,
        max_file_bytes=settings.SOURCES_ZIP_MAX_FILE_BYTES,
        max_entries=settings.SOURCES_ZIP_MAX_ENTRIES,
    )


def prepare_raw_input(raw: RawInput) -> PreparedInput:
    """Bundle raw input with the enabled adapters and the configured zip limits.

    Raises:
        InputError: The input is unreadable, too large, or its language is unknown.
    """
    return prepare_input(raw, adapters=available_adapters(), limits=archive_limits())
