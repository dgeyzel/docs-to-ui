import logging

from d2u.generations.models import ErrorCode
from plain.jobs import Job, register_job
from plain.jobs.models import JobResult

from app.generate.pipeline import (
    claim_generation,
    mark_failed,
    run_claimed_generation,
)

logger = logging.getLogger(__name__)


@register_job
class GenerateDocJob(Job):
    """Turns one pending generation into a doc page. Safe to run twice."""

    def __init__(self, generation_id: int) -> None:
        self.generation_id = generation_id

    def default_queue(self) -> str:
        return "docs"

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
                code=ErrorCode.INTERNAL_ERROR,
                detail={"message": f"Unexpected error ({type(exc).__name__})."},
            )

    def on_aborted(self, result: JobResult) -> None:
        mark_failed(
            self.generation_id,
            code=ErrorCode.WORKER_LOST,
            detail={"message": "The worker stopped before the generation finished."},
        )
