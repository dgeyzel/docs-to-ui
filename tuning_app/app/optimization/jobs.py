import logging

from d2u.generation.exceptions import GenerationError
from plain.jobs import Job, register_job
from plain.jobs.models import JobResult

from app.evals.exceptions import EvalRunError
from app.optimization.exceptions import OptimizationError
from app.optimization.runner import claim_run, fail_run, run_optimization

logger = logging.getLogger(__name__)


@register_job
class OptimizationRunJob(Job):
    """Runs one DSPy optimization to a candidate and its eval. Safe to run twice."""

    def __init__(self, run_id: int) -> None:
        self.run_id = run_id

    def default_queue(self) -> str:
        return "tuning"

    def default_concurrency_key(self) -> str:
        return f"optimization-run-{self.run_id}"

    def run(self) -> None:
        run = claim_run(self.run_id)
        if run is None:
            logger.info("Optimization run %s is not pending; skipping", self.run_id)
            return
        try:
            run_optimization(run)
        except (OptimizationError, EvalRunError, GenerationError) as exc:
            logger.info("Optimization run %s failed", self.run_id, exc_info=True)
            fail_run(self.run_id, f"{type(exc).__name__}: {exc}")
        except Exception as exc:
            # Job boundary: any unexpected failure (including inside DSPy) fails the run.
            logger.exception("Optimization run %s crashed", self.run_id)
            fail_run(self.run_id, f"internal_error: {type(exc).__name__}")

    def on_aborted(self, result: JobResult) -> None:
        fail_run(
            self.run_id, "worker_lost: the worker stopped before the run finished."
        )
