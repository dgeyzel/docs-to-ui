"""The native backend: spans in Postgres, viewed in the app's trace viewer."""

from opentelemetry.sdk.trace import SpanProcessor
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from plain.urls import reverse

from app.telemetry.events import FeedbackEvent
from app.traces.exporter import PostgresSpanExporter


class NativeBackend:
    """Exports spans to the `trace_spans` table through a dedicated connection."""

    name: str = "native"

    def __init__(self, *, database_url: str, max_attribute_bytes: int) -> None:
        self._database_url = database_url
        self._max_attribute_bytes = max_attribute_bytes

    def span_processor(self) -> SpanProcessor:
        """A batch processor around the Postgres exporter."""
        exporter = PostgresSpanExporter(
            database_url=self._database_url,
            max_attribute_bytes=self._max_attribute_bytes,
        )
        return BatchSpanProcessor(exporter)

    def trace_url(self, trace_id: str) -> str | None:
        """The in-app trace viewer page."""
        return reverse("traces:detail", trace_id=trace_id)

    def record_feedback(self, trace_id: str, feedback: FeedbackEvent) -> None:
        """Nothing to do: feedback is always stored natively already."""

    def shutdown(self) -> None:
        """Nothing to release; the provider shuts the processor down."""
