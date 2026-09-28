import re
from typing import Any

from plain.http import NotFoundError404
from plain.templates.views import TemplateView

from app.traces.models import TraceSpan
from app.traces.presentation import (
    attribute_rows,
    build_llm_call,
    build_waterfall,
    trace_totals,
)
from app.traces.queries import recent_traces, trace_spans

_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID = re.compile(r"^[0-9a-f]{16}$")
STATUS_FILTERS = ("", "ok", "error")


def _checked(pattern: re.Pattern[str], value: str) -> str:
    if not pattern.match(value):
        raise NotFoundError404()
    return value


class TraceListView(TemplateView):
    template_name = "traces/list.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        raw_generation = self.request.query_params.get("generation", "").strip()
        generation_id = int(raw_generation) if raw_generation.isdigit() else None
        status = self.request.query_params.get("status", "")
        if status not in STATUS_FILTERS:
            status = ""
        context["traces"] = recent_traces(generation_id=generation_id, status=status)
        context["generation_filter"] = raw_generation if generation_id else ""
        context["status_filter"] = status
        return context


class TraceDetailView(TemplateView):
    template_name = "traces/detail.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        trace_id = _checked(_TRACE_ID, self.url_kwargs["trace_id"])
        spans = trace_spans(trace_id)
        # Spans are exported in batches, so a new trace can briefly have none.
        context["waiting"] = not spans
        context["trace_id"] = trace_id
        context["rows"] = build_waterfall(spans)
        context["totals"] = trace_totals(spans) if spans else None
        context["generation_id"] = next(
            (span.generation_id for span in spans if span.generation_id), None
        )
        return context


class SpanDetailView(TemplateView):
    """The span panel, loaded into the trace page over HTMX."""

    template_name = "traces/span_panel.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        trace_id = _checked(_TRACE_ID, self.url_kwargs["trace_id"])
        span_id = _checked(_SPAN_ID, self.url_kwargs["span_id"])
        span = TraceSpan.query.get_or_none(
            TraceSpan.trace_id.equals(trace_id), TraceSpan.span_id.equals(span_id)
        )
        if span is None:
            raise NotFoundError404()
        context["span"] = span
        context["attributes"] = attribute_rows(span.attributes)
        context["llm_call"] = build_llm_call(span.attributes) if span.is_llm else None
        return context
