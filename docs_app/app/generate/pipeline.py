"""Creating generations and turning their stored input into a `DocPage`."""

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

import psycopg
from d2u.generations.models import (
    ErrorCode,
    Generation,
    GenerationStage,
    GenerationStatus,
    InputOrigin,
)
from d2u.llm.artifacts import Programs, load_programs
from d2u.llm.exceptions import (
    ArtifactNotFoundError,
    GenerationFailedError,
    GenerationTimeoutError,
    LLMConfigurationError,
)
from d2u.llm.generator import GeneratorConfig, generate_docpage
from d2u.llm.lm import build_lm
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
    generation_span,
    stage_span,
    tag_current_span,
)
from plain.runtime import APP_PATH, settings

logger = logging.getLogger(__name__)

# Repository root: docs_app/app is APP_PATH. Artifacts and test fixtures live there.
REPO_ROOT = APP_PATH.parent.parent
ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "programs"


@dataclass(frozen=True, slots=True)
class SubmittedInput:
    """Validated input from the source form."""

    origin: InputOrigin
    filename: str
    data: bytes
    language: str
    entry: str = ""


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
    never processes a generation twice.
    """
    claimed = Generation.query.filter(
        id=generation_id, status=GenerationStatus.PENDING.value
    ).update(
        status=GenerationStatus.RUNNING.value,
        stage=GenerationStage.BUNDLE.value,
        started_at=datetime.now(UTC),
        program_version=settings.LLM_PROGRAM_VERSION,
        model=settings.LLM_MODEL,
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
        program_version=generation.program_version,
        parent=parent,
    ):
        run_generation(generation)


def run_generation(generation: Generation) -> None:
    """Bundle, extract, enrich, write the overview and merge; record the outcome.

    Expected failures are recorded as a failed status with an error code.
    """
    deadline = time.monotonic() + settings.GENERATIONS_TIMEOUT_S
    try:
        with stage_span(GenerationStage.BUNDLE.value):
            _set_stage(generation, GenerationStage.BUNDLE)
            prepared = build_bundle(generation, adapters=available_adapters())
            adapter = prepared.adapter
            generation.input_manifest = prepared.manifest.model_dump(mode="json")
            generation.update(fields=["input_manifest"])

        with stage_span(GenerationStage.EXTRACT.value) as span:
            _set_stage(generation, GenerationStage.EXTRACT)
            surface = adapter.extract(prepared.bundle)
            span.set_attribute("docs.operations.total", len(surface.operations))
        generation.language = adapter.name
        generation.update(fields=["language"])

        _set_stage(generation, GenerationStage.ENRICH)
        result = generate_docpage(
            surface=surface,
            group_of=adapter.group_key,
            display_name=adapter.display_name,
            lm=build_lm(
                model=settings.LLM_MODEL,
                thinking_level=settings.LLM_THINKING_LEVEL,
                fake_responses_path=_fake_responses_path(),
            ),
            programs=_programs(generation.program_version),
            config=GeneratorConfig(
                token_budget=settings.LLM_BATCH_TOKEN_BUDGET,
                max_operations=settings.LLM_BATCH_MAX_OPERATIONS,
                max_concurrency=settings.LLM_MAX_CONCURRENCY,
                deadline=deadline,
            ),
            on_progress=lambda done, total: _set_progress(generation, done, total),
            on_stage=lambda stage: _set_stage(generation, GenerationStage(stage)),
        )
    except InputError as exc:
        mark_failed(
            generation.id,
            code=ErrorCode.INPUT_ERROR,
            detail={"message": exc.message, "path": exc.path, "line": exc.line},
        )
        return
    except GenerationTimeoutError as exc:
        mark_failed(generation.id, code=ErrorCode.TIMEOUT, detail={"message": str(exc)})
        return
    except GenerationFailedError as exc:
        code = ErrorCode.PROVIDER_ERROR if exc.provider else ErrorCode.VALIDATION_ERROR
        mark_failed(generation.id, code=code, detail={"message": str(exc)})
        return
    except (LLMConfigurationError, ArtifactNotFoundError) as exc:
        logger.exception("Generation %s is misconfigured", generation.id)
        mark_failed(
            generation.id, code=ErrorCode.PROVIDER_ERROR, detail={"message": str(exc)}
        )
        return

    generation.doc_json = result.page.model_dump(mode="json")
    generation.status = GenerationStatus.SUCCEEDED.value
    generation.finished_at = datetime.now(UTC)
    generation.update(fields=["doc_json", "status", "finished_at"])
    logger.info(
        "Generation %s succeeded (%s of %s batches failed)",
        generation.id,
        result.batches_failed,
        result.batches_total,
    )


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


def _set_progress(generation: Generation, done: int, total: int) -> None:
    generation.progress = {"batches_done": done, "batches_total": total}
    generation.update(fields=["progress"])


def _fake_responses_path() -> Path | None:
    if not settings.LLM_FAKE_RESPONSES:
        return None
    path = Path(settings.LLM_FAKE_RESPONSES)
    return path if path.is_absolute() else REPO_ROOT / path


@cache
def _load_programs_cached(root: Path, version: str) -> Programs:
    return load_programs(root=root, version=version)


def _programs(version: str) -> Programs:
    return _load_programs_cached(ARTIFACTS_ROOT, version)
