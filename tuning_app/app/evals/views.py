from dataclasses import dataclass
from typing import Any

from d2u.registry.models import RuntimeSettings
from d2u.schemas.docpage import DocPage
from plain.forms import ValidationError
from plain.http import NotFoundError404, RedirectResponse, Response
from plain.postgres import transaction
from plain.runtime import settings
from plain.templates import Template
from plain.templates.views import FormView, TemplateView
from plain.urls import reverse
from plain.views import View

from app.evals.exceptions import EvalRunError
from app.evals.forms import EvalRunForm, MetricWeightsForm
from app.evals.metrics.compare import (
    RunScores,
    compare_examples,
    compare_metrics,
    comparison_warnings,
)
from app.evals.metrics.components import COMPONENT_WEIGHTS
from app.evals.metrics.diff import page_diff
from app.evals.metrics.scoring import METRIC_WEIGHTS
from app.evals.models import EvalResult, EvalRun, MetricVersion, RunStatus
from app.evals.runner import create_run, current_metric_version

RUNS_LIMIT = 100
METRIC_LABELS = {
    "faithfulness": "Faithfulness",
    "component_accuracy": "Component accuracy",
    "coverage": "Coverage",
    "example_validity": "Example validity",
    "prose_quality": "Prose quality",
}
COMPONENT_LABELS = {
    "precision": "Operation precision",
    "recall": "Operation recall",
    "operations": "Operation F1",
    "param_names": "Parameter names",
    "param_locations": "Parameter locations",
    "param_types": "Parameter types",
    "param_required": "Required flags",
    "param_defaults": "Defaults",
    "returns": "Returns",
    "signatures": "Signatures",
    "groups": "Groups",
}


@dataclass(frozen=True, slots=True)
class SummaryRow:
    """One line of a run's summary: a mean and its 95% interval."""

    name: str
    label: str
    mean: float
    low: float
    high: float
    weight: float | None


def summary_rows(
    estimates: dict[str, dict[str, float]],
    labels: dict[str, str],
    weights: dict[str, float] | None,
) -> list[SummaryRow]:
    """Summary rows in label order, for the metrics or components that exist."""
    return [
        SummaryRow(
            name=name,
            label=label,
            mean=estimates[name]["mean"],
            low=estimates[name]["low"],
            high=estimates[name]["high"],
            weight=weights.get(name) if weights is not None else None,
        )
        for name, label in labels.items()
        if name in estimates
    ]


def _get_run(url_kwargs: dict[str, Any]) -> EvalRun:
    run = EvalRun.query.get_or_none(int(url_kwargs["id"]))
    if run is None:
        raise NotFoundError404()
    return run


class EvalListView(TemplateView):
    """Every run, newest first, with checkboxes to compare runs."""

    template_name = "evals/list.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["runs"] = list(
            EvalRun.query.join("gold_set").order_by("-created_at")[:RUNS_LIMIT]
        )
        return context


class EvalCreateView(FormView[EvalRunForm]):
    template_name = "evals/new.html"
    form_class = EvalRunForm

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        runtime = RuntimeSettings.load()
        kwargs["initial"] = {
            "split": "dev",
            "strategy": "llm",
            "model": str(runtime.active_model.id) if runtime.active_model else "",
            "judge": (
                str(runtime.default_judge_model.id)
                if runtime.default_judge_model
                else ""
            ),
            "concurrency": min(4, settings.TUNING_MAX_EVAL_CONCURRENCY),
        }
        return kwargs

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["max_concurrency"] = settings.TUNING_MAX_EVAL_CONCURRENCY
        context["metric_version"] = current_metric_version()
        form: EvalRunForm = context["form"]
        context["same_judge"] = bool(
            form["model"].value()
            and form["model"].value() == form["judge"].value()
            and form["strategy"].value() != "parser"
        )
        return context

    def form_valid(self, form: EvalRunForm) -> Response:
        data = form.cleaned_data
        try:
            run = create_run(
                gold_set=data["gold_set_obj"],
                split=data["split"],
                strategy=data["strategy"],
                model=data["model_obj"],
                prompt=data["prompt_obj"],
                judge=form.chosen_judge(),
                concurrency=data["concurrency"],
            )
        except EvalRunError as exc:
            form.add_error(None, ValidationError(str(exc)))
            return self.render(form=form, status_code=422)
        return RedirectResponse(reverse("evals:detail", id=run.id), status_code=302)


class EvalDetailView(TemplateView):
    template_name = "evals/detail.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        run = _get_run(self.url_kwargs)
        summary = run.summary or {}
        version = run.metric_version
        context["run"] = run
        context["metric_rows"] = summary_rows(
            summary.get("metrics", {}), METRIC_LABELS, version.weights
        )
        context["component_rows"] = summary_rows(
            summary.get("components", {}), COMPONENT_LABELS, version.component_weights
        )
        context["total"] = summary.get("total", {}).get("total")
        context["results"] = list(
            EvalResult.query.filter(run=run).order_by("label", "id")
        )
        context["metric_names"] = list(METRIC_LABELS)
        context["metric_labels"] = METRIC_LABELS
        return context


