import logging

from plain.jobs import Job, register_job
from plain.jobs.models import JobResult

from app.evals.exceptions import EvalRunError
from app.evals.runner import claim_run, fail_run, run_eval

logger = logging.getLogger(__name__)


@register_job
class EvalRunJob(Job):
    """Runs one eval run to completion. Safe to run twice."""

    def __init__(self, run_id: int) -> None:
        self.run_id = run_id

    def default_queue(self) -> str:
        return "tuning"

    def default_concurrency_key(self) -> str:
        return f"eval-run-{self.run_id}"

    def run(self) -> None:
        run = claim_run(self.run_id)
        if run is None:
            logger.info("Eval run %s is not pending; skipping", self.run_id)
            return
        try:
            run_eval(run)
        except EvalRunError as exc:
            fail_run(self.run_id, str(exc))
        except Exception as exc:
            # Job boundary: any unexpected failure becomes a failed run.
            logger.exception("Eval run %s crashed", self.run_id)
            fail_run(self.run_id, f"internal_error: {type(exc).__name__}")

    def on_aborted(self, result: JobResult) -> None:
        fail_run(
            self.run_id, "worker_lost: the worker stopped before the run finished."
        )
