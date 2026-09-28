import re
from typing import Any

from d2u.generation.params import coerce_param, offered_params
from d2u.registry.models import ModelConfig, RuntimeSettings
from plain import forms
from plain.http import Request

ENV_VAR_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
PARAM_PREFIX = "param_"


class ModelConfigForm(forms.Form):
    """Add or edit a registered model (SPEC §7).

    Call parameters are read from `param_<name>` inputs, and only the ones
    offered for the submitted LiteLLM model string are kept.
    """

    name = forms.TextField(max_length=100)
    litellm_model = forms.TextField(max_length=200)
    api_key_env = forms.TextField(max_length=100, required=False)
    api_base = forms.URLField(max_length=500, required=False)
    max_input_tokens = forms.IntegerField(min_value=1000, max_value=10_000_000)
    enabled_for_generation = forms.BooleanField(required=False)
    enabled_for_judging = forms.BooleanField(required=False)
    notes = forms.TextField(required=False)

    def __init__(
        self, *, request: Request, instance: ModelConfig | None = None, **kwargs: Any
    ) -> None:
        super().__init__(request=request, **kwargs)
        self.instance = instance
        self.param_errors: dict[str, str] = {}

    def clean_name(self) -> str:
        name = self.cleaned_data["name"]
        clash = ModelConfig.query.filter(name=name)
        if self.instance is not None:
            clash = clash.exclude(id=self.instance.id)
        if clash.exists():
            raise forms.ValidationError("A model with this name already exists.")
        return name

    def clean_api_key_env(self) -> str:
        value = self.cleaned_data["api_key_env"]
        if value and not ENV_VAR_NAME.match(value):
            raise forms.ValidationError(
                "Use an environment variable name such as GEMINI_API_KEY."
            )
        return value

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        cleaned["params"] = self._clean_params(cleaned.get("litellm_model") or "")
        if self.instance is not None:
            runtime = RuntimeSettings.load()
            if (
                runtime.active_model is not None
                and runtime.active_model.id == self.instance.id
                and not cleaned.get("enabled_for_generation")
            ):
                self.add_error(
                    "enabled_for_generation",
                    forms.ValidationError(
                        "This is the Docs app's active model; "
                        "activate another model first."
                    ),
                )
            if (
                runtime.default_judge_model is not None
                and runtime.default_judge_model.id == self.instance.id
                and not cleaned.get("enabled_for_judging")
            ):
                self.add_error(
                    "enabled_for_judging",
                    forms.ValidationError(
                        "This is the default judge; "
                        "choose another judge in Settings first."
                    ),
                )
        return cleaned

    def _clean_params(self, litellm_model: str) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for spec in offered_params(litellm_model):
            raw = str(self.data.get(PARAM_PREFIX + spec.name, "") or "")
            if not raw.strip():
                continue
            try:
                params[spec.name] = coerce_param(spec, raw)
            except ValueError as exc:
                self.param_errors[spec.name] = str(exc)
        if self.param_errors:
            self.add_error(None, forms.ValidationError("Some parameters are invalid."))
        return params

    def apply_to(self, model: ModelConfig) -> None:
        """Copy the validated values onto a model (not yet written)."""
        data = self.cleaned_data
        model.name = data["name"]
        model.litellm_model = data["litellm_model"]
        model.api_key_env = data["api_key_env"] or ""
        model.api_base = data["api_base"] or ""
        model.max_input_tokens = data["max_input_tokens"]
        model.enabled_for_generation = bool(data["enabled_for_generation"])
        model.enabled_for_judging = bool(data["enabled_for_judging"])
        model.notes = data["notes"] or ""
        model.params = data["params"]
