from dataclasses import dataclass
from typing import Any

from d2u.generation.prompts import LANGUAGES, PROMPT_STRATEGIES
from d2u.registry.models import PromptPromotion, PromptVersion
from plain.http import JsonResponse, NotFoundError404, RedirectResponse, Response
from plain.templates.views import TemplateView
from plain.urls import reverse
from plain.views import View

from app.evals.models import EvalRun, RunStatus
from app.prompts.diff import examples_text, line_diff
from app.prompts.exceptions import PromptError
from app.prompts.forms import DraftForm, ImportForm, NewVersionForm, PromoteForm
from app.prompts.services import (
    create_draft,
    import_version,
    promote,
    rollback,
    rollback_target,
    save_draft,
)

HISTORY_LIMIT = 20
MESSAGES = {
    "created": "Draft created.",
    "imported": "Version imported as a draft.",
    "saved": "Draft saved.",
    "promoted": "Version promoted. The Docs app uses it from its next generation.",
    "rolled_back": "Rolled back. The Docs app uses the restored version from its next generation.",
}


@dataclass(frozen=True, slots=True)
class PromptGroup:
    """The versions for one language and strategy."""

    language: str
    strategy: str
    versions: list[PromptVersion]
    rollback_to: PromptVersion | None


def _get_prompt(url_kwargs: dict[str, Any]) -> PromptVersion:
    prompt = PromptVersion.query.get_or_none(int(url_kwargs["id"]))
    if prompt is None:
        raise NotFoundError404()
    return prompt


def _redirect(url: str, message: str) -> RedirectResponse:
    return RedirectResponse(f"{url}?message={message}", status_code=302)


def run_scores(run: EvalRun) -> dict:
    """The dev-set evidence copied onto a promoted version: the run's means."""
    summary = run.summary or {}
    return {
        "eval_run": run.id,
        "gold_set": run.gold_set.name,
        "split": run.split,
        "metric_version": run.metric_version.version,
        "total": summary.get("total", {}).get("total", {}).get("mean"),
        "metrics": {
            name: value["mean"] for name, value in summary.get("metrics", {}).items()
        },
    }


class PromptListView(TemplateView):
    """Prompt versions per language and strategy, with new-draft and import forms."""

    template_name = "prompts/list.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        versions = list(
            PromptVersion.query.order_by("language", "strategy", "-created_at")
        )
        context["groups"] = [
            PromptGroup(
                language=language,
                strategy=strategy,
                versions=[
                    v
                    for v in versions
                    if (v.language, v.strategy) == (language, strategy)
                ],
                rollback_to=rollback_target(language, strategy),
            )
            for language in LANGUAGES
            for strategy in PROMPT_STRATEGIES
        ]
        context["all_versions"] = versions
        context["message"] = MESSAGES.get(
            self.request.query_params.get("message", ""), ""
        )
        context["error"] = ""
        return context

    def post(self) -> Response:
        action = self.request.form_data.get("form", "")
        if action == "rollback":
            return self._rollback()
        if action == "import":
            form = ImportForm(request=self.request)
            if not form.is_valid():
                errors = [str(e) for errs in form.errors.values() for e in errs]
                return self.render(error=" ".join(errors), status_code=422)
            try:
                prompt = import_version(form.cleaned_data["file"])
            except PromptError as exc:
                return self.render(error=str(exc), status_code=422)
            return _redirect(reverse("prompts:detail", id=prompt.id), "imported")
        form = NewVersionForm(request=self.request)
        if not form.is_valid():
            return self.render(
                error="Choose a version to copy and a label.", status_code=422
            )
        try:
            prompt = create_draft(
                form.base_version(), version=form.cleaned_data["version"]
            )
        except PromptError as exc:
            return self.render(error=str(exc), status_code=422)
        return _redirect(reverse("prompts:detail", id=prompt.id), "created")

    def _rollback(self) -> Response:
        language = str(self.request.form_data.get("language", ""))
        strategy = str(self.request.form_data.get("strategy", ""))
        try:
            rollback(language, strategy)
        except PromptError as exc:
            return self.render(error=str(exc), status_code=422)
        return _redirect(reverse("prompts:list"), "rolled_back")


