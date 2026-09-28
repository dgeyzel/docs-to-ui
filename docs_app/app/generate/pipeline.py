"""Creating generations and turning their stored input into a `DocPage`."""

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

import psycopg
from d2u.generation.client import FakeResponses, Usage
from d2u.generation.exceptions import (
    GenerationFailedError,
    GenerationTimeoutError,
    LLMConfigurationError,
    OutputValidationError,
    ProviderError,
)
from d2u.generation.strategies import (
    GenerationConfig,
    GenerationResult,
    generate_hybrid,
    generate_llm,
    generate_parser,
)
from d2u.generations.models import (
    ErrorCode,
    Generation,
    GenerationStage,
    GenerationStatus,
    InputOrigin,
    Strategy,
)
from d2u.registry.lookups import active_model, require_active_prompt
from d2u.registry.models import PromptVersion
from d2u.schemas.docpage import ApiSurface
from d2u.sources.adapters.base import LanguageAdapter
from d2u.sources.archive import ArchiveLimits, read_zip
from d2u.sources.bundle import (
    FileManifest,
    SourceBundle,
    manifest_for,
    single_file_bundle,
)
from d2u.sources.exceptions import InputError
from d2u.sources.registry import detect, enabled_adapters, get_adapter, select_files
from d2u.telemetry.api import (
    TraceContext,
    current_trace_context,
    generation_baggage,
    generation_span,
    stage_span,
    tag_current_span,
)
from plain.runtime import APP_PATH, settings

logger = logging.getLogger(__name__)

# Repository root: docs_app/app is APP_PATH. Test fixtures live there.
REPO_ROOT = APP_PATH.parent.parent


@dataclass(frozen=True, slots=True)
class SubmittedInput:
    """Validated input from the source form."""

    origin: InputOrigin
    filename: str
    data: bytes
    language: str
    entry: str = ""
    strategy: Strategy = Strategy.LLM


@dataclass(frozen=True, slots=True)
class PreparedInput:
    """The bundle an adapter will read, the adapter, and what was read."""

    bundle: SourceBundle
    adapter: LanguageAdapter
    manifest: FileManifest


def available_adapters() -> list[LanguageAdapter]:
    """The adapters enabled by `SOURCES_ENABLED_ADAPTERS`."""
    return enabled_adapters(settings.SOURCES_ENABLED_ADAPTERS)


def create_generation(submitted: SubmittedInput) -> Generation:
    """Store the raw input on a new pending generation.

    The current request's trace context is recorded so the job's spans join
    the same trace.
    """
    trace_context = current_trace_context()
    generation = Generation(
        language=submitted.language,
        input_origin=submitted.origin.value,
        input_filename=submitted.filename,
        input_entry=submitted.entry,
        strategy=submitted.strategy.value,
        input_blob=submitted.data,
        input_sha256=hashlib.sha256(submitted.data).hexdigest(),
        input_bytes=len(submitted.data),
        trace_id=trace_context.trace_id if trace_context else "",
        trace_span_id=trace_context.span_id if trace_context else "",
    )
    generation.create()
    tag_current_span(generation_id=generation.id)
    return generation


def regenerate(original: Generation) -> Generation:
    """A new pending generation from another generation's stored input."""
    return create_generation(
        SubmittedInput(
            origin=InputOrigin(original.input_origin),
            filename=original.input_filename,
            data=bytes(original.input_blob),
            language=original.language,
            entry=original.input_entry,
            strategy=Strategy(original.strategy),
        )
    )


def enqueue_generation(generation: Generation) -> None:
    """Queue the generation's job, or mark it failed with `enqueue_error`."""
    from app.generate.jobs import GenerateDocJob

    try:
        job_request = GenerateDocJob(generation.id).run_in_worker()
    except psycopg.Error:
        logger.exception("Could not enqueue generation %s", generation.id)
        job_request = None
    if job_request is None:
        mark_failed(
            generation.id,
            code=ErrorCode.ENQUEUE_ERROR,
            detail={"message": "The generation could not be queued. Try again."},
        )


def claim_generation(generation_id: int) -> Generation | None:
    """Move a pending generation to running; None if it isn't pending.

    The status check and update are one statement, so running the job twice
    never processes a generation twice. The active model is recorded now, so
    a later change in the Tuning app doesn't affect a running generation.
    """
    model = active_model()
    claimed = Generation.query.filter(
        id=generation_id, status=GenerationStatus.PENDING.value
    ).update(
        status=GenerationStatus.RUNNING.value,
        stage=GenerationStage.BUNDLE.value,
        started_at=datetime.now(UTC),
        llm_model=model,
        model=model.name if model else "",
    )
    if claimed == 0:
        return None
    return Generation.query.get(generation_id)


