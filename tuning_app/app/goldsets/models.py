from datetime import datetime
from enum import StrEnum

from d2u.schemas.docpage import DocPage
from d2u.schemas.gold import GOLD_SPLITS, GoldInput
from plain import postgres
from plain.postgres import Field, types


class ExampleStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"


class SeedStatus(StrEnum):
    """Filling an example's expected page from a model, in the background."""

    NONE = ""
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"


def _choices(values: list[str] | tuple[str, ...]) -> list[tuple[str, str]]:
    return [(value, value) for value in values]


@postgres.register_model
class GoldSet(postgres.Model):
    """A named collection of gold examples for one language (SPEC §9.2)."""

    name: Field[str] = types.TextField(max_length=100)
    language: Field[str] = types.TextField(max_length=32)
    notes: Field[str] = types.TextField(required=False, default="")
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    updated_at: Field[datetime] = types.DateTimeField(create_now=True, update_now=True)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["name"], name="goldsets_goldset_name_unique"
            ),
        ],
    )

    def __str__(self) -> str:
        return self.name


@postgres.register_model
class GoldExample(postgres.Model):
    """One input and its reference page (SPEC §9.2).

    `input` holds a `GoldInput` and `expected` a `DocPage`, both stored with
    `model_dump(mode="json")` and read back through the typed accessors.
    """

    gold_set: Field[GoldSet] = types.ForeignKeyField(
        GoldSet, on_delete=postgres.CASCADE, related_query_name="examples"
    )
    input: Field[dict] = types.JSONField()
    expected: Field[dict] = types.JSONField()
    split: Field[str] = types.TextField(
        max_length=8, choices=_choices(GOLD_SPLITS), default="train"
    )
    status: Field[str] = types.TextField(
        max_length=16,
        choices=_choices([status.value for status in ExampleStatus]),
        default=ExampleStatus.DRAFT.value,
    )
    source: Field[str] = types.TextField(max_length=100, default="manual")
    notes: Field[str] = types.TextField(required=False, default="")
    seed_status: Field[str] = types.TextField(
        max_length=16,
        choices=_choices([status.value for status in SeedStatus]),
        required=False,
        default="",
    )
    seed_error: Field[str] = types.TextField(required=False, default="")
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    updated_at: Field[datetime] = types.DateTimeField(create_now=True, update_now=True)

    model_options = postgres.Options(
        indexes=[
            postgres.Index(
                fields=["gold_set", "split", "status"],
                name="goldsets_goldexample_gold_set_split_status_idx",
            ),
        ],
    )

    def __str__(self) -> str:
        return f"Example {self.id} of {self.gold_set.name}"

    def gold_input(self) -> GoldInput:
        """The stored input, validated."""
        return GoldInput.model_validate(self.input)

    def expected_page(self) -> DocPage:
        """The stored reference page, validated."""
        return DocPage.model_validate(self.expected)

    @property
    def label(self) -> str:
        """A short name for lists: the entry file, or the first file's path."""
        gold_input = self.gold_input()
        return gold_input.entry or min(gold_input.files)

    @property
    def seeding(self) -> bool:
        """Whether a model is still filling in the expected page."""
        return self.seed_status in (SeedStatus.PENDING, SeedStatus.RUNNING)


@postgres.register_model
class GoldExampleRevision(postgres.Model):
    """A snapshot of an example after each change, for its history."""

    example: Field[GoldExample] = types.ForeignKeyField(
        GoldExample, on_delete=postgres.CASCADE
    )
    change: Field[str] = types.TextField(max_length=100)
    expected: Field[dict] = types.JSONField()
    split: Field[str] = types.TextField(max_length=8)
    status: Field[str] = types.TextField(max_length=16)
    notes: Field[str] = types.TextField(required=False, default="")
    created_at: Field[datetime] = types.DateTimeField(create_now=True)

    model_options = postgres.Options(
        indexes=[
            postgres.Index(
                fields=["example", "created_at"],
                name="goldsets_goldexamplerevision_example_created_at_idx",
            ),
        ],
    )

    def __str__(self) -> str:
        return f"{self.change} ({self.created_at:%Y-%m-%d %H:%M})"
