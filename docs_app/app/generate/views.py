from typing import Any

from d2u.generations.models import Feedback, Generation, GenerationStatus
from d2u.registry.lookups import active_model, trace_backends
from d2u.schemas.docpage import DocPage
from d2u.sources.bundle import FileManifest
from d2u.sources.registry import display_name
from d2u.telemetry.api import record_feedback, trace_url
from d2u.telemetry.config import selection_summary
from d2u.telemetry.events import FeedbackEvent
from d2u.traces.queries import generation_trace_totals
from plain.http import NotFoundError404, RedirectResponse, Response
from plain.runtime import settings
from plain.templates import Template
from plain.templates.views import FormView, TemplateView
from plain.urls import reverse
from plain.views import View

from app.generate.export import export_filename, render_export_html
from app.generate.forms import FeedbackForm, SourceForm, format_megabytes
from app.generate.pipeline import create_generation, enqueue_generation, regenerate
from app.generate.presentation import (
    build_error_view,
    build_page_view,
    build_status_view,
    usage_label,
    wall_time_label,
)

RECENT_GENERATIONS_LIMIT = 20
# HTMX stops polling when a response has this status.
HTMX_STOP_POLLING = 286


def _get_generation(url_kwargs: dict[str, Any]) -> Generation:
    generation = Generation.query.get_or_none(int(url_kwargs["id"]))
    if generation is None:
        raise NotFoundError404()
    return generation


def _succeeded_page(generation: Generation) -> DocPage:
    if generation.status != GenerationStatus.SUCCEEDED or generation.doc_json is None:
        raise NotFoundError404()
    return DocPage.model_validate(generation.doc_json)


def _detail_url(generation: Generation) -> str:
    return reverse("generations:detail", id=generation.id)


def latest_feedback(generation: Generation) -> dict[str, int]:
    """The most recent score per operation ID ("" for the whole page)."""
    scores: dict[str, int] = {}
    for feedback in Feedback.query.where(
        Feedback.generation.id.equals(generation.id)
    ).order_by("created_at"):
        scores[feedback.operation_id] = feedback.score
    return scores


class HomeView(FormView[SourceForm]):
    template_name = "generations/home.html"
    form_class = SourceForm

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["generations"] = list(
            Generation.query.order_by("-created_at")[:RECENT_GENERATIONS_LIMIT]
        )
        context["max_input_label"] = format_megabytes(
            settings.GENERATIONS_MAX_INPUT_BYTES
        )
        model = active_model()
        context["active_model_name"] = model.name if model else ""
        context["trace_backends_label"] = selection_summary(trace_backends())
        return context

    def form_valid(self, form: SourceForm) -> Response:
        generation = create_generation(form.submitted_input())
        enqueue_generation(generation)
        return RedirectResponse(_detail_url(generation), status_code=302)


class GenerationDetailView(TemplateView):
    template_name = "generations/detail.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        generation = _get_generation(self.url_kwargs)
        context["generation"] = generation
        context["status"] = build_status_view(generation)
        context["error"] = build_error_view(
            error_code=generation.error_code, error_detail=generation.error_detail
        )
        context["manifest"] = (
            FileManifest.model_validate(generation.input_manifest)
            if generation.input_manifest
            else None
        )
        context["trace_url"] = trace_url(generation.trace_id)
        context["trace_totals"] = generation_trace_totals(generation.trace_id)
        context["wall_time"] = wall_time_label(generation)
        context["usage"] = usage_label(generation)
        context["page"] = None
        context["feedback"] = latest_feedback(generation)
        if generation.status == GenerationStatus.SUCCEEDED and generation.doc_json:
            context["page"] = build_page_view(
                page=DocPage.model_validate(generation.doc_json),
                language_display=display_name(generation.language),
            )
        return context


class GenerationStatusView(View):
    """The polled status fragment for a pending or running generation."""

    def get(self) -> Response:
        generation = _get_generation(self.url_kwargs)
        if generation.status == GenerationStatus.SUCCEEDED:
            return Response(headers={"HX-Redirect": _detail_url(generation)})
        if generation.status == GenerationStatus.FAILED:
            html = Template("generations/error_fragment.html").render(
                {
                    "generation": generation,
                    "error": build_error_view(
                        error_code=generation.error_code,
                        error_detail=generation.error_detail,
                    ),
                }
            )
            return Response(html, status_code=HTMX_STOP_POLLING)
        html = Template("generations/status_fragment.html").render(
            {"generation": generation, "status": build_status_view(generation)}
        )
        return Response(html)


class RegenerateView(View):
    """Start a new generation from another generation's stored input."""

    def post(self) -> Response:
        original = _get_generation(self.url_kwargs)
        generation = regenerate(original)
        enqueue_generation(generation)
        return RedirectResponse(_detail_url(generation), status_code=302)


class FeedbackView(View):
    """Record feedback on a page or one operation, then return to it."""

    def post(self) -> Response:
        generation = _get_generation(self.url_kwargs)
        page = _succeeded_page(generation)
        form = FeedbackForm(request=self.request)
        if not form.is_valid():
            return Response("Invalid feedback.", status_code=400)
        operation_id = form.cleaned_data["operation_id"] or None
        known = {op.id for op in page.surface.operations}
        if operation_id is not None and operation_id not in known:
            raise NotFoundError404()
        record_feedback(
            generation,
            FeedbackEvent(
                generation_id=generation.id,
                operation_id=operation_id,
                score=form.cleaned_data["score"],
                comment=(form.cleaned_data["comment"] or "").strip(),
            ),
        )
        anchor = form.cleaned_data["anchor"]
        fragment = f"#feedback-{anchor}" if anchor else ""
        return RedirectResponse(_detail_url(generation) + fragment, status_code=302)


class ExportHtmlView(View):
    def get(self) -> Response:
        generation = _get_generation(self.url_kwargs)
        page = _succeeded_page(generation)
        html = render_export_html(
            page_view=build_page_view(
                page=page, language_display=display_name(generation.language)
            )
        )
        return Response(
            html,
            content_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{export_filename(generation, "html")}"'
                )
            },
        )


class ExportJsonView(View):
    def get(self) -> Response:
        generation = _get_generation(self.url_kwargs)
        page = _succeeded_page(generation)
        return Response(
            page.model_dump_json(indent=2),
            content_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{export_filename(generation, "json")}"'
                )
            },
        )
