"""The interface every trace destination implements."""

from typing import Protocol, runtime_checkable

from opentelemetry.sdk.trace import SpanProcessor

from d2u.telemetry.events import FeedbackEvent


class TraceBackend(Protocol):
    """Where spans go, where humans view them, and where feedback is mirrored."""

    name: str

    def span_processor(self) -> SpanProcessor:
        """Processor added to the shared TracerProvider (always a BatchSpanProcessor)."""
        ...

    def trace_url(self, trace_id: str) -> str | None:
        """Where a human can view this trace."""
        ...

    def record_feedback(self, trace_id: str, feedback: FeedbackEvent) -> None:
        """Mirror feedback to the backend. Must never raise."""
        ...

    def shutdown(self) -> None:
        """Release anything the backend holds that the provider doesn't."""
        ...


@runtime_checkable
class FeedbackDeliverer(Protocol):
    """A backend that mirrors feedback later, from a background job."""

    name: str

    def deliver_feedback(self, trace_id: str, feedback: FeedbackEvent) -> None:
        """Send feedback now. May raise, so the job can retry."""
        ...
