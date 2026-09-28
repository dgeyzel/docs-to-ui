"""Exceptions raised while turning user input into a `SourceBundle` or `ApiSurface`."""


class SourcesError(Exception):
    """Base class for every error raised by the sources package."""


class InputError(SourcesError):
    """The input is invalid. Carries the bundle path and line where known.

    Args:
        path: Path of the offending file inside the bundle ("" if not file-specific).
        line: 1-based line number, or None when no line applies.
        message: Human-readable explanation, safe to show to the user.
    """

    def __init__(self, *, path: str, line: int | None, message: str) -> None:
        self.path = path
        self.line = line
        self.message = message
        super().__init__(self.location_prefix() + message)

    def location_prefix(self) -> str:
        """Return `path:line: ` (or the parts that are known) for display."""
        if not self.path:
            return ""
        if self.line is None:
            return f"{self.path}: "
        return f"{self.path}:{self.line}: "


class ArchiveLimitError(InputError):
    """An archive exceeded a size or entry limit while it was being read."""
