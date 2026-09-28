"""Starter gold sets from the example inputs shipped with the Tuning app.

Each language gets a draft set whose expected pages are seeded from the
parser, ready to review and correct. Loading is idempotent: a starter set
that already exists is left alone.
"""

from pathlib import Path

from d2u.schemas.gold import GoldInput, GoldSplit
from plain.postgres import transaction
from pydantic import BaseModel, ConfigDict

from app.goldsets.models import GoldSet
from app.goldsets.services import adapter_for, create_example, parser_page

STARTER_DIR = Path(__file__).resolve().parent / "starter_data"
STARTER_SPLITS: tuple[GoldSplit, ...] = ("train", "dev")


class StarterEntry(BaseModel):
    """One shipped input: its files as the app would receive them."""

    model_config = ConfigDict(frozen=True)

    id: str
    language: str
    origin: str
    files: dict[str, str]
    entry: str | None = None
    comment: str | None = None


def load_entries(language: str, split: GoldSplit) -> list[StarterEntry]:
    """The shipped inputs for a language and split."""
    path = STARTER_DIR / language / f"{split}.jsonl"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [
            StarterEntry.model_validate_json(line) for line in handle if line.strip()
        ]


def starter_set_name(language: str) -> str:
    """The name of a language's starter set."""
    return f"Starter ({adapter_for(language).display_name})"


def load_starter_sets(languages: list[str]) -> list[GoldSet]:
    """Create the missing starter sets; returns the sets created."""
    created: list[GoldSet] = []
    for language in languages:
        name = starter_set_name(language)
        entries = [
            (split, entry)
            for split in STARTER_SPLITS
            for entry in load_entries(language, split)
        ]
        if not entries or GoldSet.query.filter(name=name).exists():
            continue
        with transaction.atomic():
            gold_set = _create_starter_set(name, language, entries)
        created.append(gold_set)
    return created


def _create_starter_set(
    name: str, language: str, entries: list[tuple[GoldSplit, StarterEntry]]
) -> GoldSet:
    gold_set = GoldSet(
        name=name,
        language=language,
        notes="Shipped example inputs with parser-seeded pages. Review before approving.",
    )
    gold_set.create()
    for split, entry in entries:
        gold_input = GoldInput.model_validate(
            {"origin": entry.origin, "files": entry.files, "entry": entry.entry}
        )
        create_example(
            gold_set,
            gold_input=gold_input,
            expected=parser_page(language, gold_input),
            source="parser_seed",
            notes=entry.comment or f"Starter input {entry.id}.",
            split=split,
            change="Seeded from the parser",
        )
    return gold_set
