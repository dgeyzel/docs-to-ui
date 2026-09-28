import re
from typing import Any

from d2u.generations.models import InputOrigin
from d2u.sources.bundle import normalize_filename
from plain import forms
from plain.runtime import settings

from app.generate.pipeline import SubmittedInput, available_adapters


def language_choices() -> list[tuple[str, str]]:
    """ "Auto-detect" followed by every enabled adapter."""
    return [("", "Auto-detect")] + [
        (adapter.name, adapter.display_name) for adapter in available_adapters()
    ]


def format_megabytes(size: int) -> str:
    """Format a byte count as megabytes, e.g. "5.0 MB"."""
    return f"{size / (1024 * 1024):.1f} MB"


class SourceForm(forms.Form):
    """A single uploaded file or pasted text, plus an optional language."""

    file = forms.FileField(required=False, max_length=255)
    text = forms.TextField(required=False, strip=False)
    language = forms.ChoiceField(choices=language_choices, required=False)
    entry = forms.TextField(required=False, max_length=255)

    def parse_entry(self) -> str:
        # Optional in submitted data: older clients and scripts may omit it.
        return self.data.get("entry", "")

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        uploaded = cleaned.get("file")
        text = cleaned.get("text") or ""
        has_text = bool(text.strip())
        limit = settings.GENERATIONS_MAX_INPUT_BYTES

        if uploaded and has_text:
            raise forms.ValidationError("Upload a file or paste text, not both.")
        if not uploaded and not has_text:
            raise forms.ValidationError("Upload a file or paste some text.")

        if uploaded:
            if uploaded.size > limit:
                self.add_error(
                    "file",
                    forms.ValidationError(
                        f"File exceeds the {format_megabytes(limit)} limit "
                        f"(actual: {format_megabytes(uploaded.size)})."
                    ),
                )
        elif len(text.encode("utf-8")) > limit:
            self.add_error(
                "text",
                forms.ValidationError(
                    f"Pasted text exceeds the {format_megabytes(limit)} limit."
                ),
            )
        return cleaned

    def selected_source(self) -> str:
        """Which input tab to show: "paste" if text was submitted, else "file"."""
        text = self["text"]
        if self.is_bound and (text.value() or text.errors):
            return "paste"
        return "file"

    def selected_language(self) -> str:
        """The submitted language choice ("" for auto-detect)."""
        return self["language"].value() or ""

    def submitted_input(self) -> SubmittedInput:
        """The validated input. Only call after `is_valid()` returned True."""
        uploaded = self.cleaned_data.get("file")
        language = self.cleaned_data.get("language") or ""
        if uploaded:
            filename = normalize_filename(uploaded.name)
            is_zip = filename.lower().endswith(".zip")
            return SubmittedInput(
                origin=InputOrigin.ZIP if is_zip else InputOrigin.FILE,
                filename=filename,
                data=uploaded.read(),
                language=language,
                entry=(self.cleaned_data.get("entry") or "").strip() if is_zip else "",
            )
        return SubmittedInput(
            origin=InputOrigin.PASTE,
            filename="",
            data=self.cleaned_data["text"].encode("utf-8"),
            language=language,
        )


class FeedbackForm(forms.Form):
    """A 👍 / 👎 with an optional correction comment."""

    operation_id = forms.TextField(required=False, max_length=512)
    score = forms.TypedChoiceField(
        choices=[("1", "Helpful"), ("-1", "Not helpful")], coerce=int
    )
    comment = forms.TextField(required=False, max_length=5000)
    anchor = forms.TextField(required=False, max_length=200)

    def clean_anchor(self) -> str:
        anchor = self.cleaned_data.get("anchor") or ""
        return anchor if re.fullmatch(r"[a-z0-9-]*", anchor) else ""
