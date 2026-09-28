from typing import Any

import pydantic
from d2u.generations.inputs import available_adapters
from d2u.registry.models import ModelConfig
from d2u.schemas.gold import GOLD_SPLITS, GoldInput, GoldSetFile
from d2u.sources.bundle import normalize_filename
from d2u.sources.exceptions import InputError
from d2u.sources.intake import RawInput
from plain import forms
from plain.http import Request
from plain.runtime import settings

from app.goldsets.models import GoldSet
from app.goldsets.services import describe_input_error, gold_input_from_raw

FILL_CHOICES = [
    ("empty", "Start empty"),
    ("parser", "Seed from the parser"),
    ("model", "Seed from a model"),
]


def language_choices() -> list[tuple[str, str]]:
    """Every enabled language."""
    return [(adapter.name, adapter.display_name) for adapter in available_adapters()]


def generation_model_choices() -> list[tuple[str, str]]:
    """Models enabled for generation, by ID."""
    return [
        (str(model.id), model.name)
        for model in ModelConfig.query.filter(enabled_for_generation=True).order_by(
            "name"
        )
    ]


def _megabytes(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MB"


class GoldSetForm(forms.Form):
    """A new, empty gold set."""

    name = forms.TextField(max_length=100)
    language = forms.ChoiceField(choices=language_choices)

    def clean_name(self) -> str:
        name = self.cleaned_data["name"]
        if GoldSet.query.filter(name=name).exists():
            raise forms.ValidationError("A gold set with this name already exists.")
        return name


class GoldSetImportForm(forms.Form):
    """A gold-set JSON file (see `d2u.schemas.gold.GoldSetFile`)."""

    file = forms.FileField(max_length=255)

    def clean_file(self) -> GoldSetFile:
        uploaded = self.cleaned_data["file"]
        limit = settings.GOLDSETS_MAX_IMPORT_BYTES
        if uploaded.size > limit:
            raise forms.ValidationError(
                f"The file exceeds the {_megabytes(limit)} limit."
            )
        try:
            return GoldSetFile.model_validate_json(uploaded.read())
        except pydantic.ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(part) for part in first["loc"])
            raise forms.ValidationError(
                f"Not a valid gold-set file ({where}: {first['msg']})."
            ) from exc


class ExampleCreateForm(forms.Form):
    """Source for a new example (as the Docs app accepts it) and how to fill its page."""

    file = forms.FileField(required=False, max_length=255)
    text = forms.TextField(required=False, strip=False)
    entry = forms.TextField(required=False, max_length=255)
    fill = forms.ChoiceField(choices=FILL_CHOICES)
    model = forms.ChoiceField(choices=generation_model_choices, required=False)
    notes = forms.TextField(required=False)

    def __init__(self, *, request: Request, gold_set: GoldSet, **kwargs: Any) -> None:
        super().__init__(request=request, **kwargs)
        self.gold_set = gold_set

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if self.errors:
            return cleaned
        if cleaned.get("fill") == "model" and not cleaned.get("model"):
            self.add_error("model", forms.ValidationError("Choose a model."))
            return cleaned
        raw = self._raw_input(cleaned)
        if raw is None:
            return cleaned
        try:
            cleaned["gold_input"] = gold_input_from_raw(raw)
        except InputError as exc:
            raise forms.ValidationError(describe_input_error(exc)) from exc
        return cleaned

    def _raw_input(self, cleaned: dict[str, Any]) -> RawInput | None:
        uploaded = cleaned.get("file")
        text = cleaned.get("text") or ""
        limit = settings.GENERATIONS_MAX_INPUT_BYTES
        if uploaded and text.strip():
            self.add_error(
                None, forms.ValidationError("Upload a file or paste text, not both.")
            )
            return None
        if not uploaded and not text.strip():
            self.add_error(
                None, forms.ValidationError("Upload a file or paste some text.")
            )
            return None
        if uploaded:
            if uploaded.size > limit:
                self.add_error(
                    "file",
                    forms.ValidationError(
                        f"File exceeds the {_megabytes(limit)} limit."
                    ),
                )
                return None
            filename = normalize_filename(uploaded.name)
            is_zip = filename.lower().endswith(".zip")
            return RawInput(
                origin="zip" if is_zip else "file",
                data=uploaded.read(),
                filename=filename,
                language=self.gold_set.language,
                entry=(cleaned.get("entry") or "").strip() if is_zip else "",
            )
        data = text.encode("utf-8")
        if len(data) > limit:
            self.add_error(
                "text",
                forms.ValidationError(
                    f"Pasted text exceeds the {_megabytes(limit)} limit."
                ),
            )
            return None
        return RawInput(origin="paste", data=data, language=self.gold_set.language)

    def gold_input(self) -> GoldInput:
        """The bundled input. Only call after `is_valid()` returned True."""
        return self.cleaned_data["gold_input"]

    def chosen_model(self) -> ModelConfig | None:
        """The model to seed from, when filling from a model."""
        value = self.cleaned_data.get("model")
        return ModelConfig.query.get(int(value)) if value else None


class ReviewForm(forms.Form):
    """An example's split and reviewer notes."""

    split = forms.ChoiceField(choices=[(split, split) for split in GOLD_SPLITS])
    notes = forms.TextField(required=False)


class FillForm(forms.Form):
    """Replace an example's expected page from the parser or a model."""

    fill = forms.ChoiceField(choices=FILL_CHOICES[1:])
    model = forms.ChoiceField(choices=generation_model_choices, required=False)

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if cleaned.get("fill") == "model" and not cleaned.get("model"):
            self.add_error("model", forms.ValidationError("Choose a model."))
        return cleaned

    def chosen_model(self) -> ModelConfig | None:
        """The model to seed from, when filling from a model."""
        value = self.cleaned_data.get("model")
        return ModelConfig.query.get(int(value)) if value else None


class BulkSplitForm(forms.Form):
    """Move the selected examples to one split."""

    examples = forms.MultipleChoiceField(choices=[], required=True)
    split = forms.ChoiceField(choices=[(split, split) for split in GOLD_SPLITS])

    def __init__(
        self, *, request: Request, example_ids: list[int], **kwargs: Any
    ) -> None:
        super().__init__(request=request, **kwargs)
        self.fields["examples"].choices = [(str(i), str(i)) for i in example_ids]  # ty: ignore[unresolved-attribute]

    def selected_ids(self) -> list[int]:
        """The selected example IDs."""
        return [int(value) for value in self.cleaned_data["examples"]]
