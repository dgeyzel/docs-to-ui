"""The interface every source language adapter implements."""

from typing import Protocol

from d2u.schemas.docpage import ApiSurface, Operation
from d2u.sources.bundle import SourceBundle


class LanguageAdapter(Protocol):
    """Turns a `SourceBundle` into an `ApiSurface` deterministically."""

    name: str
    display_name: str
    file_extensions: tuple[str, ...]
    default_excludes: tuple[str, ...]
    example_languages: tuple[str, ...]

    def includes(self, path: str) -> bool:
        """Whether a bundle path is a file this adapter reads."""
        ...

    def sniff(self, bundle: SourceBundle) -> float:
        """Confidence from 0.0 to 1.0 that the bundle is in this language."""
        ...

    def extract(self, bundle: SourceBundle) -> ApiSurface:
        """Extract the API surface.

        Raises:
            InputError: The input is invalid; carries path and line.
        """
        ...

    def group_key(self, op: Operation) -> str:
        """Navigation and batching group for an operation."""
        ...

    def check_syntax(self, bundle: SourceBundle) -> None:
        """Check the input parses, without extracting structure.

        Used before the `llm` strategy sends source to a model, so broken
        input fails fast with a precise location.

        Raises:
            InputError: A file doesn't parse; carries path and line.
        """
        ...

    def entry_file(self, bundle: SourceBundle) -> str | None:
        """The file the API is defined in, for languages that have one.

        Raises:
            InputError: Several files qualify and the bundle names none.
        """
        ...
