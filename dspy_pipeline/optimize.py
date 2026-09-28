"""Offline optimization and evaluation for the generation programs.

Usage (reads GEMINI_API_KEY and other settings from the environment):
    uv run --env-file .env python -m dspy_pipeline.optimize evaluate --version baseline
    uv run --env-file .env python -m dspy_pipeline.optimize optimize --version v1
    uv run --env-file .env python -m dspy_pipeline.optimize export-feedback --output candidates.jsonl

This pipeline imports `app.llm` and `app.sources`, which never import Plain,
so it runs without booting the app. Traces go to whichever backends
`PLAIN_TELEMETRY_BACKENDS` lists.
"""

import argparse
import hashlib
import json
import logging
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any, Literal

import dspy
import psycopg
import pydantic
from dspy.utils.exceptions import AdapterParseError, LMError
from pydantic import BaseModel, ConfigDict

from app.llm.artifacts import (
    ENRICH_PROGRAM,
    OVERVIEW_PROGRAM,
    ArtifactMeta,
    load_program,
    save_program,
)
from app.llm.batching import build_batches
from app.llm.lm import build_lm
from app.llm.schemas import ApiSurface
from app.sources.adapters.base import LanguageAdapter
from app.sources.archive import ArchiveLimits, read_zip
from app.sources.bundle import SourceBundle, SourceFile
from app.sources.registry import ADAPTERS, select_files
from dspy_pipeline.metrics.enrich import (
    Judge,
    llm_judge,
    make_enrich_metric,
    score_enrichment,
)

logger = logging.getLogger(__name__)

PIPELINE_DIR = Path(__file__).resolve().parent
DATASETS_DIR = PIPELINE_DIR / "datasets"
DEFAULT_ARTIFACTS_ROOT = PIPELINE_DIR.parent / "artifacts" / "programs"
LANGUAGES = ("openapi", "python")
# Matches SOURCES_ZIP_* defaults; feedback inputs were already accepted once.
FEEDBACK_ARCHIVE_LIMITS = ArchiveLimits(
    max_uncompressed_bytes=52428800, max_file_bytes=5242880, max_entries=5000
)
Split = Literal["train", "dev"]


class DatasetEntry(BaseModel):
    """One input to document: its files as they would arrive in the app."""

    model_config = ConfigDict(frozen=True)

    id: str
    language: str
    origin: Literal["paste", "file", "zip"]
    files: dict[str, str]
    entry: str | None = None
    operation_id: str | None = None
    comment: str | None = None


def load_entries(*, languages: Sequence[str], split: Split) -> list[DatasetEntry]:
    """Read the dataset entries for the given languages and split."""
    entries: list[DatasetEntry] = []
    for language in languages:
        path = DATASETS_DIR / language / f"{split}.jsonl"
        with path.open(encoding="utf-8") as handle:
            entries.extend(
                DatasetEntry.model_validate_json(line)
                for line in handle
                if line.strip()
            )
    return entries


def dataset_hash(entries: Sequence[DatasetEntry]) -> str:
    """A stable hash of the entries, recorded in artifact metadata."""
    canonical = json.dumps(
        [entry.model_dump(mode="json") for entry in entries], sort_keys=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def entry_surface(entry: DatasetEntry) -> tuple[ApiSurface, LanguageAdapter]:
    """Extract an entry's surface exactly as the app would."""
    adapter = ADAPTERS[entry.language]
    bundle = SourceBundle(
        files=[
            SourceFile(path=path, text=text)
            for path, text in sorted(entry.files.items())
        ],
        origin=entry.origin,
        entry=entry.entry,
    )
    selected, _ = select_files(bundle, adapter)
    return adapter.extract(selected), adapter


def batch_examples(
    entries: Sequence[DatasetEntry], *, token_budget: int, max_operations: int
) -> list[dspy.Example]:
    """One `EnrichOperations` example per batch, batched as the app batches."""
    examples = []
    for entry in entries:
        surface, adapter = entry_surface(entry)
        for batch in build_batches(
            surface.operations,
            group_of=adapter.group_key,
            token_budget=token_budget,
            max_operations=max_operations,
        ):
            examples.append(
                dspy.Example(
                    operations=batch.operations,
                    api_title=surface.title,
                    language=surface.language,
                    entry_id=entry.id,
                ).with_inputs("operations", "api_title", "language")
            )
    return examples


def evaluate_program(
    program: dspy.Module,
    examples: Sequence[dspy.Example],
    *,
    lm: dspy.BaseLM,
    judge: Judge,
) -> dict[str, Any]:
    """Run a program over examples and average every metric component."""
    rows = []
    for example in examples:
        try:
            with dspy.context(lm=lm):
                prediction = program(**example.inputs())
            result = prediction.result
        except LMError, AdapterParseError, pydantic.ValidationError, ValueError:
            # An example that errors scores zero rather than stopping the run.
            logger.warning("Example from %s failed", example.entry_id, exc_info=True)
            result = None
        score = score_enrichment(
            operations=example.operations, result=result, judge=judge
        )
        rows.append({"entry": example.entry_id, **score.components()})
    components = ("coverage", "fidelity", "consistency", "examples", "prose", "total")
    return {
        "examples": len(rows),
        "mean": {
            name: round(fmean(row[name] for row in rows), 6) if rows else 0.0
            for name in components
        },
        "rows": rows,
    }


def configure_tracing() -> None:
    """Send eval traces to the backends in PLAIN_TELEMETRY_BACKENDS."""
    names = json.loads(os.environ.get("PLAIN_TELEMETRY_BACKENDS", "[]"))
    if not names:
        return
    from openinference.instrumentation.dspy import DSPyInstrumentor
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(
        resource=Resource.create({"service.name": "docs-to-ui-evals"})
    )
    if "native" in names:
        from app.traces.exporter import PostgresSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(
                PostgresSpanExporter(
                    database_url=os.environ["DATABASE_URL"],
                    max_attribute_bytes=int(
                        os.environ.get(
                            "PLAIN_TELEMETRY_NATIVE_MAX_ATTRIBUTE_BYTES", "262144"
                        )
                    ),
                )
            )
        )
    if "langfuse" in names:
        from app.telemetry.otlp import langfuse_span_exporter

        provider.add_span_processor(
            BatchSpanProcessor(
                langfuse_span_exporter(
                    base_url=os.environ["LANGFUSE_BASE_URL"],
                    public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
                    secret_key=os.environ["LANGFUSE_SECRET_KEY"],
                )
            )
        )
    trace.set_tracer_provider(provider)
    DSPyInstrumentor().instrument()


