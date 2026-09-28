from typing import Any

from d2u.registry.lookups import trace_backends
from d2u.registry.models import RuntimeSettings
from d2u.telemetry.config import backend_options, invalidate_selection
from plain.http import Response
from plain.runtime import settings
from plain.templates.views import FormView
from plain.urls import reverse

from app.settings_ui.forms import RuntimeSettingsForm


class SettingsView(FormView[RuntimeSettingsForm]):
    """Runtime settings shared by both apps; the only place they change."""

    template_name = "settings_ui/index.html"
    form_class = RuntimeSettingsForm

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        runtime = RuntimeSettings.load()
        kwargs["initial"] = {
            "trace_backends": trace_backends(),
            "default_judge": (
                str(runtime.default_judge_model.id)
                if runtime.default_judge_model
                else ""
            ),
        }
        return kwargs

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["backend_options"] = backend_options()
        context["ttl_s"] = settings.TELEMETRY_SETTINGS_TTL_S
        runtime = RuntimeSettings.load()
        judge, active = runtime.default_judge_model, runtime.active_model
        context["judge_is_generation_model"] = bool(
            judge and active and judge.id == active.id
        )
        context["saved"] = self.request.query_params.get("saved") == "1"
        return context

    def get_success_url(self, form: RuntimeSettingsForm) -> str:
        return reverse("settings:index") + "?saved=1"

    def form_valid(self, form: RuntimeSettingsForm) -> Response:
        runtime = RuntimeSettings.load()
        runtime.trace_backends = form.cleaned_data["trace_backends"]
        runtime.default_judge_model = form.chosen_judge()
        runtime.update()
        # Other processes pick the change up within the TTL; this one now.
        invalidate_selection()
        return super().form_valid(form)
