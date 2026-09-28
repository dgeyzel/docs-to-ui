"""Gold-set contracts: example inputs and the gold-set import file (SPEC §9.2).

Plain-free. The Tuning app stores these as JSON and reads them back through
`model_validate`.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from d2u.schemas.docpage import DocPage

GoldSplit = Literal["train", "dev", "test"]
GoldStatus = Literal["draft", "approved"]
GOLD_SPLITS: tuple[GoldSplit, ...] = ("train", "dev", "test")


class GoldInput(BaseModel):
    """The source files as the Docs app would receive them, after bundling.

    `files` holds the files the language's adapter reads (for a zip, the
    included files); `entry` names the chosen entry file, if any.
    """

    model_config = ConfigDict(frozen=True)

    origin: Literal["paste", "file", "zip"]
    files: dict[str, str]
    entry: str | None = None

    @field_validator("files")
    @classmethod
    def _has_files(cls, files: dict[str, str]) -> dict[str, str]:
        if not files:
            raise ValueError("an example needs at least one file")
        return files


class GoldExampleFile(BaseModel):
    """One example in a gold-set import file."""

    model_config = ConfigDict(frozen=True)

    input: GoldInput
    expected: DocPage
    split: GoldSplit = "train"
    status: GoldStatus = "draft"
    notes: str = ""


class GoldSetFile(BaseModel):
    """A gold set as imported from a JSON file."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=100)
    language: str
    examples: list[GoldExampleFile]
