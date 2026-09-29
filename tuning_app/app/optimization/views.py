from dataclasses import dataclass
from typing import Any

from d2u.registry.models import PromptStatus, RuntimeSettings
from plain.forms import ValidationError
from plain.http import NotFoundError404, RedirectResponse, Response
from plain.templates import Template
from plain.templates.views import FormView, TemplateView
from plain.urls import reverse
from plain.views import View

from app.evals.models import RunStatus
from app.optimization.exceptions import OptimizationRunError
from app.optimization.forms import OptimizationForm, param_input_name
from app.optimization.models import OptimizationRun
from app.optimization.optimizers import (
    LABELS,
    PARAMS,
    Optimizer,
    OptimizerParam,
    mipro_available,
)
from app.optimization.runner import create_run
from app.prompts.exceptions import PromptError
from app.prompts.services import promote
from app.prompts.views import run_scores

RUNS_LIMIT = 100


@dataclass(frozen=True, slots=True)
class ParamField:
    """One optimizer parameter as the form shows it."""

    param: OptimizerParam
    input_name: str
    value: str


@dataclass(frozen=True, slots=True)
class OptimizerFields:
    """An optimizer's parameter inputs."""

    optimizer: Optimizer
    label: str
    fields: list[ParamField]
    available: bool


def optimizer_fields(data: Any) -> list[OptimizerFields]:
    """Every optimizer's parameters, with submitted values or defaults."""
    # Any: form data or an empty mapping.
    groups = []
    for optimizer, params in PARAMS.items():
        fields = []
        for param in params:
            name = param_input_name(optimizer, param.name)
            fields.append(ParamField(param, name, str(data.get(name, param.default))))
        groups.append(
            OptimizerFields(
                optimizer=optimizer,
                label=LABELS[optimizer],
                fields=fields,
                available=optimizer != Optimizer.MIPRO or mipro_available(),
            )
        )
    return groups


def _get_run(url_kwargs: dict[str, Any]) -> OptimizationRun:
    run = OptimizationRun.query.get_or_none(int(url_kwargs["id"]))
    if run is None:
        raise NotFoundError404()
    return run


class OptimizationListView(TemplateView):
    template_name = "optimization/list.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["runs"] = list(
            OptimizationRun.query.join("gold_set", "base_prompt").order_by(
                "-created_at"
            )[:RUNS_LIMIT]
        )
        context["labels"] = {
            optimizer.value: label for optimizer, label in LABELS.items()
        }
        return context


class OptimizationCreateView(FormView[OptimizationForm]):
    template_name = "optimization/new.html"
    form_class = OptimizationForm

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        runtime = RuntimeSettings.load()
        kwargs["initial"] = {
            "task_model": str(runtime.active_model.id) if runtime.active_model else "",
            "judge": (
                str(runtime.default_judge_model.id)
                if runtime.default_judge_model
                else ""
            ),
            "optimizer": Optimizer.BOOTSTRAP.value,
        }
        return kwargs

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        form: OptimizationForm = context["form"]
        context["optimizers"] = optimizer_fields(form.data if form.is_bound else {})
        return context

    def form_valid(self, form: OptimizationForm) -> Response:
        data = form.cleaned_data
        try:
            run = create_run(
                base_prompt=data["prompt_obj"],
                gold_set=data["gold_set_obj"],
                task_model=data["task_obj"],
                judge_model=data["judge_obj"],
                optimizer=Optimizer(data["optimizer"]),
                params=data["params"],
            )
        except OptimizationRunError as exc:
            form.add_error(None, ValidationError(str(exc)))
            return self.render(form=form, status_code=422)
        return RedirectResponse(
            reverse("optimization:detail", id=run.id), status_code=302
        )


class OptimizationDetailView(TemplateView):
    """Progress, trial log, the candidate's diff and its dev-set scores."""

    template_name = "optimization/detail.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        run = _get_run(self.url_kwargs)
        context["run"] = run
        context["optimizer_label"] = LABELS[Optimizer(run.optimizer)]
        context["eval_run"] = run.eval_run
        context["can_promote"] = bool(
            run.candidate
            and run.candidate.status != PromptStatus.ACTIVE
            and run.eval_run
            and run.eval_run.status == RunStatus.SUCCEEDED
        )
        context["error"] = ""
        return context

    def post(self) -> Response:
        """Promote the candidate, with its dev-set eval as the evidence."""
        run = _get_run(self.url_kwargs)
        eval_run = run.eval_run
        if (
            run.candidate is None
            or eval_run is None
            or eval_run.status != RunStatus.SUCCEEDED
        ):
            return self.render(
                error="The candidate can be promoted once its eval run has finished.",
                status_code=422,
            )
        try:
            promote(
                run.candidate,
                scores=run_scores(eval_run),
                note=f"From optimization run {run.id}",
            )
        except PromptError as exc:
            return self.render(error=str(exc), status_code=422)
        return RedirectResponse(
            reverse("prompts:detail", id=run.candidate.id) + "?message=promoted",
            status_code=302,
        )


class OptimizationStatusView(View):
    """Polled while a run searches; reloads the page when it stops."""

    def get(self) -> Response:
        run = _get_run(self.url_kwargs)
        if run.finished:
            return Response(
                headers={"HX-Redirect": reverse("optimization:detail", id=run.id)}
            )
        html = Template("optimization/status_fragment.html").render({"run": run})
        return Response(html)
