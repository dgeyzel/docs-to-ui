"""Splitting an input too large for one call into parts (SPEC §6.4)."""

from collections.abc import Mapping
from pathlib import PurePosixPath

CHARS_PER_TOKEN = 4
# Share of the model's input budget used for source files; the rest leaves
# room for instructions, examples and message overhead.
SOURCE_BUDGET_SHARE = 0.8


def estimate_tokens(text: str) -> int:
    """A rough, provider-independent token estimate: four characters per token."""
    return max(1, len(text) // CHARS_PER_TOKEN)


def source_budget(*, max_input_tokens: int, instructions: str) -> int:
    """Tokens available for source files in one call."""
    return max(
        1, int(max_input_tokens * SOURCE_BUDGET_SHARE) - estimate_tokens(instructions)
    )


def split_files(files: Mapping[str, str], *, budget: int) -> list[dict[str, str]]:
    """Group files into parts that each fit in `budget` tokens.

    Files are taken in path order, and files in the same directory are kept
    in the same part where they fit. A single file larger than the budget
    gets a part of its own. Everything fits in one part when it can.
    """
    if sum(estimate_tokens(text) for text in files.values()) <= budget:
        return [dict(files)]

    directories: dict[str, list[str]] = {}
    for path in sorted(files):
        directories.setdefault(str(PurePosixPath(path).parent), []).append(path)

    parts: list[dict[str, str]] = []
    current: dict[str, str] = {}
    current_tokens = 0

    def close() -> None:
        nonlocal current, current_tokens
        if current:
            parts.append(current)
        current, current_tokens = {}, 0

    for paths in directories.values():
        directory_tokens = sum(estimate_tokens(files[path]) for path in paths)
        if directory_tokens <= budget and current_tokens + directory_tokens > budget:
            close()
        for path in paths:
            tokens = estimate_tokens(files[path])
            if current and current_tokens + tokens > budget:
                close()
            current[path] = files[path]
            current_tokens += tokens
    close()
    return parts
