"""The three ways to build a page (SPEC §6.3).

| Strategy | Structure from | Prose from |
| `llm`    | LLM            | LLM, in the same call |
| `hybrid` | parser         | LLM, one call per batch |
| `parser` | parser         | source descriptions only |

Plain-free: both apps call these functions, so evals run the production path.
"""

import contextvars
import logging
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from opentelemetry import trace

from d2u.generation.batching import Batch, build_batches
from d2u.generation.client import FakeResponses, ModelSpec, Usage, complete_structured
from d2u.generation.convert import (
    base_operation_id,
    generated_to_docpage,
    merge_parts,
)
from d2u.generation.docpage import build_unenriched_docpage, fallback_overview
from d2u.generation.exceptions import (
    GenerationFailedError,
    GenerationTimeoutError,
    OutputValidationError,
    ProviderError,
)
from d2u.generation.merge import MergeReport, merge_enrichment, order_docs
from d2u.generation.prompts import (
    PromptSpec,
    docs_messages,
    overview_messages,
    page_messages,
)
from d2u.generation.splitting import source_budget, split_files
from d2u.schemas.docpage import ApiSurface, DocPage, Operation, OperationDocs, Overview
from d2u.schemas.generated import GeneratedDocs, GeneratedOverview, GeneratedPage

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

MAX_FAILED_BATCH_RATIO = 0.10
HYBRID_BATCH_TOKEN_BUDGET = 60000
HYBRID_BATCH_MAX_OPERATIONS = 25

Progress = Callable[[int, int], None]
StageCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class GenerationConfig:
    """Concurrency, the soft deadline (a `time.monotonic()` value) and test fixtures."""

    max_concurrency: int = 4
    deadline: float | None = None
    fake: FakeResponses | None = None


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """The page, what it cost, and how many parts (or batches) ran and failed."""

    page: DocPage
    usage: Usage
    parts_total: int = 0
    parts_failed: int = 0


def _noop_progress(done: int, total: int) -> None:
    return None


def _noop_stage(stage: str) -> None:
    return None


def check_deadline(deadline: float | None) -> None:
    """Raise if the soft deadline has passed.

    Raises:
        GenerationTimeoutError: It has.
    """
    if deadline is not None and time.monotonic() > deadline:
        raise GenerationTimeoutError("The generation took longer than its time limit.")


def _in_current_context[T, R](
    task: Callable[[int, T], R], index: int, item: T
) -> Callable[[], R]:
    context = contextvars.copy_context()

    def run() -> R:
        return context.run(task, index, item)

    return run


def run_all[T, R](
    items: list[T],
    *,
    task: Callable[[int, T], R],
    max_concurrency: int,
    deadline: float | None,
    on_progress: Progress,
) -> list[R]:
    """Run `task` on every item with at most `max_concurrency` in flight.

    Results come back in item order. New items start only while the
    deadline hasn't passed. If a task raises, nothing new starts and the
    exception propagates. Each task runs in a copy of the caller's context
    so trace context reaches its spans.
    """
    limit = max(1, max_concurrency)
    results: dict[int, R] = {}
    remaining = iter(enumerate(items))
    in_flight: dict[Future[R], int] = {}
    pool = ThreadPoolExecutor(max_workers=limit, thread_name_prefix="generate")
    try:
        while True:
            while len(in_flight) < limit:
                entry = next(remaining, None)
                if entry is None:
                    break
                check_deadline(deadline)
                index, item = entry
                in_flight[pool.submit(_in_current_context(task, index, item))] = index
            if not in_flight:
                break
            done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in done:
                index = in_flight.pop(future)
                results[index] = future.result()
                on_progress(len(results), len(items))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return [results[index] for index in range(len(items))]


def _record_list(span: trace.Span, name: str, values: list[str]) -> None:
    if values:
        span.add_event(name, {"docs.ids": values})


def generate_llm(
    *,
    source_files: dict[str, str],
    language: str,
    model: ModelSpec,
    prompt: PromptSpec,
    config: GenerationConfig,
    entry: str | None = None,
    on_progress: Progress = _noop_progress,
    on_stage: StageCallback = _noop_stage,
) -> GenerationResult:
    """The `llm` strategy: the model reads the source and writes the whole page.

    `entry` names the file the API is defined in, when the language has one.

    An input too large for one call is split into parts; parts are merged in
    code and one more call writes the overview. Any failed part fails the
    generation.

    Raises:
        ProviderError, OutputValidationError, LLMConfigurationError: A call failed.
        GenerationTimeoutError: The deadline passed between calls.
    """
    line_counts = {path: text.count("\n") + 1 for path, text in source_files.items()}
    budget = source_budget(
        max_input_tokens=model.max_input_tokens, instructions=prompt.instructions
    )
    parts = split_files(source_files, budget=budget)
    on_stage("generate")
    on_progress(0, len(parts))

    def generate_part(index: int, files: dict[str, str]) -> tuple[GeneratedPage, Usage]:
        with tracer.start_as_current_span(
            f"generate.part[{index}]",
            attributes={"docs.part.index": index, "docs.part.files": len(files)},
        ):
            result = complete_structured(
                model=model,
                messages=page_messages(prompt, files, entry=entry),
                response_model=GeneratedPage,
                fake=config.fake,
            )
            return result.value, result.usage

    outcomes = run_all(
        parts,
        task=generate_part,
        max_concurrency=config.max_concurrency,
        deadline=config.deadline,
        on_progress=on_progress,
    )
    usage = sum((part_usage for _, part_usage in outcomes), Usage())
    pages = [page for page, _ in outcomes]

    duplicates: list[str] = []
    merged = pages[0]
    if len(pages) > 1:
        merged, duplicates = merge_parts(pages)
        check_deadline(config.deadline)
        on_stage("overview")
        with tracer.start_as_current_span("overview"):
            overview = complete_structured(
                model=model,
                messages=overview_messages(
                    title=merged.title,
                    summaries=[
                        f"{base_operation_id(op)}: {op.summary}"
                        for op in merged.operations
                    ],
                ),
                response_model=GeneratedOverview,
                fake=config.fake,
            )
        usage = usage + overview.usage
        merged = merged.model_copy(
            update={
                "title": overview.value.title,
                "overview_md": overview.value.overview_md,
            }
        )

    on_stage("merge")
    with tracer.start_as_current_span("merge") as span:
        page, report = generated_to_docpage(
            merged, language=language, line_counts=line_counts
        )
        _record_list(span, "merge.duplicate_operations", duplicates)
        _record_list(span, "merge.id_collisions", report.id_collisions)
        _record_list(span, "merge.dropped_locations", report.dropped_locations)
        span.set_attribute("docs.operations.total", len(page.surface.operations))
    return GenerationResult(page=page, usage=usage, parts_total=len(parts))


