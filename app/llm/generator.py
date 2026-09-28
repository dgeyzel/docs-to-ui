"""Running the LLM programs for a surface and assembling the `DocPage`.

Batches run concurrently. A failed batch doesn't abort the generation: its
operations are rendered from their source descriptions instead, unless more
than 10% of batches fail.
"""

import contextvars
import logging
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

import dspy
import pydantic
from dspy.utils.exceptions import AdapterParseError, LMError
from opentelemetry import trace

from app.llm.artifacts import Programs
from app.llm.batching import Batch, build_batches
from app.llm.docpage import fallback_overview
from app.llm.exceptions import GenerationFailedError, GenerationTimeoutError
from app.llm.merge import MergeReport, merge_enrichment, merge_overview, order_docs
from app.llm.schemas import (
    ApiSurface,
    BatchEnrichment,
    DocPage,
    Operation,
    OperationDocs,
    Overview,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

MAX_FAILED_BATCH_RATIO = 0.10
# One call plus one validation retry.
ATTEMPTS = 2


@dataclass(frozen=True, slots=True)
class GeneratorConfig:
    """Batching and concurrency limits, plus the soft deadline.

    `deadline` is a `time.monotonic()` value, checked between batches.
    """

    token_budget: int
    max_operations: int
    max_concurrency: int
    deadline: float | None = None


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """The finished page and how many batches failed along the way."""

    page: DocPage
    batches_total: int
    batches_failed: int


@dataclass(frozen=True, slots=True)
class _BatchOutcome:
    batch: Batch
    docs: list[OperationDocs] = field(default_factory=list)
    failed: bool = False
    provider_error: bool = False


def surface_outline(surface: ApiSurface, group_of: Callable[[Operation], str]) -> str:
    """The `WriteOverview` input: title, then one line per operation."""
    lines = [surface.title, ""]
    lines.extend(f"- {op.id} (group: {group_of(op)})" for op in surface.operations)
    return "\n".join(lines)


def generate_docpage(
    *,
    surface: ApiSurface,
    group_of: Callable[[Operation], str],
    display_name: str,
    lm: dspy.BaseLM,
    programs: Programs,
    config: GeneratorConfig,
    on_progress: Callable[[int, int], None],
    on_stage: Callable[[str], None],
) -> GenerationResult:
    """Enrich every operation, write the overview and merge the page.

    Args:
        surface: The extracted surface.
        group_of: The adapter's grouping function.
        display_name: Source language name, for the fallback overview.
        lm: The language model to call.
        programs: The loaded programs.
        config: Limits and deadline.
        on_progress: Called with (batches_done, batches_total).
        on_stage: Called with "overview" and then "merge" as they start.

    Raises:
        GenerationFailedError: More than 10% of batches failed.
        GenerationTimeoutError: The deadline passed between batches.
    """
    batches = build_batches(
        surface.operations,
        group_of=group_of,
        token_budget=config.token_budget,
        max_operations=config.max_operations,
    )
    on_progress(0, len(batches))

    def run_one(batch: Batch) -> _BatchOutcome:
        return _enrich_batch(batch, surface=surface, lm=lm, program=programs.enrich)

    outcomes = _run_batches(
        batches,
        run_one=run_one,
        max_concurrency=config.max_concurrency,
        deadline=config.deadline,
        on_progress=on_progress,
    )
    failed = [outcome for outcome in outcomes if outcome.failed]
    if len(failed) / len(batches) > MAX_FAILED_BATCH_RATIO:
        raise GenerationFailedError(
            f"{len(failed)} of {len(batches)} batches failed.",
            provider=any(outcome.provider_error for outcome in failed),
        )
    _check_deadline(config.deadline)

    docs = [entry for outcome in outcomes for entry in outcome.docs]
    on_stage("overview")
    overview = _write_overview(
        surface=surface,
        docs=docs,
        group_of=group_of,
        display_name=display_name,
        lm=lm,
        program=programs.overview,
    )

    on_stage("merge")
    with tracer.start_as_current_span("merge") as span:
        overview, report = merge_overview(surface, overview)
        _record_dropped(span, report)
        page = DocPage(
            surface=surface, overview=overview, operations=order_docs(surface, docs)
        )
        span.set_attribute("docs.operations.total", len(surface.operations))
        span.set_attribute("docs.operations.enriched", len(docs))
    return GenerationResult(
        page=page, batches_total=len(batches), batches_failed=len(failed)
    )


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise GenerationTimeoutError("The generation took longer than its time limit.")


def _run_batches(
    batches: list[Batch],
    *,
    run_one: Callable[[Batch], _BatchOutcome],
    max_concurrency: int,
    deadline: float | None,
    on_progress: Callable[[int, int], None],
) -> list[_BatchOutcome]:
    """Run batches with at most `max_concurrency` in flight.

    New batches start only while the deadline hasn't passed. Each task runs
    in a copy of the caller's context so trace context reaches its spans.
    """
    limit = max(1, max_concurrency)
    outcomes: list[_BatchOutcome] = []
    remaining = iter(batches)
    in_flight: set[Future[_BatchOutcome]] = set()
    pool = ThreadPoolExecutor(max_workers=limit, thread_name_prefix="enrich")
    try:
        while True:
            while len(in_flight) < limit:
                batch = next(remaining, None)
                if batch is None:
                    break
                _check_deadline(deadline)
                in_flight.add(pool.submit(_in_current_context(run_one, batch)))
            if not in_flight:
                break
            done, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in done:
                outcomes.append(future.result())
                on_progress(len(outcomes), len(batches))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return sorted(outcomes, key=lambda outcome: outcome.batch.index)


def _in_current_context(
    run_one: Callable[[Batch], _BatchOutcome], batch: Batch
) -> Callable[[], _BatchOutcome]:
    context = contextvars.copy_context()

    def task() -> _BatchOutcome:
        return context.run(run_one, batch)

    return task


def _enrich_batch(
    batch: Batch, *, surface: ApiSurface, lm: dspy.BaseLM, program: dspy.Module
) -> _BatchOutcome:
    attributes = {
        "docs.batch.index": batch.index,
        "docs.batch.size": len(batch.operations),
    }
    with tracer.start_as_current_span(
        f"enrich.batch[{batch.index}]", attributes=attributes
    ) as span:
        last_error: Exception | None = None
        for attempt in range(1, ATTEMPTS + 1):
            span.set_attribute("docs.batch.attempts", attempt)
            try:
                with dspy.context(lm=lm):
                    prediction = program(
                        operations=batch.operations,
                        api_title=surface.title,
                        language=surface.language,
                    )
                result = BatchEnrichment.model_validate(prediction.result)
            except LMError as exc:
                # Provider failures are already retried by the LM client.
                logger.warning(
                    "Batch %s failed at the provider", batch.index, exc_info=True
                )
                _record_failure(span, exc)
                return _BatchOutcome(batch=batch, failed=True, provider_error=True)
            except Exception as exc:
                # Per-batch LLM boundary: a bad batch must not abort the generation.
                last_error = exc
                logger.warning(
                    "Batch %s attempt %s returned invalid output",
                    batch.index,
                    attempt,
                    exc_info=True,
                )
                span.add_event(
                    "enrich.batch.invalid_output",
                    {"docs.attempt": attempt, "exception.type": type(exc).__name__},
                )
                continue

            docs, report = merge_enrichment(batch.operations, result.operations)
            _record_dropped(span, report)
            span.set_attribute("docs.batch.enriched", len(docs))
            return _BatchOutcome(batch=batch, docs=docs)

        if last_error is not None:
            _record_failure(span, last_error)
        return _BatchOutcome(batch=batch, failed=True)


def _write_overview(
    *,
    surface: ApiSurface,
    docs: list[OperationDocs],
    group_of: Callable[[Operation], str],
    display_name: str,
    lm: dspy.BaseLM,
    program: dspy.Module,
) -> Overview:
    """Call `WriteOverview`; fall back to a deterministic overview on failure."""
    with tracer.start_as_current_span("overview") as span:
        outline = surface_outline(surface, group_of)
        summaries = [f"{entry.operation_id}: {entry.summary}" for entry in docs]
        for attempt in range(1, ATTEMPTS + 1):
            try:
                with dspy.context(lm=lm):
                    prediction = program(
                        surface_outline=outline, batch_summaries=summaries
                    )
                return Overview.model_validate(prediction.result)
            except LMError as exc:
                logger.warning("Overview failed at the provider", exc_info=True)
                span.record_exception(exc)
                break
            except (AdapterParseError, pydantic.ValidationError, ValueError) as exc:
                logger.warning(
                    "Overview attempt %s returned invalid output",
                    attempt,
                    exc_info=True,
                )
                span.add_event(
                    "overview.invalid_output",
                    {"docs.attempt": attempt, "exception.type": type(exc).__name__},
                )
        span.add_event("overview.fallback")
        return fallback_overview(
            surface=surface, group_of=group_of, display_name=display_name
        )


def _record_dropped(span: trace.Span, report: MergeReport) -> None:
    if report.unknown_operation_ids:
        span.add_event(
            "merge.unknown_operation_ids",
            {"docs.ids": report.unknown_operation_ids},
        )
    if report.unknown_param_ids:
        span.add_event(
            "merge.unknown_param_ids", {"docs.ids": report.unknown_param_ids}
        )


def _record_failure(span: trace.Span, exc: Exception) -> None:
    span.record_exception(exc)
    span.set_status(trace.StatusCode.ERROR, type(exc).__name__)
    span.set_attribute("error.type", type(exc).__name__)
