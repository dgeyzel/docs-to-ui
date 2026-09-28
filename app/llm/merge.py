"""Validating LLM output against the extracted surface.

The LLM may return IDs that don't exist. They are dropped here, never shown.
"""

from dataclasses import dataclass, field

from app.llm.schemas import ApiSurface, Operation, OperationDocs, Overview


@dataclass(frozen=True, slots=True)
class MergeReport:
    """IDs the LLM returned that were not in the surface."""

    unknown_operation_ids: list[str] = field(default_factory=list)
    unknown_param_ids: list[str] = field(default_factory=list)

    @property
    def dropped(self) -> bool:
        return bool(self.unknown_operation_ids or self.unknown_param_ids)


def merge_enrichment(
    operations: list[Operation], docs: list[OperationDocs]
) -> tuple[list[OperationDocs], MergeReport]:
    """Keep docs for known operations only, once each, with known param IDs.

    Args:
        operations: The operations the batch was asked about.
        docs: What the LLM returned for the batch.
    """
    params_by_op = {op.id: {param.id for param in op.params} for op in operations}
    kept: list[OperationDocs] = []
    seen: set[str] = set()
    unknown_ops: list[str] = []
    unknown_params: list[str] = []

    for entry in docs:
        known_params = params_by_op.get(entry.operation_id)
        if known_params is None:
            unknown_ops.append(entry.operation_id)
            continue
        if entry.operation_id in seen:
            continue
        seen.add(entry.operation_id)
        descriptions = {}
        for param_id, text in entry.param_descriptions.items():
            if param_id in known_params:
                descriptions[param_id] = text
            else:
                unknown_params.append(param_id)
        kept.append(entry.model_copy(update={"param_descriptions": descriptions}))

    return kept, MergeReport(
        unknown_operation_ids=unknown_ops, unknown_param_ids=unknown_params
    )


def merge_overview(
    surface: ApiSurface, overview: Overview
) -> tuple[Overview, MergeReport]:
    """Keep known operation IDs in groups, each at most once; drop empty groups.

    Operations the LLM left out of every group are placed by the renderer
    under their group hint.
    """
    known = {op.id for op in surface.operations}
    placed: set[str] = set()
    unknown: list[str] = []
    groups: dict[str, list[str]] = {}
    for name, op_ids in overview.groups.items():
        kept = []
        for op_id in op_ids:
            if op_id not in known:
                unknown.append(op_id)
            elif op_id not in placed:
                placed.add(op_id)
                kept.append(op_id)
        if kept and name.strip():
            groups[name.strip()] = kept
    merged = Overview(overview_md=overview.overview_md, groups=groups)
    return merged, MergeReport(unknown_operation_ids=unknown)


def order_docs(surface: ApiSurface, docs: list[OperationDocs]) -> list[OperationDocs]:
    """Sort docs into surface order so stored pages are deterministic."""
    position = {op.id: index for index, op in enumerate(surface.operations)}
    return sorted(docs, key=lambda entry: position[entry.operation_id])