class EvalStatusView(View):
    """The polled progress of a running eval; reloads the page when it finishes."""

    def get(self) -> Response:
        run = _get_run(self.url_kwargs)
        if run.finished:
            return Response(headers={"HX-Redirect": reverse("evals:detail", id=run.id)})
        html = Template("evals/status_fragment.html").render({"run": run})
        return Response(html)


class MetricsView(FormView[MetricWeightsForm]):
    """Metric definitions and weights; saving creates a new metric version."""

    template_name = "evals/metrics.html"
    form_class = MetricWeightsForm

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        current = current_metric_version()
        kwargs["initial"] = {
            **{f"metric_{name}": value for name, value in current.weights.items()},
            **{
                f"component_{name}": value
                for name, value in current.component_weights.items()
            },
        }
        return kwargs

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["current"] = current_metric_version()
        context["versions"] = list(MetricVersion.query.order_by("-version")[:20])
        context["metric_labels"] = METRIC_LABELS
        context["component_labels"] = {
            name: COMPONENT_LABELS[name] for name in COMPONENT_WEIGHTS
        }
        context["default_metrics"] = METRIC_WEIGHTS
        context["default_components"] = COMPONENT_WEIGHTS
        context["saved"] = self.request.query_params.get("saved") == "1"
        return context

    def form_valid(self, form: MetricWeightsForm) -> Response:
        with transaction.atomic():
            version = current_metric_version().version + 1
            MetricVersion(
                version=version,
                weights=form.cleaned_data["metrics"],
                component_weights=form.cleaned_data["components"],
                notes=form.cleaned_data["notes"] or "",
            ).create()
        return RedirectResponse(reverse("metrics:index") + "?saved=1", status_code=302)


def _get_result(url_kwargs: dict[str, Any]) -> EvalResult:
    result = EvalResult.query.get_or_none(
        id=int(url_kwargs["result_id"]), run__id=int(url_kwargs["id"])
    )
    if result is None:
        raise NotFoundError404()
    return result


def claims_by_operation(verdict: dict) -> list[tuple[str, list[dict]]]:
    """The judge's claims grouped by operation ("" for the title and overview)."""
    groups: dict[str, list[dict]] = {}
    for claim in verdict.get("claims", []):
        groups.setdefault(claim.get("operation_id", ""), []).append(claim)
    return list(groups.items())


class ResultDetailView(TemplateView):
    """One example of a run: expected and generated side by side, and the judge."""

    template_name = "evals/result.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        result = _get_result(self.url_kwargs)
        run = result.run
        expected = DocPage.model_validate(result.expected) if result.expected else None
        output = DocPage.model_validate(result.output) if result.output else None
        context["run"] = run
        context["result"] = result
        context["diff"] = page_diff(output, expected) if output and expected else None
        context["claims"] = claims_by_operation(result.verdict)
        context["unsupported"] = sum(
            1
            for claim in result.verdict.get("claims", [])
            if not claim.get("supported")
        )
        context["metric_labels"] = METRIC_LABELS
        context["component_labels"] = COMPONENT_LABELS
        context["example"] = result.example
        return context


def _run_scores(run: EvalRun) -> RunScores:
    totals: dict[int, float] = {}
    labels: dict[int, str] = {}
    for result in EvalResult.query.filter(run=run).order_by("id"):
        if result.example is None:
            continue
        totals[result.example.id] = result.total
        labels[result.example.id] = result.label
    label = f"#{run.id} {run.strategy}" + (
        f" · {run.model_name}" if run.model_name else ""
    )
    return RunScores(
        run_id=run.id, label=label, summary=run.summary, totals=totals, labels=labels
    )


class CompareView(TemplateView):
    """Two or more finished runs on one gold set, as deltas from the oldest."""

    template_name = "evals/compare.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        ids = [
            int(value)
            for value in self.request.query_params.getlist("runs")
            if value.isdigit()
        ]
        # The oldest run is the baseline the others are compared with.
        ids = sorted(set(ids))
        runs = {run.id: run for run in EvalRun.query.filter(id__in=ids)}
        ordered = [runs[run_id] for run_id in ids if run_id in runs]
        context["runs"] = ordered
        context["error"] = self._problem(ordered)
        if context["error"]:
            return context
        scores = [_run_scores(run) for run in ordered]
        context["totals"] = compare_metrics(scores, "total", ["total"])
        context["metrics"] = compare_metrics(scores, "metrics", list(METRIC_LABELS))
        context["components"] = compare_metrics(
            scores, "components", list(COMPONENT_LABELS)
        )
        context["examples"] = compare_examples(scores)
        context["labels"] = {**METRIC_LABELS, **COMPONENT_LABELS, "total": "Total"}
        context["warnings"] = comparison_warnings(
            gold_hashes=[run.gold_set_hash for run in ordered],
            splits=[run.split for run in ordered],
            metric_versions=[run.metric_version.version for run in ordered],
        )
        return context

    @staticmethod
    def _problem(runs: list[EvalRun]) -> str:
        if len(runs) < 2:
            return "Choose at least two runs to compare."
        if len({run.gold_set.id for run in runs}) > 1:
            return "Only runs on the same gold set can be compared."
        if any(run.status != RunStatus.SUCCEEDED for run in runs):
            return "Only finished, successful runs can be compared."
        return ""
