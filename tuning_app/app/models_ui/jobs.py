import logging

from plain.jobs import Job, register_job
from plain.jobs.models import JobResult

from app.models_ui.connection import claim_test, finish_test, run_test

logger = logging.getLogger(__name__)


@register_job
class TestModelJob(Job):
    """Runs one Test connection for a registered model. Safe to run twice."""

    def __init__(self, test_id: int) -> None:
        self.test_id = test_id

    def default_queue(self) -> str:
        return "tuning"

    def default_concurrency_key(self) -> str:
        return f"model-test-{self.test_id}"

    def run(self) -> None:
        test = claim_test(self.test_id)
        if test is None:
            logger.info("Connection test %s is not pending; skipping", self.test_id)
            return
        run_test(test)

    def on_aborted(self, result: JobResult) -> None:
        finish_test(self.test_id, error="The worker stopped before the test finished.")
