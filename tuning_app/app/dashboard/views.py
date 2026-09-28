from typing import Any

from d2u.registry.models import PromptStatus, PromptVersion, RuntimeSettings
from plain.templates.views import TemplateView
from plain.views import RedirectView

from app.evals.models import EvalRun, RunStatus

RECENT_RUNS_LIMIT = 10


def latest_runs_by_language() -> list[EvalRun]:
    """The newest successful run for each gold-set language, by language."""
    latest: dict[str, EvalRun] = {}
    runs = EvalRun.query.filter(status=RunStatus.SUCCEEDED.value).order_by(
        "-finished_at"
    )
    for run in runs.join("gold_set"):
        latest.setdefault(run.gold_set.language, run)
    return [latest[language] for language in sorted(latest)]


class DashboardView(TemplateView):
    """The active choices, the latest scores per language and recent runs."""

    template_name = "dashboard/index.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        runtime = RuntimeSettings.load()
        context["active_model"] = runtime.active_model
        context["default_judge"] = runtime.default_judge_model
        context["active_prompts"] = list(
            PromptVersion.query.filter(status=PromptStatus.ACTIVE.value).order_by(
                "language", "strategy"
            )
        )
        context["latest_runs"] = latest_runs_by_language()
        context["recent_runs"] = list(
            EvalRun.query.join("gold_set").order_by("-created_at")[:RECENT_RUNS_LIMIT]
        )
        return context


class RootRedirectView(RedirectView):
    """Send / to the dashboard: every Tuning app page lives under /tuning/."""

    url_name = "dashboard"
