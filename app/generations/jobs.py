import logging

from plain.jobs import Job, register_job
from plain.jobs.models import JobResult

from app.generations.models import ErrorCode
from app.generations.pipeline import (
    claim_generation,
    mark_failed,
    run_claimed_generation,
)
from app.telemetry.api import deliver_feedback
from app.telemetry.events import FeedbackEvent

logger = logging.getLogger(__name__)


@register_job
class GenerateDocJob(Job):
    """Turns one pending generation into a doc page. Safe to run twice."""

    def __init__(self, generation_id: int) -> None:
        self.generation_id = generation_id

    def default_concurrency_key(self) -> str:
        return f"generation-{self.generation_id}"

    def default_retries(self) -> int:
        return 0

    def run(self) -> None:
        generation = claim_generation(self.generation_id)
        if generation is None:
            logger.info("Generation %s is not pending; skipping", self.generation_id)
            return
        try:
            run_claimed_generation(generation)
        except Exception as exc:
            # Job boundary: any unexpected failure becomes a failed generation.
            logger.exception("Generation %s crashed", self.generation_id)
            mark_failed(
                self.generation_id,
                code=ErrorCode.VALIDATION_ERROR,
                detail={"message": f"Unexpected error ({type(exc).__name__})."},
            )

    def on_aborted(self, result: JobResult) -> None:
        mark_failed(
            self.generation_id,
            code=ErrorCode.WORKER_LOST,
            detail={"message": "The worker stopped before the generation finished."},
        )


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
