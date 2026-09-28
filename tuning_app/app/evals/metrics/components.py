"""Component accuracy and coverage (SPEC §9.5). Plain-free.

Operations are matched by derived ID. Parameters of matched operations are
matched by name. Each component is a share between 0 and 1; component
accuracy is their weighted mean.
"""

from dataclasses import asdict, dataclass

from d2u.schemas.docpage import DocPage, Param

COMPONENT_WEIGHTS: dict[str, float] = {
    "operations": 0.30,
    "param_names": 0.15,
    "param_locations": 0.10,
    "param_types": 0.10,
    "param_required": 0.10,
    "param_defaults": 0.05,
    "returns": 0.05,
    "signatures": 0.10,
    "groups": 0.05,
}


@dataclass(frozen=True, slots=True)
class ComponentScores:
    """Field-level agreement with the gold page.

    `operations` is the F1 of the operation sets; the rest are measured on
    matched operations (and their matched parameters).
    """

    precision: float
    recall: float
    operations: float
    param_names: float
    param_locations: float
    param_types: float
    param_required: float
    param_defaults: float
    returns: float
    signatures: float
    groups: float

    def weighted(self, weights: dict[str, float]) -> float:
        """The weighted mean of the components (weights need not sum to 1)."""
        total = sum(weights.get(name, 0.0) for name in COMPONENT_WEIGHTS)
        if total <= 0:
            return 0.0
        values = asdict(self)
        return (
            sum(values[name] * weights.get(name, 0.0) for name in COMPONENT_WEIGHTS)
            / total
        )

    def as_dict(self) -> dict[str, float]:
        """Every component, for storage."""
        return {name: round(value, 6) for name, value in asdict(self).items()}


def _text(value: str | None) -> str:
    return " ".join((value or "").split())


def _loose(value: str | None) -> str:
    return _text(value).strip("'\"`").casefold()


def group_of(page: DocPage) -> dict[str, str]:
    """Each operation's navigation group (its group hint if it has none)."""
    groups = {
        op_id: name for name, ids in page.overview.groups.items() for op_id in ids
    }
    return {op.id: groups.get(op.id, op.group_hint) for op in page.surface.operations}


def _share(matches: list[bool], *, empty: float) -> float:
    return sum(matches) / len(matches) if matches else empty


def _f1(found: set[str], expected: set[str]) -> tuple[float, float, float]:
    if not found and not expected:
        return 1.0, 1.0, 1.0
    true_positives = len(found & expected)
    precision = true_positives / len(found) if found else 0.0
    recall = true_positives / len(expected) if expected else 0.0
    if true_positives == 0:
        return precision, recall, 0.0
    return precision, recall, 2 * precision * recall / (precision + recall)


def coverage(output: DocPage, gold: DocPage) -> float:
    """The share of gold operations present in the output (1.0 for an empty gold page)."""
    expected = {op.id for op in gold.surface.operations}
    if not expected:
        return 1.0
    found = {op.id for op in output.surface.operations}
    return len(expected & found) / len(expected)


def component_scores(output: DocPage, gold: DocPage) -> ComponentScores:
    """Compare an output page's structure with the gold page's."""
    found = {op.id: op for op in output.surface.operations}
    expected = {op.id: op for op in gold.surface.operations}
    precision, recall, f1 = _f1(set(found), set(expected))
    matched = [(found[op_id], expected[op_id]) for op_id in expected if op_id in found]
    if not matched:
        return ComponentScores(precision, recall, f1, *([0.0] * 8))

    found_groups, expected_groups = group_of(output), group_of(gold)
    name_scores: list[float] = []
    pairs: list[tuple[Param, Param]] = []
    for out_op, gold_op in matched:
        out_params = {param.name: param for param in out_op.params}
        gold_params = {param.name: param for param in gold_op.params}
        name_scores.append(_f1(set(out_params), set(gold_params))[2])
        pairs.extend(
            (out_params[name], gold_params[name])
            for name in gold_params
            if name in out_params
        )
    no_gold_params = not any(gold_op.params for _, gold_op in matched)
    empty = 1.0 if no_gold_params else 0.0

    return ComponentScores(
        precision=precision,
        recall=recall,
        operations=f1,
        param_names=sum(name_scores) / len(name_scores),
        param_locations=_share(
            [a.location == b.location for a, b in pairs], empty=empty
        ),
        param_types=_share(
            [_loose(a.type) == _loose(b.type) for a, b in pairs], empty=empty
        ),
        param_required=_share(
            [a.required == b.required for a, b in pairs], empty=empty
        ),
        param_defaults=_share(
            [_loose(a.default) == _loose(b.default) for a, b in pairs], empty=empty
        ),
        returns=_share(
            [_loose(a.returns) == _loose(b.returns) for a, b in matched], empty=1.0
        ),
        signatures=_share(
            [_text(a.signature) == _text(b.signature) for a, b in matched], empty=1.0
        ),
        groups=_share(
            [
                _loose(found_groups.get(a.id)) == _loose(expected_groups.get(b.id))
                for a, b in matched
            ],
            empty=1.0,
        ),
    )


def operation_differences(output: DocPage, gold: DocPage) -> dict[str, list[str]]:
    """Missing and invented operation IDs, for the results page."""
    found = {op.id for op in output.surface.operations}
    expected = {op.id for op in gold.surface.operations}
    return {"missing": sorted(expected - found), "invented": sorted(found - expected)}
