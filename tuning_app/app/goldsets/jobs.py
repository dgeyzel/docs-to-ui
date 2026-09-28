import logging

from d2u.generation.exceptions import GenerationError
from d2u.registry.models import ModelConfig
from d2u.sources.exceptions import InputError
from plain.jobs import Job, register_job
from plain.jobs.models import JobResult

from app.goldsets.exceptions import GoldSetError
from app.goldsets.services import (
    claim_seed,
    describe_input_error,
    finish_seed,
    run_model_seed,
)

logger = logging.getLogger(__name__)


@register_job
class SeedGoldExampleJob(Job):
    """Fills one gold example's expected page from a model. Safe to run twice."""

    def __init__(self, example_id: int, model_id: int) -> None:
        self.example_id = example_id
        self.model_id = model_id

    def default_queue(self) -> str:
        return "tuning"

    def default_concurrency_key(self) -> str:
        return f"gold-seed-{self.example_id}"

    def run(self) -> None:
        example = claim_seed(self.example_id)
        if example is None:
            logger.info("Example %s has no pending seed; skipping", self.example_id)
            return
        model = ModelConfig.query.get_or_none(self.model_id)
        if model is None:
            finish_seed(self.example_id, error="The model was deleted.")
            return
        try:
            run_model_seed(example, model)
        except InputError as exc:
            finish_seed(self.example_id, error=describe_input_error(exc))
        except (GenerationError, GoldSetError) as exc:
            logger.info("Seeding example %s failed", self.example_id, exc_info=True)
            finish_seed(self.example_id, error=f"{type(exc).__name__}: {exc}")

    def on_aborted(self, result: JobResult) -> None:
        finish_seed(
            self.example_id, error="The worker stopped before the page was filled in."
        )
