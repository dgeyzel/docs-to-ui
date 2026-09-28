"""Turning the LLM's `GeneratedPage` into a stored `DocPage` (SPEC §6.2).

IDs are derived here, never taken from the LLM, so pages built by the `llm`,
`hybrid` and `parser` strategies use the same IDs for the same operations.
"""

import re
from dataclasses import dataclass, field

from d2u.schemas.docpage import (
    ApiSurface,
    DocPage,
    Operation,
    OperationDocs,
    Overview,
    Param,
    SourceLocation,
)
from d2u.schemas.generated import GeneratedOperation, GeneratedPage, GeneratedParam

_SLASHES = re.compile(r"/{2,}")


@dataclass(slots=True)
class ConversionReport:
    """Adjustments made while converting, recorded as span events."""

    id_collisions: list[str] = field(default_factory=list)
    dropped_locations: list[str] = field(default_factory=list)


def normalize_path(path: str) -> str:
    """An HTTP path with one leading slash and no trailing slash."""
    cleaned = "/" + _SLASHES.sub("/", path.strip()).strip("/")
    return cleaned


def base_operation_id(op: GeneratedOperation) -> str:
    """`"{METHOD} {path}"` for HTTP, the qualified name for Python.

    Falls back to the signature when the fields an ID needs are missing.
    """
    if op.kind == "http" and op.method and op.path:
        return f"{op.method.strip().upper()} {normalize_path(op.path)}"
    if op.kind != "http" and op.qualified_name and op.qualified_name.strip():
        return op.qualified_name.strip()
    return op.signature.strip()


def unique_id(base: str, used: set[str], report: ConversionReport) -> str:
    """`base`, or `base~2`, `base~3`, ... if it was already used."""
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}~{suffix}"
        suffix += 1
    if candidate != base:
        report.id_collisions.append(candidate)
    used.add(candidate)
    return candidate


def _location(
    op: GeneratedOperation, line_counts: dict[str, int], report: ConversionReport
) -> SourceLocation | None:
    if not op.source_path:
        return None
    lines = line_counts.get(op.source_path)
    line = op.source_line if op.source_line is not None else 1
    if lines is None or line < 1 or line > lines:
        report.dropped_locations.append(f"{op.source_path}:{line}")
        return None
    return SourceLocation(path=op.source_path, line=line)


def convert_operation(
    op: GeneratedOperation,
    *,
    op_id: str,
    line_counts: dict[str, int],
    report: ConversionReport,
) -> tuple[Operation, OperationDocs]:
    """Split one generated operation into its structure and its prose."""
    used_params: set[str] = set()
    params: list[Param] = []
    descriptions: dict[str, str] = {}
    for param in op.params:
        param_id = unique_id(f"{op_id}#{param.name}", used_params, report)
        params.append(
            Param(
                id=param_id,
                name=param.name,
                location=param.location,
                type=param.type,
                required=param.required,
                default=param.default,
            )
        )
        if param.description:
            descriptions[param_id] = param.description
    operation = Operation(
        id=op_id,
        kind=op.kind,
        signature=op.signature,
        group_hint=op.group,
        params=params,
        returns=op.returns,
        location=_location(op, line_counts, report),
    )
    docs = OperationDocs(
        operation_id=op_id,
        summary=op.summary,
        description_md=op.description_md,
        param_descriptions=descriptions,
        examples=op.examples,
    )
    return operation, docs


def generated_to_docpage(
    page: GeneratedPage, *, language: str, line_counts: dict[str, int]
) -> tuple[DocPage, ConversionReport]:
    """Build a `DocPage` (strategy `llm`) from what the LLM returned.

    Args:
        page: The validated LLM output.
        language: The input language, e.g. "openapi".
        line_counts: Line count of every bundle file, used to drop source
            locations that don't exist.
    """
    report = ConversionReport()
    used: set[str] = set()
    operations: list[Operation] = []
    docs: list[OperationDocs] = []
    groups: dict[str, list[str]] = {}
    for generated in page.operations:
        op_id = unique_id(base_operation_id(generated), used, report)
        operation, operation_docs = convert_operation(
            generated, op_id=op_id, line_counts=line_counts, report=report
        )
        operations.append(operation)
        docs.append(operation_docs)
        groups.setdefault(generated.group.strip() or "Other", []).append(op_id)
    return (
        DocPage(
            strategy="llm",
            surface=ApiSurface(
                title=page.title, language=language, operations=operations
            ),
            overview=Overview(overview_md=page.overview_md, groups=groups),
            operations=docs,
        ),
        report,
    )


def merge_parts(parts: list[GeneratedPage]) -> tuple[GeneratedPage, list[str]]:
    """Combine the pages generated for each part of a split input.

    Operations are unioned by derived ID; the first occurrence wins, and the
    IDs of dropped duplicates are returned. The title and overview come from
    the first part; the caller replaces the overview with one written for
    the whole input.
    """
    seen: set[str] = set()
    duplicates: list[str] = []
    operations: list[GeneratedOperation] = []
    for part in parts:
        for op in part.operations:
            op_id = base_operation_id(op)
            if op_id in seen:
                duplicates.append(op_id)
                continue
            seen.add(op_id)
            operations.append(op)
    first = parts[0]
    merged = GeneratedPage(
        title=first.title, overview_md=first.overview_md, operations=operations
    )
    return merged, duplicates


_ID_SUFFIX = re.compile(r"~\d+$")


def _split_http_id(op_id: str) -> tuple[str | None, str | None]:
    method, _, path = _ID_SUFFIX.sub("", op_id).partition(" ")
    return (method, path) if path.startswith("/") else (None, None)


def docpage_to_generated(page: DocPage) -> GeneratedPage:
    """The inverse of `generated_to_docpage`, for editing a stored page.

    HTTP operations get their method and path back from their ID, and Python
    operations their qualified name. Prose comes from the page's docs, or the
    source descriptions for operations without docs. Converting the result
    back derives the same IDs.
    """
    docs = {entry.operation_id: entry for entry in page.operations}
    group_of = {
        op_id: group
        for group, op_ids in page.overview.groups.items()
        for op_id in op_ids
    }
    operations: list[GeneratedOperation] = []
    for op in page.surface.operations:
        entry = docs.get(op.id)
        descriptions = entry.param_descriptions if entry else {}
        method, path = _split_http_id(op.id) if op.kind == "http" else (None, None)
        summary = entry.summary if entry else (op.source_description or "")
        operations.append(
            GeneratedOperation(
                kind=op.kind,
                method=method,
                path=path,
                qualified_name=None if op.kind == "http" else _ID_SUFFIX.sub("", op.id),
                signature=op.signature,
                group=group_of.get(op.id, op.group_hint),
                summary=summary.split("\n", 1)[0][:200],
                description_md=entry.description_md if entry else "",
                params=[
                    GeneratedParam(
                        name=param.name,
                        location=param.location,
                        type=param.type,
                        required=param.required,
                        default=param.default,
                        description=descriptions.get(
                            param.id, param.source_description or ""
                        ),
                    )
                    for param in op.params
                ],
                returns=op.returns,
                examples=list(entry.examples) if entry else [],
                source_path=op.location.path if op.location else None,
                source_line=op.location.line if op.location else None,
            )
        )
    return GeneratedPage(
        title=page.surface.title,
        overview_md=page.overview.overview_md,
        operations=operations,
    )
