"""Faithfulness (SPEC §9.5): is everything in the output supported? Plain-free.

Faithfulness = 0.5 × deterministic + 0.5 × judge.

- Deterministic: the share of the output's operations, parameters and
  parameter types that exist in the gold page or, where available, the
  parser's surface. Nothing generated means nothing invented (1.0).
- Judge: the share of the judge's claims that the source supports. No
  claims scores 1.0; no judge verdict scores 0.
"""

from dataclasses import dataclass

from d2u.schemas.docpage import ApiSurface, DocPage
from d2u.schemas.judging import JudgeVerdict

DETERMINISTIC_SHARE = 0.5


@dataclass(frozen=True, slots=True)
class FaithfulnessScore:
    """Both halves of faithfulness, the combined score, and what was invented."""

    deterministic: float
    judge: float
    invented: tuple[str, ...]

    @property
    def score(self) -> float:
        return (
            DETERMINISTIC_SHARE * self.deterministic
            + (1 - DETERMINISTIC_SHARE) * self.judge
        )


def _type(value: str) -> str:
    return " ".join(value.split()).casefold()


def deterministic_faithfulness(
    output: DocPage, gold: DocPage, parser: ApiSurface | None
) -> tuple[float, tuple[str, ...]]:
    """The share of generated items found in the references, and the invented ones."""
    references = [gold.surface] + ([parser] if parser is not None else [])
    operations = {op.id for surface in references for op in surface.operations}
    types: dict[str, set[str]] = {}
    for surface in references:
        for op in surface.operations:
            for param in op.params:
                types.setdefault(param.id, set()).add(_type(param.type))

    supported = 0
    invented: list[str] = []
    for op in output.surface.operations:
        if op.id not in operations:
            invented.append(op.id)
            continue
        supported += 1
        for param in op.params:
            if param.id not in types:
                invented.append(param.id)
                continue
            supported += 1
            if _type(param.type) in types[param.id]:
                supported += 1
            else:
                invented.append(f"{param.id}: {param.type}")
    total = supported + len(invented)
    return (supported / total if total else 1.0), tuple(invented)


def judge_faithfulness(verdict: JudgeVerdict | None) -> float:
    """The share of the judge's claims that are supported."""
    if verdict is None:
        return 0.0
    if not verdict.claims:
        return 1.0
    return sum(claim.supported for claim in verdict.claims) / len(verdict.claims)


def faithfulness(
    output: DocPage,
    gold: DocPage,
    *,
    parser: ApiSurface | None,
    verdict: JudgeVerdict | None,
) -> FaithfulnessScore:
    """Combine the deterministic checks with the judge's claim verdicts."""
    deterministic, invented = deterministic_faithfulness(output, gold, parser)
    return FaithfulnessScore(
        deterministic=deterministic,
        judge=judge_faithfulness(verdict),
        invented=invented,
    )
