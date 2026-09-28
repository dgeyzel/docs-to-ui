"""Turns a stored `DocPage` into the values the doc-page templates render.

All decisions about what to show live here so the templates stay free of
logic. Every piece of untrusted Markdown goes through `render_markdown`.
"""

import re
from dataclasses import dataclass

from d2u.generations.models import Generation, GenerationStage, GenerationStatus
from d2u.schemas.docpage import DocPage, Operation, OperationDocs
from markupsafe import Markup

from app.generate.markdown import render_markdown

BADGE_METHODS = ("get", "post", "put", "patch", "delete")
EXAMPLE_LABELS = {"curl": "curl", "python": "Python", "json": "JSON"}


@dataclass(frozen=True, slots=True)
class ParamRow:
    name: str
    location: str
    type: str
    required: bool
    default: str
    description: Markup


@dataclass(frozen=True, slots=True)
class ExampleTab:
    anchor: str
    label: str
    title: str
    code: str


@dataclass(frozen=True, slots=True)
class OperationView:
    operation_id: str
    anchor: str
    method: str
    method_class: str
    label: str
    summary: str
    description: Markup
    params: list[ParamRow]
    examples: list[ExampleTab]
    returns: str
    source_location: str
    enriched: bool


@dataclass(frozen=True, slots=True)
class GroupView:
    anchor: str
    name: str
    operations: list[OperationView]


@dataclass(frozen=True, slots=True)
class PageView:
    title: str
    language: str
    overview: Markup
    groups: list[GroupView]


@dataclass(frozen=True, slots=True)
class ErrorView:
    title: str
    location: str
    message: str


ERROR_TITLES = {
    "input_error": "Input error",
    "validation_error": "Validation error",
    "provider_error": "Model provider error",
    "timeout": "Timed out",
    "worker_lost": "Worker lost",
    "enqueue_error": "Could not start generation",
}


def build_error_view(*, error_code: str, error_detail: dict) -> ErrorView | None:
    """Describe a failed generation's error, or None when there is none.

    `error_detail` holds `message` and, for input errors, `path` and `line`.
    """
    if not error_code:
        return None
    path = error_detail.get("path") or ""
    line = error_detail.get("line")
    location = f"{path}:{line}" if path and line else path
    return ErrorView(
        title=ERROR_TITLES.get(error_code, error_code),
        location=location,
        message=error_detail.get("message") or "",
    )


def build_page_view(*, page: DocPage, language_display: str) -> PageView:
    """Build the render model for a doc page.

    Groups follow `page.overview.groups`. Unknown IDs there are ignored, and
    operations missing from every group are appended under their group hint.
    """
    docs_by_id = {docs.operation_id: docs for docs in page.operations}
    ops_by_id = {op.id: op for op in page.surface.operations}
    anchors = _Anchors()

    grouped: dict[str, list[Operation]] = {}
    placed: set[str] = set()
    for name, op_ids in page.overview.groups.items():
        for op_id in op_ids:
            op = ops_by_id.get(op_id)
            if op is None or op_id in placed:
                continue
            grouped.setdefault(name, []).append(op)
            placed.add(op_id)
    for op in page.surface.operations:
        if op.id not in placed:
            grouped.setdefault(op.group_hint, []).append(op)
            placed.add(op.id)

    groups = [
        GroupView(
            anchor=anchors.make(f"group-{name}"),
            name=name,
            operations=[
                _operation_view(op, docs_by_id.get(op.id), anchors) for op in ops
            ],
        )
        for name, ops in grouped.items()
    ]
    return PageView(
        title=page.surface.title,
        language=language_display,
        overview=render_markdown(page.overview.overview_md),
        groups=groups,
    )


def _operation_view(
    op: Operation, docs: OperationDocs | None, anchors: _Anchors
) -> OperationView:
    method, label = _method_and_label(op)
    anchor = anchors.make(f"op-{op.id}")
    param_descriptions = docs.param_descriptions if docs else {}
    params = [
        ParamRow(
            name=param.name,
            location=param.location,
            type=param.type,
            required=param.required,
            default=param.default or "",
            description=render_markdown(
                param_descriptions.get(param.id) or param.source_description
            ),
        )
        for param in op.params
    ]
    examples = []
    if docs:
        examples = [
            ExampleTab(
                anchor=f"{anchor}-example-{index}",
                label=EXAMPLE_LABELS.get(example.language.lower(), example.language),
                title=example.title,
                code=example.code,
            )
            for index, example in enumerate(docs.examples)
        ]
    location = ""
    if op.location:
        location = f"{op.location.path}:{op.location.line}"

    return OperationView(
        operation_id=op.id,
        anchor=anchor,
        method=method,
        method_class=method if method in BADGE_METHODS else "other",
        label=label,
        summary=docs.summary if docs else "",
        description=render_markdown(
            docs.description_md if docs else op.source_description
        ),
        params=params,
        examples=examples,
        returns=op.returns or "",
        source_location=location,
        enriched=docs is not None,
    )


def _method_and_label(op: Operation) -> tuple[str, str]:
    if op.kind == "http":
        method, _, path = op.signature.partition(" ")
        if path:
            return method.lower(), path
    return "", op.signature


class _Anchors:
    """Produces unique, deterministic HTML ids."""

    def __init__(self) -> None:
        self._used: set[str] = set()

    def make(self, text: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "item"
        anchor = base
        suffix = 2
        while anchor in self._used:
            anchor = f"{base}-{suffix}"
            suffix += 1
        self._used.add(anchor)
        return anchor


STAGE_LABELS = (
    (GenerationStage.BUNDLE, "Bundle"),
    (GenerationStage.EXTRACT, "Extract"),
    (GenerationStage.ENRICH, "Enrich"),
    (GenerationStage.OVERVIEW, "Overview"),
    (GenerationStage.MERGE, "Merge"),
)


@dataclass(frozen=True, slots=True)
class StepView:
    number: int
    label: str
    state: str


@dataclass(frozen=True, slots=True)
class StatusView:
    steps: list[StepView]
    batches_done: int
    batches_total: int
    percent: int
    progress_label: str


def build_status_view(generation: Generation) -> StatusView:
    """The stage stepper and batch progress for a generation.

    Steps before the current stage are "completed", the current one is
    "active" (only while running) and later ones "upcoming".
    """
    stages = [stage for stage, _ in STAGE_LABELS]
    running = generation.status == GenerationStatus.RUNNING
    current = stages.index(generation.stage) if generation.stage in stages else -1
    if generation.status == GenerationStatus.SUCCEEDED:
        current = len(stages)

    steps = []
    for index, (_, label) in enumerate(STAGE_LABELS):
        if index < current:
            state = "completed"
        elif index == current and running:
            state = "active"
        else:
            state = "upcoming"
        steps.append(StepView(number=index + 1, label=label, state=state))

    done = int(generation.progress.get("batches_done", 0))
    total = int(generation.progress.get("batches_total", 0))
    percent = round(100 * done / total) if total else 0
    if generation.status == GenerationStatus.PENDING:
        progress_label = "Waiting for a worker…"
    elif total:
        progress_label = f"Enriched {done} of {total} batches"
    else:
        progress_label = "Preparing…"
    return StatusView(
        steps=steps,
        batches_done=done,
        batches_total=total,
        percent=percent,
        progress_label=progress_label,
    )


def wall_time_label(generation: Generation) -> str:
    """How long the generation ran, e.g. "1m 05s", or "" if not finished."""
    if generation.started_at is None or generation.finished_at is None:
        return ""
    seconds = max(
        0, round((generation.finished_at - generation.started_at).total_seconds())
    )
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"
