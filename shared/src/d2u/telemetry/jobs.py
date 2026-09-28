from plain.jobs import Job, register_job

from d2u.telemetry.api import deliver_feedback
from d2u.telemetry.events import FeedbackEvent


@register_job
class MirrorFeedbackJob(Job):
    """Sends one piece of feedback to a trace backend that mirrors it later."""

    def __init__(
        self,
        *,
        backend: str,
        trace_id: str,
        generation_id: int,
        operation_id: str,
        score: int,
        comment: str,
    ) -> None:
        self.backend = backend
        self.trace_id = trace_id
        self.generation_id = generation_id
        self.operation_id = operation_id
        self.score = score
        self.comment = comment

    def default_retries(self) -> int:
        return 3

    def calculate_retry_delay(self, attempt: int) -> int:
        return 10 * 2 ** (attempt - 1)

    def run(self) -> None:
        deliver_feedback(
            backend_name=self.backend,
            trace_id=self.trace_id,
            event=FeedbackEvent(
                generation_id=self.generation_id,
                operation_id=self.operation_id or None,
                score=1 if self.score > 0 else -1,
                comment=self.comment,
            ),
        )
