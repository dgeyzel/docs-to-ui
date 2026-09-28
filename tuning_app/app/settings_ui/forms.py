from d2u.registry.models import ModelConfig
from d2u.telemetry.config import BACKEND_NAMES, backend_options, normalize_selection
from plain import forms


def judge_choices() -> list[tuple[str, str]]:
    """Models enabled for judging, by ID."""
    return [
        (str(model.id), model.name)
        for model in ModelConfig.query.filter(enabled_for_judging=True).order_by("name")
    ]


class RuntimeSettingsForm(forms.Form):
    """Runtime choices shared by both apps (SPEC §9.1, §11.2).

    Any subset of trace backends is allowed, including none. A backend whose
    environment variables are missing in this process can't be chosen.
    """

    trace_backends = forms.MultipleChoiceField(
        choices=[(name, name) for name in BACKEND_NAMES], required=False
    )
    default_judge = forms.ChoiceField(choices=judge_choices, required=False)

    def clean_trace_backends(self) -> list[str]:
        chosen = normalize_selection(self.cleaned_data["trace_backends"])
        for option in backend_options():
            if option.name in chosen and not option.available:
                verb = "is" if len(option.missing) == 1 else "are"
                raise forms.ValidationError(
                    f"{option.label} can't be selected until "
                    f"{', '.join(option.missing)} {verb} set."
                )
        return chosen

    def chosen_judge(self) -> ModelConfig | None:
        """The selected default judge, or None for no default."""
        value = self.cleaned_data.get("default_judge")
        return ModelConfig.query.get(int(value)) if value else None
