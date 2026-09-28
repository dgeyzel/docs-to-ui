from typing import Any

from d2u.registry.lookups import trace_backends
from d2u.registry.models import RuntimeSettings
from d2u.telemetry.config import backend_options, invalidate_selection
from plain.http import Response
from plain.runtime import settings
from plain.templates.views import FormView
from plain.urls import reverse

from app.settings_ui.forms import TraceBackendsForm


class SettingsView(FormView[TraceBackendsForm]):
    """Runtime settings shared by both apps; the only place they change."""

    template_name = "settings_ui/index.html"
    form_class = TraceBackendsForm

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["initial"] = {"trace_backends": trace_backends()}
        return kwargs

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["backend_options"] = backend_options()
        context["ttl_s"] = settings.TELEMETRY_SETTINGS_TTL_S
        context["saved"] = self.request.query_params.get("saved") == "1"
        return context

    def get_success_url(self, form: TraceBackendsForm) -> str:
        return reverse("settings:index") + "?saved=1"

    def form_valid(self, form: TraceBackendsForm) -> Response:
        runtime = RuntimeSettings.load()
        runtime.trace_backends = form.cleaned_data["trace_backends"]
        runtime.update()
        # Other processes pick the change up within the TTL; this one now.
        invalidate_selection()
        return super().form_valid(form)