def mark_failed(generation_id: int, *, code: ErrorCode, detail: dict) -> None:
    """Record a failure on a generation that hasn't finished yet."""
    Generation.query.filter(
        id=generation_id,
        status__in=[GenerationStatus.PENDING.value, GenerationStatus.RUNNING.value],
    ).update(
        status=GenerationStatus.FAILED.value,
        error_code=code.value,
        error_detail=detail,
        finished_at=datetime.now(UTC),
    )
    logger.info("Generation %s failed with %s", generation_id, code.value)


def run_claimed_generation(generation: Generation) -> None:
    """Run a claimed generation inside a span that continues its request's trace."""
    parent = None
    if generation.trace_id and generation.trace_span_id:
        parent = TraceContext(
            trace_id=generation.trace_id, span_id=generation.trace_span_id
        )
    with generation_span(
        name="generate",
        generation_id=generation.id,
        prompt_version="",
        model=generation.model,
        parent=parent,
    ):
        run_generation(generation)


def prompt_label(prompt: PromptVersion) -> str:
    """How a prompt version is shown and traced, e.g. `openapi/llm/baseline`."""
    return f"{prompt.language}/{prompt.strategy}/{prompt.version}"


def run_generation(generation: Generation) -> None:
    """Bundle the input, run the generation's strategy, and record the outcome.

    Expected failures are recorded as a failed status with an error code.
    """
    config = GenerationConfig(
        max_concurrency=settings.GENERATIONS_MAX_CONCURRENCY,
        deadline=time.monotonic() + settings.GENERATIONS_TIMEOUT_S,
        fake=fake_responses(),
    )
    try:
        with stage_span(GenerationStage.BUNDLE.value):
            _set_stage(generation, GenerationStage.BUNDLE)
            prepared = build_bundle(generation, adapters=available_adapters())
            generation.input_manifest = prepared.manifest.model_dump(mode="json")
            generation.language = prepared.adapter.name
            generation.update(fields=["input_manifest", "language"])
        result = _run_strategy(generation, prepared, config)
    except InputError as exc:
        _fail(
            generation, ErrorCode.INPUT_ERROR, exc.message, path=exc.path, line=exc.line
        )
        return
    except GenerationTimeoutError as exc:
        _fail(generation, ErrorCode.TIMEOUT, str(exc))
        return
    except GenerationFailedError as exc:
        code = ErrorCode.PROVIDER_ERROR if exc.provider else ErrorCode.VALIDATION_ERROR
        _fail(generation, code, str(exc))
        return
    except OutputValidationError as exc:
        _fail(generation, ErrorCode.VALIDATION_ERROR, str(exc))
        return
    except ProviderError as exc:
        _fail(generation, ErrorCode.PROVIDER_ERROR, str(exc))
        return
    except LLMConfigurationError as exc:
        logger.exception("Generation %s is misconfigured", generation.id)
        _fail(generation, ErrorCode.PROVIDER_ERROR, str(exc))
        return

    _record_usage(generation, result.usage)
    generation.doc_json = result.page.model_dump(mode="json")
    generation.status = GenerationStatus.SUCCEEDED.value
    generation.finished_at = datetime.now(UTC)
    generation.update(
        fields=[
            "doc_json",
            "status",
            "finished_at",
            "input_tokens",
            "output_tokens",
            "cost_usd",
            "latency_ms",
        ]
    )
    logger.info(
        "Generation %s succeeded (%s of %s parts failed)",
        generation.id,
        result.parts_failed,
        result.parts_total,
    )


def _run_strategy(
    generation: Generation, prepared: PreparedInput, config: GenerationConfig
) -> GenerationResult:
    adapter = prepared.adapter
    strategy = Strategy(generation.strategy)
    on_progress = _progress_callback(generation)
    on_stage = _stage_callback(generation)

    if strategy == Strategy.PARSER:
        surface = _extract(generation, prepared)
        return generate_parser(
            surface=surface,
            group_of=adapter.group_key,
            display_name=adapter.display_name,
        )

    if strategy == Strategy.LLM:
        # Broken input fails here with a precise location, before any model call.
        with stage_span("check"):
            adapter.check_syntax(prepared.bundle)

    if generation.llm_model is None:
        raise LLMConfigurationError(
            "No active model is set. Choose one in the Tuning app."
        )
    model = generation.llm_model.to_spec()
    prompt = require_active_prompt(language=adapter.name, strategy=strategy.value)
    generation.prompt_version = prompt
    generation.prompt_label = prompt_label(prompt)
    generation.update(fields=["prompt_version", "prompt_label"])

    with generation_baggage(prompt_version=generation.prompt_label):
        if strategy == Strategy.LLM:
            return generate_llm(
                source_files={file.path: file.text for file in prepared.bundle.files},
                entry=adapter.entry_file(prepared.bundle),
                language=adapter.name,
                model=model,
                prompt=prompt.to_spec(),
                config=config,
                on_progress=on_progress,
                on_stage=on_stage,
            )
        surface = _extract(generation, prepared)
        return generate_hybrid(
            surface=surface,
            group_of=adapter.group_key,
            display_name=adapter.display_name,
            model=model,
            prompt=prompt.to_spec(),
            config=config,
            on_progress=on_progress,
            on_stage=on_stage,
        )


