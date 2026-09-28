"""The Langfuse backend: spans over OTLP, feedback as Langfuse scores.

Imported only when "langfuse" is in TELEMETRY_BACKENDS.
"""

import logging

from langfuse import Langfuse
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.telemetry.events import FeedbackEvent
from app.telemetry.otlp import langfuse_span_exporter

logger = logging.getLogger(__name__)

FEEDBACK_SCORE_NAME = "user_feedback"


class LangfuseBackend:
    """Sends spans to a Langfuse project and mirrors feedback as scores."""

    name: str = "langfuse"

    def __init__(
        self, *, base_url: str, public_key: str, secret_key: str, project_id: str
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._public_key = public_key
        self._secret_key = secret_key
        self._project_id = project_id

    def span_processor(self) -> SpanProcessor:
        """A batch processor around an authenticated OTLP exporter."""
        return BatchSpanProcessor(
            langfuse_span_exporter(
                base_url=self._base_url,
                public_key=self._public_key,
                secret_key=self._secret_key,
            )
        )

    def trace_url(self, trace_id: str) -> str | None:
        """The trace in the Langfuse UI."""
        return f"{self._base_url}/project/{self._project_id}/traces/{trace_id}"

    def record_feedback(self, trace_id: str, feedback: FeedbackEvent) -> None:
        """Queue a background job that sends the score. Never raises."""
        from app.generations.jobs import MirrorFeedbackJob

        try:
            MirrorFeedbackJob(
                backend=self.name,
                trace_id=trace_id,
                generation_id=feedback.generation_id,
                operation_id=feedback.operation_id or "",
                score=feedback.score,
                comment=feedback.comment,
            ).run_in_worker()
        except Exception:
            # Feedback boundary: mirroring must never affect saving feedback.
            logger.exception("Could not queue Langfuse feedback for trace %s", trace_id)

    def deliver_feedback(self, trace_id: str, feedback: FeedbackEvent) -> None:
        """Send feedback as a Langfuse score now (called by the background job).

        Raises:
            Exception: Whatever the Langfuse client raises, so the job can retry.
        """
        client = Langfuse(
            public_key=self._public_key,
            secret_key=self._secret_key,
            base_url=self._base_url,
            # A private, unused provider: the client must not attach its own
            # exporter to the app's provider, or every span would be sent twice.
            tracer_provider=TracerProvider(),
        )
        try:
            client.create_score(
                name=FEEDBACK_SCORE_NAME,
                value=float(feedback.score),
                data_type="NUMERIC",
                trace_id=trace_id,
                comment=feedback.comment or None,
                metadata={
                    "generation_id": feedback.generation_id,
                    "operation_id": feedback.operation_id,
                },
            )
            client.flush()
        finally:
            client.shutdown()

    def shutdown(self) -> None:
        """Nothing to release; the provider shuts the processor down."""