@dataclass(frozen=True, slots=True)
class _BatchOutcome:
    docs: list[OperationDocs] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    failed: bool = False
    provider_error: bool = False


def _record_dropped(span: trace.Span, report: MergeReport) -> None:
    _record_list(span, "merge.unknown_operation_ids", report.unknown_operation_ids)
    _record_list(span, "merge.unknown_param_ids", report.unknown_param_ids)


def generate_hybrid(
    *,
    surface: ApiSurface,
    group_of: Callable[[Operation], str],
    display_name: str,
    model: ModelSpec,
    prompt: PromptSpec,
    config: GenerationConfig,
    on_progress: Progress = _noop_progress,
    on_stage: StageCallback = _noop_stage,
) -> GenerationResult:
    """The `hybrid` strategy: parsed structure, LLM-written prose per batch.

    A failed batch doesn't abort the page: its operations show their source
    descriptions, unless more than 10% of batches fail. Navigation groups
    follow the parser's group hints.

    Raises:
        GenerationFailedError: More than 10% of batches failed.
        GenerationTimeoutError: The deadline passed between batches.
        LLMConfigurationError: The model is misconfigured.
    """
    batches = build_batches(
        surface.operations,
        group_of=group_of,
        token_budget=HYBRID_BATCH_TOKEN_BUDGET,
        max_operations=HYBRID_BATCH_MAX_OPERATIONS,
    )
    on_stage("enrich")
    on_progress(0, len(batches))

    def enrich(index: int, batch: Batch) -> _BatchOutcome:
        with tracer.start_as_current_span(
            f"enrich.batch[{index}]",
            attributes={
                "docs.batch.index": index,
                "docs.batch.size": len(batch.operations),
            },
        ) as span:
            try:
                result = complete_structured(
                    model=model,
                    messages=docs_messages(
                        prompt,
                        batch.operations,
                        api_title=surface.title,
                        language=surface.language,
                    ),
                    response_model=GeneratedDocs,
                    fake=config.fake,
                )
            except ProviderError as exc:
                logger.warning("Batch %s failed at the provider", index, exc_info=True)
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, type(exc).__name__)
                return _BatchOutcome(failed=True, provider_error=True)
            except OutputValidationError as exc:
                logger.warning("Batch %s returned invalid output", index, exc_info=True)
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, type(exc).__name__)
                return _BatchOutcome(failed=True)
            docs, report = merge_enrichment(batch.operations, result.value.operations)
            _record_dropped(span, report)
            return _BatchOutcome(docs=docs, usage=result.usage)

    outcomes = run_all(
        batches,
        task=enrich,
        max_concurrency=config.max_concurrency,
        deadline=config.deadline,
        on_progress=on_progress,
    )
    usage = sum((outcome.usage for outcome in outcomes), Usage())
    failed = [outcome for outcome in outcomes if outcome.failed]
    if batches and len(failed) / len(batches) > MAX_FAILED_BATCH_RATIO:
        raise GenerationFailedError(
            f"{len(failed)} of {len(batches)} batches failed.",
            provider=any(outcome.provider_error for outcome in failed),
        )
    check_deadline(config.deadline)

    docs = [entry for outcome in outcomes for entry in outcome.docs]
    fallback = fallback_overview(
        surface=surface, group_of=group_of, display_name=display_name
    )
    overview_md = fallback.overview_md
    on_stage("overview")
    with tracer.start_as_current_span("overview") as span:
        try:
            overview = complete_structured(
                model=model,
                messages=overview_messages(
                    title=surface.title,
                    summaries=[
                        f"{entry.operation_id}: {entry.summary}" for entry in docs
                    ],
                ),
                response_model=GeneratedOverview,
                fake=config.fake,
            )
            usage = usage + overview.usage
            overview_md = overview.value.overview_md
        except ProviderError, OutputValidationError:
            logger.warning(
                "Overview failed; using the deterministic overview", exc_info=True
            )
            span.add_event("overview.fallback")

    on_stage("merge")
    with tracer.start_as_current_span("merge"):
        page = DocPage(
            strategy="hybrid",
            surface=surface,
            overview=Overview(overview_md=overview_md, groups=fallback.groups),
            operations=order_docs(surface, docs),
        )
    return GenerationResult(
        page=page, usage=usage, parts_total=len(batches), parts_failed=len(failed)
    )


def generate_parser(
    *, surface: ApiSurface, group_of: Callable[[Operation], str], display_name: str
) -> GenerationResult:
    """The `parser` strategy: the parsed structure with source descriptions, no LLM."""
    page = build_unenriched_docpage(
        surface=surface, group_of=group_of, display_name=display_name
    )
    return GenerationResult(page=page, usage=Usage())
