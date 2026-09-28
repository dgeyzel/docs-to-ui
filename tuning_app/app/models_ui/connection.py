"""Running a registered model's Test connection (SPEC §7)."""

import logging
from datetime import UTC, datetime

import psycopg
from d2u.generation.connection import check_connection
from d2u.generations.fakes import fake_responses
from d2u.registry.models import ModelConfig

from app.models_ui.models import ModelTest, ModelTestStatus

logger = logging.getLogger(__name__)
MAX_ERROR_CHARS = 500


def start_test(model: ModelConfig) -> ModelTest:
    """Record a pending test and queue its job; a queueing failure fails the test."""
    from app.models_ui.jobs import TestModelJob

    test = ModelTest(llm_model=model, litellm_model=model.litellm_model)
    test.create()
    try:
        queued = TestModelJob(test.id).run_in_worker()
    except psycopg.Error:
        logger.exception("Could not queue connection test %s", test.id)
        queued = None
    if queued is None:
        finish_test(test.id, error="The test could not be queued. Try again.")
    return ModelTest.query.get(test.id)


def claim_test(test_id: int) -> ModelTest | None:
    """Move a pending test to running; None if it isn't pending."""
    claimed = ModelTest.query.filter(
        id=test_id, status=ModelTestStatus.PENDING.value
    ).update(status=ModelTestStatus.RUNNING.value)
    if claimed == 0:
        return None
    return ModelTest.query.get(test_id)


def finish_test(
    test_id: int, *, latency_ms: int | None = None, error: str = ""
) -> None:
    """Record a test's result, unless it already has one."""
    ModelTest.query.filter(
        id=test_id,
        status__in=[ModelTestStatus.PENDING.value, ModelTestStatus.RUNNING.value],
    ).update(
        status=ModelTestStatus.FAILED.value
        if error
        else ModelTestStatus.SUCCEEDED.value,
        latency_ms=latency_ms,
        error=error[:MAX_ERROR_CHARS],
        finished_at=datetime.now(UTC),
    )


def run_test(test: ModelTest) -> None:
    """Make the minimal structured-output call and record the outcome.

    Any provider or configuration error is the result to show, so every
    failure is recorded rather than raised.
    """
    try:
        usage = check_connection(test.llm_model.to_spec(), fake=fake_responses())
    except Exception as exc:
        # Test connection boundary: any provider error is the result to show.
        logger.info("Connection test %s failed", test.id, exc_info=True)
        finish_test(test.id, error=f"{type(exc).__name__}: {exc}")
        return
    finish_test(test.id, latency_ms=usage.latency_ms)


def latest_tests(models: list[ModelConfig]) -> dict[int, ModelTest]:
    """Each model's most recent test, by model ID (one indexed query per model)."""
    latest: dict[int, ModelTest] = {}
    for model in models:
        test = (
            ModelTest.query.filter(llm_model__id=model.id)
            .order_by("-created_at")
            .first()
        )
        if test is not None:
            latest[model.id] = test
    return latest
