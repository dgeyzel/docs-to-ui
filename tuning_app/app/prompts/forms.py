import json
from typing import Any

import pydantic
from d2u.generation.prompts import PromptSpec
from d2u.registry.models import PromptVersion
from plain import forms
from plain.http import Request

MAX_IMPORT_BYTES = 1048576


def _first_error(exc: pydantic.ValidationError) -> str:
    error = exc.errors()[0]
    where = ".".join(str(part) for part in error["loc"])
    return f"{where}: {error['msg']}" if where else str(error["msg"])


def version_choices() -> list[tuple[str, str]]:
    return [
        (str(prompt.id), str(prompt))
        for prompt in PromptVersion.query.order_by("language", "strategy", "version")
    ]


class NewVersionForm(forms.Form):
    """A new draft copied from an existing version."""

    base = forms.ChoiceField(choices=version_choices)
    version = forms.TextField(max_length=64)

    def base_version(self) -> PromptVersion:
        """The version to copy. Only call after `is_valid()` returned True."""
        return PromptVersion.query.get(int(self.cleaned_data["base"]))


class ImportForm(forms.Form):
    """A prompt version JSON file, as exported from this page."""

    file = forms.FileField(max_length=255)

    def clean_file(self) -> PromptSpec:
        uploaded = self.cleaned_data["file"]
        if uploaded.size > MAX_IMPORT_BYTES:
            raise forms.ValidationError("The file is larger than 1 MB.")
        try:
            return PromptSpec.model_validate_json(uploaded.read())
        except pydantic.ValidationError as exc:
            raise forms.ValidationError(
                f"Not a valid prompt version file ({_first_error(exc)})."
            ) from exc


class DraftForm(forms.Form):
    """A draft's instructions and few-shot examples (JSON, validated by Pydantic)."""

    instructions = forms.TextField(strip=False)
    examples = forms.TextField(required=False, strip=False)

    def __init__(
        self, *, request: Request, prompt: PromptVersion, **kwargs: Any
    ) -> None:
        super().__init__(request=request, **kwargs)
        self.prompt = prompt

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if self.errors:
            return cleaned
        raw = (cleaned.get("examples") or "").strip() or "[]"
        try:
            examples = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.add_error(
                "examples", forms.ValidationError(f"Not valid JSON ({exc.msg}).")
            )
            return cleaned
        key = "page_examples" if self.prompt.strategy == "llm" else "docs_examples"
        try:
            cleaned["spec"] = PromptSpec.model_validate(
                {
                    "language": self.prompt.language,
                    "strategy": self.prompt.strategy,
                    "version": self.prompt.version,
                    "instructions": cleaned["instructions"],
                    key: examples,
                }
            )
        except pydantic.ValidationError as exc:
            self.add_error("examples", forms.ValidationError(_first_error(exc)))
        return cleaned


class PromoteForm(forms.Form):
    """Promote a version, optionally copying the scores of one of its eval runs."""

    eval_run = forms.TextField(required=False, max_length=20)
    note = forms.TextField(required=False, max_length=500)
