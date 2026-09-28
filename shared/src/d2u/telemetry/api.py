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

from d2u.generations.models import Feedback, Generation
from d2u.telemetry.backends.base import FeedbackDeliverer
from d2u.telemetry.config import available_backends, selected_backends
from d2u.telemetry.events import FeedbackEvent

logger = logging.getLogger(__name__)

GENERATION_ID_KEY = "docs.generation_id"
PROMPT_VERSION_KEY = "docs.prompt_version"
MODEL_KEY = "docs.model"

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
    """Where to view a trace: the first selected backend that has a URL."""
    if not trace_id:
        return None
    for backend in selected_backends():
        url = backend.trace_url(trace_id)
        if url:
            return url
    return None


@contextmanager
def generation_span(
    *,
    name: str,
    generation_id: int,
    prompt_version: str,
    model: str,
    parent: TraceContext | None,
) -> Iterator[trace.Span]:
    """Run a block in a span that continues the originating request's trace.

    The generation ID, prompt version and model are set as baggage, so every
    span started inside the block carries them as attributes.

    Args:
        name: Span name.
        generation_id: The generation being worked on.
        prompt_version: The prompt version in use, e.g. "openapi/llm/baseline".
        model: The model's registry name.
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
    ctx = baggage.set_baggage(PROMPT_VERSION_KEY, prompt_version, context=ctx)
    ctx = baggage.set_baggage(MODEL_KEY, model, context=ctx)
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
    """Save feedback natively, then mirror it to every selected backend.

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
    for backend in selected_backends():
        backend.record_feedback(generation.trace_id, event)
    return feedback


def deliver_feedback(*, backend_name: str, trace_id: str, event: FeedbackEvent) -> None:
    """Send queued feedback to one backend (used by `MirrorFeedbackJob`).

    The feedback was queued while the backend was selected, so it is
    delivered even if the backend has been deselected since.

    Raises:
        Exception: Whatever the backend raises, so the job can retry.
    """
    for backend in available_backends():
        if backend.name == backend_name and isinstance(backend, FeedbackDeliverer):
            backend.deliver_feedback(trace_id, event)
            return
    logger.warning("No available backend %s can deliver feedback", backend_name)


@contextmanager
def generation_baggage(*, prompt_version: str) -> Iterator[None]:
    """Add the prompt version to baggage for spans started inside the block.

    Used once the input's language, and so its prompt, is known.
    """
    token = context.attach(baggage.set_baggage(PROMPT_VERSION_KEY, prompt_version))
    try:
        yield
    finally:
        context.detach(token)