def _languages(value: str) -> list[str]:
    return list(LANGUAGES) if value == "all" else [value]


def _lms(args: argparse.Namespace) -> tuple[dspy.BaseLM, dspy.BaseLM]:
    fake = Path(args.fake_responses) if args.fake_responses else None
    lm = build_lm(
        model=args.model, thinking_level=args.thinking_level, fake_responses_path=fake
    )
    judge_lm = build_lm(
        model=args.judge_model,
        thinking_level=args.judge_thinking_level,
        fake_responses_path=fake,
    )
    return lm, judge_lm


def command_evaluate(args: argparse.Namespace) -> dict[str, Any]:
    """Score a saved program version on a split."""
    lm, judge_lm = _lms(args)
    program = load_program(
        root=Path(args.artifacts_root), program=ENRICH_PROGRAM, version=args.version
    )
    entries = load_entries(languages=_languages(args.language), split=args.split)
    examples = batch_examples(
        entries, token_budget=args.token_budget, max_operations=args.max_operations
    )
    report = evaluate_program(program, examples, lm=lm, judge=llm_judge(judge_lm))
    return {
        "command": "evaluate",
        "version": args.version,
        "split": args.split,
        **report,
    }


def command_optimize(args: argparse.Namespace) -> dict[str, Any]:
    """Optimize `EnrichOperations` on the train split and save a new version."""
    lm, judge_lm = _lms(args)
    root = Path(args.artifacts_root)
    languages = _languages(args.language)
    train_entries = load_entries(languages=languages, split="train")
    dev_entries = load_entries(languages=languages, split="dev")
    trainset = batch_examples(
        train_entries,
        token_budget=args.token_budget,
        max_operations=args.max_operations,
    )
    devset = batch_examples(
        dev_entries, token_budget=args.token_budget, max_operations=args.max_operations
    )
    judge = llm_judge(judge_lm)
    metric = make_enrich_metric(judge)
    student = load_program(root=root, program=ENRICH_PROGRAM, version=args.base_version)

    with dspy.context(lm=lm):
        if args.optimizer == "miprov2":
            optimizer = dspy.MIPROv2(metric=metric, auto="light")
            optimized = optimizer.compile(
                student, trainset=trainset, max_bootstrapped_demos=args.max_demos
            )
        else:
            optimizer = dspy.BootstrapFewShot(
                metric=metric,
                max_bootstrapped_demos=args.max_demos,
                max_labeled_demos=0,
            )
            optimized = optimizer.compile(student, trainset=trainset)

    report = evaluate_program(optimized, devset, lm=lm, judge=judge)
    created_at = datetime.now(UTC).replace(microsecond=0)
    common = {
        "version": args.version,
        "dataset_hash": dataset_hash([*train_entries, *dev_entries]),
        "model": args.model,
        "thinking_level": args.thinking_level,
        "dspy_version": dspy.__version__,
        "created_at": created_at,
    }
    save_program(
        optimized,
        root=root,
        meta=ArtifactMeta(
            program=ENRICH_PROGRAM,
            scores={"dev_total": report["mean"]["total"]},
            **common,
        ),
    )
    # The overview program isn't optimized yet; carry the base version forward
    # so every program exists at the new version.
    overview = load_program(
        root=root, program=OVERVIEW_PROGRAM, version=args.base_version
    )
    save_program(
        overview,
        root=root,
        meta=ArtifactMeta(program=OVERVIEW_PROGRAM, scores={}, **common),
    )
    return {"command": "optimize", "version": args.version, **report}


