"""The telemetry surface business code uses. It never exposes a backend."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from opentelemetry import baggage, context, trace
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    TraceFlags,
    format_span_id,
    format_trace_id,
)

from app.generations.models import Feedback, Generation
from app.telemetry.backends.base import FeedbackDeliverer
from app.telemetry.config import active_backends
from app.telemetry.events import FeedbackEvent

logger = logging.getLogger(__name__)

GENERATION_ID_KEY = "docs.generation_id"
PROGRAM_VERSION_KEY = "docs.program_version"

tracer = trace.get_tracer(__name__)


@dataclass(frozen=True, slots=True)
class TraceContext:
    """A span's position in a trace, as lowercase hex IDs."""

    trace_id: str
    span_id: str


def current_trace_context() -> TraceContext | None:
    """The active span's trace and span IDs, or None outside a recorded span."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return TraceContext(
        trace_id=format_trace_id(span_context.trace_id),
        span_id=format_span_id(span_context.span_id),
    )


def tag_current_span(*, generation_id: int) -> None:
    """Mark the active span (typically the request) with a generation ID."""
    trace.get_current_span().set_attribute(GENERATION_ID_KEY, generation_id)


def trace_url(trace_id: str) -> str | None:
    """Where to view a trace: the first active backend that has a URL."""
    if not trace_id:
        return None
    for backend in active_backends():
        url = backend.trace_url(trace_id)
        if url:
            return url
    return None


@contextmanager
def generation_span(
    *,
    name: str,
    generation_id: int,
    program_version: str,
    parent: TraceContext | None,
) -> Iterator[trace.Span]:
    """Run a block in a span that continues the originating request's trace.

    The generation ID and program version are set as baggage, so every span
    started inside the block carries them as attributes.

    Args:
        name: Span name.
        generation_id: The generation being worked on.
        program_version: The program artifact version in use.
        parent: The request's trace context; None starts a new trace.
    """
    ctx = context.get_current()
    if parent is not None:
        remote = SpanContext(
            trace_id=int(parent.trace_id, 16),
            span_id=int(parent.span_id, 16),
            is_remote=True,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
        )
        ctx = trace.set_span_in_context(NonRecordingSpan(remote), ctx)
    ctx = baggage.set_baggage(GENERATION_ID_KEY, str(generation_id), context=ctx)
    ctx = baggage.set_baggage(PROGRAM_VERSION_KEY, program_version, context=ctx)
    token = context.attach(ctx)
    try:
        with tracer.start_as_current_span(name) as span:
            yield span
    finally:
        context.detach(token)


@contextmanager
def stage_span(name: str) -> Iterator[trace.Span]:
    """A span for one generation stage (bundle, extract, ...)."""
    with tracer.start_as_current_span(name, attributes={"docs.stage": name}) as span:
        yield span


def record_feedback(generation: Generation, event: FeedbackEvent) -> Feedback:
    """Save feedback natively, then mirror it to every active backend.

    Backends never raise from `record_feedback`, so mirroring can't lose the
    saved row.
    """
    feedback = Feedback(
        generation=generation,
        operation_id=event.operation_id or "",
        score=event.score,
        comment=event.comment,
        trace_id=generation.trace_id,
    )
    feedback.create()
    for backend in active_backends():
        backend.record_feedback(generation.trace_id, event)
    return feedback


def deliver_feedback(*, backend_name: str, trace_id: str, event: FeedbackEvent) -> None:
    """Send queued feedback to one backend (used by `MirrorFeedbackJob`).

    Raises:
        Exception: Whatever the backend raises, so the job can retry.
    """
    for backend in active_backends():
        if backend.name == backend_name and isinstance(backend, FeedbackDeliverer):
            backend.deliver_feedback(trace_id, event)
            return
    logger.warning("No active backend %s can deliver feedback", backend_name)
