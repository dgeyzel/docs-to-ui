"""Running an eval: the production path on every approved example (SPEC §9.3, D13).

Each example is generated with `d2u.generation` (the same code as the Docs
app), judged, and scored. Examples run in parallel worker threads that do no
database work; the job's own thread stores each result as it arrives.
"""

import contextvars
import logging
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime

import psycopg
from d2u.generation.client import FakeResponses, ModelSpec, Usage
from d2u.generation.exceptions import (
    GenerationError,
    GenerationFailedError,
    GenerationTimeoutError,
    LLMConfigurationError,
    OutputValidationError,
    ProviderError,
)
from d2u.generation.judging import judge_page
from d2u.generation.prompts import PromptSpec
from d2u.generation.runner import generate_for_bundle
from d2u.generation.strategies import GenerationConfig
from d2u.generations.fakes import fake_responses
from d2u.registry.models import ModelConfig, PromptVersion
from d2u.schemas.docpage import ApiSurface, DocPage
from d2u.schemas.gold import GoldInput
from d2u.schemas.judging import JudgeVerdict
from d2u.sources.adapters.base import LanguageAdapter
from d2u.sources.exceptions import InputError
from d2u.sources.registry import select_files
from d2u.telemetry.api import current_trace_context, eval_run_span
from opentelemetry import trace
from plain.runtime import settings