def _extract(generation: Generation, prepared: PreparedInput) -> ApiSurface:
    with stage_span(GenerationStage.EXTRACT.value) as span:
        _set_stage(generation, GenerationStage.EXTRACT)
        surface = prepared.adapter.extract(prepared.bundle)
        span.set_attribute("docs.operations.total", len(surface.operations))
    return surface


def _fail(
    generation: Generation,
    code: ErrorCode,
    message: str,
    *,
    path: str | None = None,
    line: int | None = None,
) -> None:
    detail: dict = {"message": message}
    if path is not None:
        detail |= {"path": path, "line": line}
    mark_failed(generation.id, code=code, detail=detail)


def _record_usage(generation: Generation, usage: Usage) -> None:
    generation.input_tokens = usage.input_tokens
    generation.output_tokens = usage.output_tokens
    generation.cost_usd = usage.cost_usd
    generation.latency_ms = usage.latency_ms


def build_bundle(
    generation: Generation, *, adapters: list[LanguageAdapter]
) -> PreparedInput:
    """Turn the stored input into a bundle and choose its adapter.

    A paste has no filename, so with auto-detection each adapter is offered
    the text under its own default file extension and the best sniff wins.
    A zip is read in memory under the `SOURCES_ZIP_*` limits, then filtered
    to the files the chosen adapter reads.

    Raises:
        InputError: The input is unreadable, too large, or its language is unknown.
    """
    data = bytes(generation.input_blob)
    requested = (
        get_adapter(name=generation.language, adapters=adapters)
        if generation.language
        else None
    )

    if generation.input_origin == InputOrigin.PASTE:
        candidates = [requested] if requested else adapters
        best: tuple[float, SourceBundle, LanguageAdapter] | None = None
        for adapter in candidates:
            bundle = single_file_bundle(
                filename=f"input{adapter.file_extensions[0]}", data=data, origin="paste"
            )
            score = adapter.sniff(bundle)
            if best is None or score > best[0]:
                best = (score, bundle, adapter)
        if best is None or (requested is None and best[0] == 0.0):
            raise InputError(
                path="",
                line=None,
                message="Could not detect the input language; choose one explicitly.",
            )
        return PreparedInput(
            bundle=best[1], adapter=best[2], manifest=manifest_for(best[1])
        )

    if generation.input_origin == InputOrigin.ZIP:
        contents = read_zip(data, limits=_archive_limits())
        everything = SourceBundle(
            files=contents.files, origin="zip", entry=generation.input_entry or None
        )
        adapter = requested or detect(bundle=everything, adapters=adapters)
        bundle, filtered_out = select_files(everything, adapter)
        skipped = sorted(
            [*contents.skipped, *filtered_out], key=lambda entry: entry.path
        )
        manifest = FileManifest(
            included=[file.path for file in bundle.files], skipped=skipped
        )
        return PreparedInput(bundle=bundle, adapter=adapter, manifest=manifest)

    bundle = single_file_bundle(
        filename=generation.input_filename, data=data, origin="file"
    )
    adapter = requested or detect(bundle=bundle, adapters=adapters)
    return PreparedInput(bundle=bundle, adapter=adapter, manifest=manifest_for(bundle))


def _archive_limits() -> ArchiveLimits:
    return ArchiveLimits(
        max_uncompressed_bytes=settings.SOURCES_ZIP_MAX_UNCOMPRESSED_BYTES,
        max_file_bytes=settings.SOURCES_ZIP_MAX_FILE_BYTES,
        max_entries=settings.SOURCES_ZIP_MAX_ENTRIES,
    )


def _set_stage(generation: Generation, stage: GenerationStage) -> None:
    generation.stage = stage.value
    generation.update(fields=["stage"])


def _stage_callback(generation: Generation) -> Callable[[str], None]:
    def on_stage(stage: str) -> None:
        _set_stage(generation, GenerationStage(stage))

    return on_stage


def _progress_callback(generation: Generation) -> Callable[[int, int], None]:
    def on_progress(done: int, total: int) -> None:
        generation.progress = {"done": done, "total": total}
        generation.update(fields=["progress"])

    return on_progress


def fake_responses() -> FakeResponses | None:
    """Fixture answers for the fake model, when `GENERATIONS_FAKE_RESPONSES` is set."""
    if not settings.GENERATIONS_FAKE_RESPONSES:
        return None
    return _load_fake_responses(settings.GENERATIONS_FAKE_RESPONSES)


@cache
def _load_fake_responses(configured: str) -> FakeResponses:
    path = Path(configured)
    return FakeResponses.from_file(path if path.is_absolute() else REPO_ROOT / path)