class PromptDetailView(TemplateView):
    """One version: edit it while it's a draft, promote it, see its promotions."""

    template_name = "prompts/detail.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        prompt = _get_prompt(self.url_kwargs)
        context["prompt"] = prompt
        context["instructions"] = prompt.instructions
        context["examples"] = examples_text(list(prompt.examples))
        context["errors"] = {}
        context["eval_runs"] = list(
            EvalRun.query.filter(
                prompt_version=prompt, status=RunStatus.SUCCEEDED.value
            )
            .join("gold_set")
            .order_by("-created_at")[:HISTORY_LIMIT]
        )
        context["promotions"] = list(
            PromptPromotion.query.filter(
                language=prompt.language, strategy=prompt.strategy
            ).order_by("-created_at", "-id")[:HISTORY_LIMIT]
        )
        context["others"] = list(
            PromptVersion.query.filter(
                language=prompt.language, strategy=prompt.strategy
            )
            .exclude(id=prompt.id)
            .order_by("-created_at")
        )
        context["message"] = MESSAGES.get(
            self.request.query_params.get("message", ""), ""
        )
        context["error"] = ""
        return context

    def post(self) -> Response:
        prompt = _get_prompt(self.url_kwargs)
        action = self.request.form_data.get("form", "")
        if action == "promote":
            return self._promote(prompt)
        form = DraftForm(request=self.request, prompt=prompt)
        if not form.is_valid():
            return self.render(
                instructions=str(form.data.get("instructions", "")),
                examples=str(form.data.get("examples", "")),
                errors={
                    name: " ".join(str(e) for e in errs)
                    for name, errs in form.errors.items()
                },
                status_code=422,
            )
        try:
            save_draft(prompt, form.cleaned_data["spec"])
        except PromptError as exc:
            return self.render(error=str(exc), status_code=422)
        return _redirect(reverse("prompts:detail", id=prompt.id), "saved")

    def _promote(self, prompt: PromptVersion) -> Response:
        form = PromoteForm(request=self.request)
        form.is_valid()
        raw_run = str(form.cleaned_data.get("eval_run") or "")
        scores = None
        if raw_run.isdigit():
            run = EvalRun.query.get_or_none(
                id=int(raw_run), prompt_version=prompt, status=RunStatus.SUCCEEDED.value
            )
            if run is None:
                return self.render(
                    error="Choose one of this version's eval runs.", status_code=422
                )
            scores = run_scores(run)
        try:
            promote(prompt, scores=scores, note=form.cleaned_data.get("note") or "")
        except PromptError as exc:
            return self.render(error=str(exc), status_code=422)
        return _redirect(reverse("prompts:detail", id=prompt.id), "promoted")


class PromptDiffView(TemplateView):
    """The instructions and examples of two versions, as a line diff."""

    template_name = "prompts/diff.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        params = self.request.query_params
        ids = [params.get("a", ""), params.get("b", "")]
        prompts = [
            PromptVersion.query.get_or_none(int(value)) if value.isdigit() else None
            for value in ids
        ]
        old, new = prompts
        if old is None or new is None:
            raise NotFoundError404()
        context["old"], context["new"] = old, new
        context["instructions_diff"] = line_diff(old.instructions, new.instructions)
        context["examples_diff"] = line_diff(
            examples_text(list(old.examples)), examples_text(list(new.examples))
        )
        return context


class PromptExportView(View):
    """A version as a JSON file that Import accepts."""

    def get(self) -> Response:
        prompt = _get_prompt(self.url_kwargs)
        filename = f"{prompt.language}-{prompt.strategy}-{prompt.version}.json"
        return JsonResponse(
            prompt.to_spec().model_dump(mode="json"),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
