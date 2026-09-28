"""Line diffs between two prompt versions, for the Prompts page. Plain-free."""

import difflib
import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiffLine:
    """One line of a unified diff: "+" added, "-" removed, " " unchanged, "@" a hunk."""

    kind: str
    text: str


def line_diff(old: str, new: str, *, context: int = 3) -> list[DiffLine]:
    """A unified diff of two texts, without the file header lines."""
    lines = difflib.unified_diff(
        old.splitlines(), new.splitlines(), lineterm="", n=context
    )
    diff: list[DiffLine] = []
    for line in lines:
        if line.startswith(("---", "+++")):
            continue
        kind = "@" if line.startswith("@@") else line[:1] or " "
        diff.append(DiffLine(kind=kind, text=line if kind == "@" else line[1:]))
    return diff


def examples_text(examples: list) -> str:
    """Examples as stable, indented JSON, so their diff is readable."""
    return json.dumps(examples, indent=2, sort_keys=True, ensure_ascii=False)
