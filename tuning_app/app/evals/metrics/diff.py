"""Where a generated page differs from its gold page, for the results page. Plain-free.

Operations are matched by derived ID and parameters by name, the same way
component accuracy matches them. Each difference names the field, the
expected value and the generated one.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from d2u.schemas.docpage import DocPage, Operation, Param

from app.evals.metrics.components import group_of


class Presence(StrEnum):
    MATCHED = "matched"
    MISSING = "missing"
    INVENTED = "invented"


@dataclass(frozen=True, slots=True)
class FieldDiff:
    """One field whose generated value differs from the gold value."""

    field: str
    expected: str
    generated: str


@dataclass(frozen=True, slots=True)
class ParamDiff:
    """A parameter's presence and, when matched, its differing fields."""

    name: str
    presence: Presence
    fields: tuple[FieldDiff, ...] = ()


@dataclass(frozen=True, slots=True)
class OperationDiff:
    """An operation's presence and, when matched, what differs."""

    operation_id: str
    presence: Presence
    fields: tuple[FieldDiff, ...] = ()
    params: tuple[ParamDiff, ...] = ()
    expected_summary: str = ""
    generated_summary: str = ""

    @property
    def differs(self) -> bool:
        """Whether anything about the operation differs from the gold page."""
        return (
            self.presence != Presence.MATCHED
            or bool(self.fields)
            or any(
                param.presence != Presence.MATCHED or param.fields
                for param in self.params
            )
        )


@dataclass(frozen=True, slots=True)
class PageDiff:
    """Every operation of both pages, gold order first, then invented ones."""

    operations: tuple[OperationDiff, ...] = field(default_factory=tuple)

    def count(self, presence: Presence) -> int:
        """How many operations have this presence."""
        return sum(1 for op in self.operations if op.presence == presence)

    @property
    def wrong_fields(self) -> int:
        """Differing fields across matched operations and parameters."""
        return sum(
            len(op.fields) + sum(len(param.fields) for param in op.params)
            for op in self.operations
        )


def _show(value: object) -> str:
    return "—" if value is None or value == "" else str(value)


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip("'\"`").casefold()


def _field_diffs(pairs: list[tuple[str, object, object]]) -> tuple[FieldDiff, ...]:
    return tuple(
        FieldDiff(field=name, expected=_show(expected), generated=_show(generated))
        for name, expected, generated in pairs
        if _norm(expected) != _norm(generated)
    )


def _param_diffs(generated: Operation, gold: Operation) -> tuple[ParamDiff, ...]:
    found: dict[str, Param] = {param.name: param for param in generated.params}
    diffs: list[ParamDiff] = []
    for expected in gold.params:
        actual = found.pop(expected.name, None)
        if actual is None:
            diffs.append(ParamDiff(name=expected.name, presence=Presence.MISSING))
            continue
        diffs.append(
            ParamDiff(
                name=expected.name,
                presence=Presence.MATCHED,
                fields=_field_diffs(
                    [
                        ("location", expected.location, actual.location),
                        ("type", expected.type, actual.type),
                        ("required", expected.required, actual.required),
                        ("default", expected.default, actual.default),
                    ]
                ),
            )
        )
    diffs.extend(ParamDiff(name=name, presence=Presence.INVENTED) for name in found)
    return tuple(diffs)


def _summaries(page: DocPage) -> dict[str, str]:
    return {entry.operation_id: entry.summary for entry in page.operations}


def page_diff(generated: DocPage, gold: DocPage) -> PageDiff:
    """Compare a generated page with its gold page, operation by operation."""
    found = {op.id: op for op in generated.surface.operations}
    generated_groups, gold_groups = group_of(generated), group_of(gold)
    generated_summaries, gold_summaries = _summaries(generated), _summaries(gold)
    diffs: list[OperationDiff] = []
    for expected in gold.surface.operations:
        actual = found.pop(expected.id, None)
        if actual is None:
            diffs.append(
                OperationDiff(
                    operation_id=expected.id,
                    presence=Presence.MISSING,
                    expected_summary=gold_summaries.get(expected.id, ""),
                )
            )
            continue
        diffs.append(
            OperationDiff(
                operation_id=expected.id,
                presence=Presence.MATCHED,
                fields=_field_diffs(
                    [
                        ("signature", expected.signature, actual.signature),
                        ("returns", expected.returns, actual.returns),
                        (
                            "group",
                            gold_groups.get(expected.id),
                            generated_groups.get(actual.id),
                        ),
                    ]
                ),
                params=_param_diffs(actual, expected),
                expected_summary=gold_summaries.get(expected.id, ""),
                generated_summary=generated_summaries.get(actual.id, ""),
            )
        )
    diffs.extend(
        OperationDiff(
            operation_id=op_id,
            presence=Presence.INVENTED,
            generated_summary=generated_summaries.get(op_id, ""),
        )
        for op_id in found
    )
    return PageDiff(operations=tuple(diffs))
