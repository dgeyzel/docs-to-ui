"""The JSONL datasets: inputs to document, as the app would receive them.

Kept for the Tuning app's gold sets (milestone R4), which start from them.
"""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from d2u.schemas.docpage import ApiSurface
from d2u.sources.adapters.base import LanguageAdapter
from d2u.sources.bundle import SourceBundle, SourceFile
from d2u.sources.registry import ADAPTERS, select_files
from pydantic import BaseModel, ConfigDict

DATASETS_DIR = Path(__file__).resolve().parent / "datasets"
LANGUAGES = ("openapi", "python")
Split = Literal["train", "dev"]


class DatasetEntry(BaseModel):
    """One input to document: its files as they would arrive in the app."""

    model_config = ConfigDict(frozen=True)

    id: str
    language: str
    origin: Literal["paste", "file", "zip"]
    files: dict[str, str]
    entry: str | None = None
    operation_id: str | None = None
    comment: str | None = None


def load_entries(*, languages: Sequence[str], split: Split) -> list[DatasetEntry]:
    """Read the dataset entries for the given languages and split."""
    entries: list[DatasetEntry] = []
    for language in languages:
        path = DATASETS_DIR / language / f"{split}.jsonl"
        with path.open(encoding="utf-8") as handle:
            entries.extend(
                DatasetEntry.model_validate_json(line)
                for line in handle
                if line.strip()
            )
    return entries


def dataset_hash(entries: Sequence[DatasetEntry]) -> str:
    """A stable hash of the entries, recorded in artifact metadata."""
    canonical = json.dumps(
        [entry.model_dump(mode="json") for entry in entries], sort_keys=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def entry_surface(entry: DatasetEntry) -> tuple[ApiSurface, LanguageAdapter]:
    """Extract an entry's surface exactly as the app would."""
    adapter = ADAPTERS[entry.language]
    bundle = SourceBundle(
        files=[
            SourceFile(path=path, text=text)
            for path, text in sorted(entry.files.items())
        ],
        origin=entry.origin,
        entry=entry.entry,
    )
    selected, _ = select_files(bundle, adapter)
    return adapter.extract(selected), adapter
