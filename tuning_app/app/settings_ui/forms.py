from d2u.telemetry.config import BACKEND_NAMES, backend_options, normalize_selection
from plain import forms


class TraceBackendsForm(forms.Form):
    """Which trace backends receive spans from both apps (SPEC §11.2).

    Any subset is allowed, including none. A backend whose environment
    variables are missing in this process can't be chosen.
    """

    trace_backends = forms.MultipleChoiceField(
        choices=[(name, name) for name in BACKEND_NAMES], required=False
    )

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