from app.evals.exceptions import EvalRunError
from app.evals.metrics.scoring import (
    ExampleScore,
    Weights,
    invalid_score,
    score_example,
)
from app.evals.metrics.stats import summarize
from app.evals.models import EvalResult, EvalRun, MetricVersion, ResultStatus, RunStatus
from app.goldsets.models import ExampleStatus, GoldExample, GoldSet
from app.goldsets.services import (
    adapter_for,
    bundle_of,
    content_hash,
    describe_input_error,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
MAX_ERROR_CHARS = 1000


@dataclass(frozen=True, slots=True)
class ExampleTask:
    """What a worker thread needs to evaluate one example."""

    example_id: int
    label: str
    gold_input: GoldInput
    expected: DocPage


@dataclass(frozen=True, slots=True)
class RunSettings:
    """Everything shared by a run's examples."""

    strategy: str
    adapter: LanguageAdapter
    model: ModelSpec | None
    prompt: PromptSpec | None
    judge: ModelSpec | None
    weights: Weights
    fake: FakeResponses | None
    max_concurrency: int
    timeout_s: int


@dataclass(slots=True)
class ExampleOutcome:
    """One example's output, scores and costs, ready to store."""

    task: ExampleTask
    score: ExampleScore
    output: DocPage | None = None
    verdict: JudgeVerdict | None = None
    error: str = ""
    usage: Usage = field(default_factory=Usage)
    judge_usage: Usage = field(default_factory=Usage)


def current_metric_version() -> MetricVersion:
    """The newest metric version (a seed migration creates version 1)."""
    version = MetricVersion.query.order_by("-version").first()
    if version is None:
        raise EvalRunError("No metric version exists. Run the schema sync.")
    return version


def approved_examples(gold_set: GoldSet, split: str) -> list[GoldExample]:
    """The approved examples of a split, in a stable order."""
    return list(
        GoldExample.query.filter(
            gold_set=gold_set, split=split, status=ExampleStatus.APPROVED.value
        ).order_by("id")
    )


def create_run(
    *,
    gold_set: GoldSet,
    split: str,
    strategy: str,
    model: ModelConfig | None,
    prompt: PromptVersion | None,
    judge: ModelConfig,
    concurrency: int,
) -> EvalRun:
    """Record a pending run and queue its job.

    Raises:
        EvalRunError: The split has no approved examples, or a strategy that
            needs a model and prompt has none.
    """
    from app.evals.jobs import EvalRunJob

    if not approved_examples(gold_set, split):
        raise EvalRunError(f"{gold_set.name} has no approved {split} examples.")
    if strategy != "parser" and (model is None or prompt is None):
        raise EvalRunError(
            f"The {strategy} strategy needs a model and a prompt version."
        )
    run = EvalRun(
        gold_set=gold_set,
        split=split,
        strategy=strategy,
        llm_model=model if strategy != "parser" else None,
        prompt_version=prompt if strategy != "parser" else None,
        judge_model=judge,
        metric_version=current_metric_version(),
        model_name=model.name if model and strategy != "parser" else "",
        prompt_label=str(prompt) if prompt and strategy != "parser" else "",
        judge_name=judge.name,
        concurrency=concurrency,
    )
    run.create()
    try:
        queued = EvalRunJob(run.id).run_in_worker()
    except psycopg.Error:
        logger.exception("Could not queue eval run %s", run.id)
        queued = None
    if queued is None:
        fail_run(run.id, "The run could not be queued. Try again.")
    return run


def claim_run(run_id: int) -> EvalRun | None:
    """Move a pending run to running; None if it isn't pending."""
    claimed = EvalRun.query.filter(id=run_id, status=RunStatus.PENDING.value).update(
        status=RunStatus.RUNNING.value, started_at=datetime.now(UTC)
    )
    if claimed == 0:
        return None
    return EvalRun.query.get(run_id)


def fail_run(run_id: int, error: str) -> None:
    """Record that an unfinished run failed."""
    EvalRun.query.filter(
        id=run_id, status__in=[RunStatus.PENDING.value, RunStatus.RUNNING.value]
    ).update(
        status=RunStatus.FAILED.value,
        error=error[:MAX_ERROR_CHARS],
        finished_at=datetime.now(UTC),
    )


def parser_surface(
    bundle_input: GoldInput, adapter: LanguageAdapter
) -> ApiSurface | None:
    """The parser's surface for an input, or None when it doesn't parse."""
    bundle, _ = select_files(bundle_of(bundle_input), adapter)
    try:
        return adapter.extract(bundle)
    except InputError:
        return None


def _error_text(exc: Exception) -> str:
    if isinstance(exc, InputError):
        return f"input_error: {describe_input_error(exc)}"
    codes: list[tuple[type[Exception], str]] = [
        (GenerationTimeoutError, "timeout"),
        (OutputValidationError, "validation_error"),
        (ProviderError, "provider_error"),
        (LLMConfigurationError, "provider_error"),
    ]
    if isinstance(exc, GenerationFailedError):
        code = "provider_error" if exc.provider else "validation_error"
    else:
        code = next(
            (code for kind, code in codes if isinstance(exc, kind)), "internal_error"
        )
    return f"{code}: {exc}"


def evaluate_example(task: ExampleTask, config: RunSettings) -> ExampleOutcome:
    """Generate, judge and score one example. Does no database work.

    A failed generation scores zero; a failed judge call leaves the judged
    metrics at zero and records the error.
    """
    with tracer.start_as_current_span(
        "eval.example", attributes={"docs.eval_example_id": task.example_id}
    ):
        try:
            result = generate_for_bundle(
                strategy=config.strategy,
                bundle=bundle_of(task.gold_input),
                adapter=config.adapter,
                model=config.model,
                prompt=config.prompt,
                config=GenerationConfig(
                    max_concurrency=config.max_concurrency,
                    deadline=time.monotonic() + config.timeout_s,
                    fake=config.fake,
                ),
            )
        except (InputError, GenerationError) as exc:
            error = _error_text(exc)
            return ExampleOutcome(task=task, score=invalid_score(error), error=error)

        verdict: JudgeVerdict | None = None
        judge_usage = Usage()
        judge_error = ""
        if config.judge is not None:
            try:
                judged = judge_page(
                    model=config.judge,
                    source_files=task.gold_input.files,
                    page=result.page,
                    fake=config.fake,
                )
                verdict, judge_usage = judged.value, judged.usage
            except GenerationError as exc:
                logger.info("Judging example %s failed", task.example_id, exc_info=True)
                judge_error = f"judge: {_error_text(exc)}"

        score = score_example(
            output=result.page,
            gold=task.expected,
            parser=parser_surface(task.gold_input, config.adapter),
            verdict=verdict,
            weights=config.weights,
        )
        return ExampleOutcome(
            task=task,
            score=score,
            output=result.page,
            verdict=verdict,
            error=judge_error,
            usage=result.usage,
            judge_usage=judge_usage,
        )


def _safe_evaluate(task: ExampleTask, config: RunSettings) -> ExampleOutcome:
    try:
        return evaluate_example(task, config)
    except Exception as exc:
        # Per-example boundary: one failing example scores zero, the run goes on.
        logger.exception("Eval example %s crashed", task.example_id)
        error = f"internal_error: {type(exc).__name__}"
        return ExampleOutcome(task=task, score=invalid_score(error), error=error)


def store_outcome(run: EvalRun, outcome: ExampleOutcome) -> None:
    """Save one example's result and count it done. Safe to call twice."""
    example = GoldExample.query.get_or_none(outcome.task.example_id)
    if EvalResult.query.filter(run=run, example__id=outcome.task.example_id).exists():
        return
    EvalResult(
        run=run,
        example=example,
        label=outcome.task.label,
        status=(
            ResultStatus.SUCCEEDED if outcome.score.valid else ResultStatus.FAILED
        ).value,
        error=outcome.error[:MAX_ERROR_CHARS],
        expected=outcome.task.expected.model_dump(mode="json"),
        output=outcome.output.model_dump(mode="json") if outcome.output else {},
        scores=outcome.score.as_dict(),
        details=outcome.score.details,
        verdict=outcome.verdict.model_dump(mode="json") if outcome.verdict else {},
        total=outcome.score.total,
        input_tokens=outcome.usage.input_tokens + outcome.judge_usage.input_tokens,
        output_tokens=outcome.usage.output_tokens + outcome.judge_usage.output_tokens,
        cost_usd=outcome.usage.cost_usd,
        judge_cost_usd=outcome.judge_usage.cost_usd,
        latency_ms=outcome.usage.latency_ms,
    ).create()
    EvalRun.query.filter(id=run.id).update(examples_done=run.examples_done + 1)
    run.examples_done += 1


def _run_settings(run: EvalRun) -> RunSettings:
    if run.judge_model is None:
        raise EvalRunError("The judge model was deleted.")
    if run.strategy != "parser" and (
        run.llm_model is None or run.prompt_version is None
    ):
        raise EvalRunError("The model or prompt version was deleted.")
    return RunSettings(
        strategy=run.strategy,
        adapter=adapter_for(run.gold_set.language),
        model=run.llm_model.to_spec() if run.llm_model else None,
        prompt=run.prompt_version.to_spec() if run.prompt_version else None,
        judge=run.judge_model.to_spec(),
        weights=run.metric_version.to_weights(),
        fake=fake_responses(),
        max_concurrency=settings.GENERATIONS_MAX_CONCURRENCY,
        timeout_s=settings.GENERATIONS_TIMEOUT_S,
    )


def _in_context(
    function: Callable[[ExampleTask, RunSettings], ExampleOutcome],
    task: ExampleTask,
    config: RunSettings,
) -> Callable[[], ExampleOutcome]:
    context = contextvars.copy_context()
    return lambda: context.run(function, task, config)


def run_eval(run: EvalRun) -> None:
    """Evaluate every approved example of the run's split and record the summary.

    Raises:
        EvalRunError: The run's model, prompt or judge no longer exists.
    """
    examples = approved_examples(run.gold_set, run.split)
    run.gold_set_hash = content_hash(run.gold_set)
    run.examples_total = len(examples)
    run.update(fields=["gold_set_hash", "examples_total"])
    config = _run_settings(run)
    tasks = [
        ExampleTask(
            example_id=example.id,
            label=example.label,
            gold_input=example.gold_input(),
            expected=example.expected_page(),
        )
        for example in examples
    ]
    limit = max(1, min(run.concurrency, settings.TUNING_MAX_EVAL_CONCURRENCY))
    with eval_run_span(eval_run_id=run.id, name="eval.run"):
        trace_context = current_trace_context()
        if trace_context is not None:
            EvalRun.query.filter(id=run.id).update(trace_id=trace_context.trace_id)
        with ThreadPoolExecutor(max_workers=limit, thread_name_prefix="eval") as pool:
            pending: set[Future[ExampleOutcome]] = {
                pool.submit(_in_context(_safe_evaluate, task, config)) for task in tasks
            }
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    store_outcome(run, future.result())
    finish_run(run)


def finish_run(run: EvalRun) -> None:
    """Summarize the stored results and mark the run succeeded."""
    results = list(EvalResult.query.filter(run=run).order_by("id"))
    EvalRun.query.filter(id=run.id, status=RunStatus.RUNNING.value).update(
        status=RunStatus.SUCCEEDED.value,
        summary=summarize([result.scores for result in results]),
        input_tokens=sum(result.input_tokens for result in results),
        output_tokens=sum(result.output_tokens for result in results),
        cost_usd=sum(result.cost_usd for result in results),
        judge_cost_usd=sum(result.judge_cost_usd for result in results),
        latency_ms=sum(result.latency_ms for result in results),
        finished_at=datetime.now(UTC),
    )
    logger.info("Eval run %s finished with %s results", run.id, len(results))
