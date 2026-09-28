from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from d2u.generation.client import api_key_is_set
from d2u.generation.params import ParamSpec, offered_params
from d2u.registry.models import ModelConfig, RuntimeSettings
from plain.http import NotFoundError404, RedirectResponse, Response
from plain.templates import Template
from plain.templates.views import FormView, TemplateView
from plain.urls import reverse
from plain.views import View

from app.models_ui.connection import latest_tests, start_test
from app.models_ui.forms import PARAM_PREFIX, ModelConfigForm
from app.models_ui.models import ModelTest

# HTMX stops polling when a response has this status.
HTMX_STOP_POLLING = 286
NEW_MODEL_DEFAULTS = {"max_input_tokens": 128000, "enabled_for_generation": True}


@dataclass(frozen=True, slots=True)
class ParamRow:
    """One offered parameter as the form shows it."""

    spec: ParamSpec
    input_name: str
    value: str
    error: str


def param_rows(
    litellm_model: str, values: Mapping[str, Any], errors: Mapping[str, str]
) -> list[ParamRow]:
    """The parameters offered for a model string, with current values and errors."""
    return [
        ParamRow(
            spec=spec,
            input_name=PARAM_PREFIX + spec.name,
            value="" if values.get(spec.name) is None else str(values[spec.name]),
            error=errors.get(spec.name, ""),
        )
        for spec in offered_params(litellm_model)
    ]


def _get_model(url_kwargs: dict[str, Any]) -> ModelConfig:
    model = ModelConfig.query.get_or_none(int(url_kwargs["id"]))
    if model is None:
        raise NotFoundError404()
    return model


def _submitted_params(form: ModelConfigForm) -> dict[str, str]:
    return {
        key.removeprefix(PARAM_PREFIX): str(form.data.get(key, ""))
        for key in form.data
        if key.startswith(PARAM_PREFIX)
    }


class ModelListView(TemplateView):
    template_name = "models_ui/list.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        models = list(ModelConfig.query.order_by("name"))
        runtime = RuntimeSettings.load()
        context["models"] = models
        context["tests"] = latest_tests(models)
        context["key_set"] = {
            model.id: api_key_is_set(model.to_spec()) for model in models
        }
        context["active_id"] = runtime.active_model.id if runtime.active_model else None
        context["judge_id"] = (
            runtime.default_judge_model.id if runtime.default_judge_model else None
        )
        return context


class ModelCreateView(FormView[ModelConfigForm]):
    template_name = "models_ui/form.html"
    form_class = ModelConfigForm

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["initial"] = dict(NEW_MODEL_DEFAULTS)
        return kwargs

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        form: ModelConfigForm = context["form"]
        if form.is_bound:
            # Validate so parameter errors are available to the template.
            form.is_valid()
        litellm_model = str(form["litellm_model"].value() or "")
        submitted = _submitted_params(form) if form.is_bound else {}
        context["param_rows"] = param_rows(litellm_model, submitted, form.param_errors)
        context["model"] = None
        context["saved"] = False
        return context

    def form_valid(self, form: ModelConfigForm) -> Response:
        model = ModelConfig(
            name=form.cleaned_data["name"],
            litellm_model=form.cleaned_data["litellm_model"],
        )
        form.apply_to(model)
        model.create()
        return RedirectResponse(reverse("models:detail", id=model.id), status_code=302)


class ModelDetailView(FormView[ModelConfigForm]):
    """Edit a model, test its connection and activate it for the Docs app."""

    template_name = "models_ui/form.html"
    form_class = ModelConfigForm

    def get_form_kwargs(self) -> dict[str, Any]:
        model = _get_model(self.url_kwargs)
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = model
        kwargs["initial"] = {
            "name": model.name,
            "litellm_model": model.litellm_model,
            "api_key_env": model.api_key_env,
            "api_base": model.api_base,
            "max_input_tokens": model.max_input_tokens,
            "enabled_for_generation": model.enabled_for_generation,
            "enabled_for_judging": model.enabled_for_judging,
            "notes": model.notes,
        }
        return kwargs

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        form: ModelConfigForm = context["form"]
        if form.is_bound:
            # Validate so parameter errors are available to the template.
            form.is_valid()
        model = form.instance
        assert model is not None
        runtime = RuntimeSettings.load()
        litellm_model = str(form["litellm_model"].value() or "")
        values = _submitted_params(form) if form.is_bound else dict(model.params)
        context["param_rows"] = param_rows(litellm_model, values, form.param_errors)
        context["model"] = model
        context["key_set"] = api_key_is_set(model.to_spec())
        context["is_active"] = bool(
            runtime.active_model and runtime.active_model.id == model.id
        )
        context["is_judge"] = bool(
            runtime.default_judge_model and runtime.default_judge_model.id == model.id
        )
        context["dropped_params"] = sorted(
            set(model.params) - {row.spec.name for row in context["param_rows"]}
        )
        context["test"] = latest_tests([model]).get(model.id)
        context["saved"] = self.request.query_params.get("saved") == "1"
        return context

    def form_valid(self, form: ModelConfigForm) -> Response:
        model = form.instance
        assert model is not None
        form.apply_to(model)
        model.update()
        return RedirectResponse(
            reverse("models:detail", id=model.id) + "?saved=1", status_code=302
        )


class ModelParamsView(View):
    """The parameter inputs for a model string, swapped in over HTMX."""

    def get(self) -> Response:
        params = self.request.query_params
        litellm_model = params.get("litellm_model", "")
        values = {
            key.removeprefix(PARAM_PREFIX): params.get(key, "")
            for key in params
            if key.startswith(PARAM_PREFIX)
        }
        html = Template("models_ui/params_fragment.html").render(
            {
                "param_rows": param_rows(litellm_model, values, {}),
                "litellm_model": litellm_model,
            }
        )
        return Response(html)


class ModelActivateView(View):
    """Make a model the Docs app's active generation model."""

    def post(self) -> Response:
        model = _get_model(self.url_kwargs)
        if not model.enabled_for_generation:
            return Response("This model isn't enabled for generation.", status_code=400)
        runtime = RuntimeSettings.load()
        runtime.active_model = model
        runtime.update()
        return RedirectResponse(reverse("models:detail", id=model.id), status_code=302)


class ModelTestView(View):
    """Start a Test connection for a model."""

    def post(self) -> Response:
        model = _get_model(self.url_kwargs)
        start_test(model)
        return RedirectResponse(
            reverse("models:detail", id=model.id) + "#connection-test", status_code=302
        )


class ModelTestStatusView(View):
    """The polled result of one Test connection."""

    def get(self) -> Response:
        model = _get_model(self.url_kwargs)
        test = ModelTest.query.get_or_none(
            id=int(self.url_kwargs["test_id"]), llm_model__id=model.id
        )
        if test is None:
            raise NotFoundError404()
        html = Template("models_ui/test_fragment.html").render(
            {"model": model, "test": test}
        )
        return Response(html, status_code=HTMX_STOP_POLLING if test.finished else 200)