def feedback_candidates(database_url: str) -> list[DatasetEntry]:
    """👎 feedback with a comment, as dataset entries awaiting human review."""
    query = """
        SELECT f.id, f.operation_id, f.comment,
               g.language, g.input_origin, g.input_filename, g.input_entry, g.input_blob
        FROM generations_feedback AS f
        JOIN generations_generation AS g ON g.id = f.generation_id
        WHERE f.score = -1 AND f.comment <> '' AND g.language <> ''
        ORDER BY f.id
    """
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()

    candidates = []
    for (
        feedback_id,
        operation_id,
        comment,
        language,
        origin,
        filename,
        entry,
        blob,
    ) in rows:
        data = bytes(blob)
        if origin == "zip":
            files = {
                file.path: file.text
                for file in read_zip(data, limits=FEEDBACK_ARCHIVE_LIMITS).files
            }
        else:
            name = filename or f"input{ADAPTERS[language].file_extensions[0]}"
            files = {name: data.decode("utf-8-sig")}
        candidates.append(
            DatasetEntry(
                id=f"feedback-{feedback_id}",
                language=language,
                origin=origin,
                files=files,
                entry=entry or None,
                operation_id=operation_id or None,
                comment=comment,
            )
        )
    return candidates


def command_export_feedback(args: argparse.Namespace) -> dict[str, Any]:
    """Write feedback candidates to a JSONL file for review."""
    candidates = feedback_candidates(args.database_url)
    with Path(args.output).open("w", encoding="utf-8") as handle:
        handle.writelines(
            candidate.model_dump_json(exclude_none=True) + "\n"
            for candidate in candidates
        )
    return {
        "command": "export-feedback",
        "output": args.output,
        "candidates": len(candidates),
    }


def build_parser() -> argparse.ArgumentParser:
    """The command-line interface."""
    parser = argparse.ArgumentParser(
        prog="dspy_pipeline.optimize", description=__doc__.splitlines()[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def add_model_options(command: argparse.ArgumentParser) -> None:
        command.add_argument("--language", choices=[*LANGUAGES, "all"], default="all")
        command.add_argument(
            "--model",
            default=os.environ.get("PLAIN_LLM_MODEL", "gemini/gemini-3.8-flash"),
        )
        command.add_argument(
            "--thinking-level",
            default=os.environ.get("PLAIN_LLM_THINKING_LEVEL", "medium"),
        )
        command.add_argument(
            "--judge-model",
            default=os.environ.get("PLAIN_LLM_JUDGE_MODEL", "gemini/gemini-3.8-flash"),
        )
        command.add_argument(
            "--judge-thinking-level",
            default=os.environ.get("PLAIN_LLM_JUDGE_THINKING_LEVEL", "high"),
        )
        command.add_argument(
            "--fake-responses", default=os.environ.get("PLAIN_LLM_FAKE_RESPONSES", "")
        )
        command.add_argument("--token-budget", type=int, default=60000)
        command.add_argument("--max-operations", type=int, default=25)
        command.add_argument("--artifacts-root", default=str(DEFAULT_ARTIFACTS_ROOT))

    evaluate = commands.add_parser(
        "evaluate", help="Score a program version on a dataset split."
    )
    add_model_options(evaluate)
    evaluate.add_argument("--version", default="baseline")
    evaluate.add_argument("--split", choices=["train", "dev"], default="dev")
    evaluate.set_defaults(handler=command_evaluate)

    optimize = commands.add_parser(
        "optimize", help="Optimize EnrichOperations and save a version."
    )
    add_model_options(optimize)
    optimize.add_argument("--version", required=True)
    optimize.add_argument("--base-version", default="baseline")
    optimize.add_argument(
        "--optimizer", choices=["bootstrap", "miprov2"], default="bootstrap"
    )
    optimize.add_argument("--max-demos", type=int, default=4)
    optimize.set_defaults(handler=command_optimize)

    export = commands.add_parser(
        "export-feedback", help="Export 👎 feedback as dataset candidates."
    )
    export.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    export.add_argument("--output", required=True)
    export.set_defaults(handler=command_export_feedback)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command and print its report as JSON. Returns the exit code."""
    args = build_parser().parse_args(argv)
    configure_tracing()
    report = args.handler(args)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
