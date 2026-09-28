"""Scoring one example against its gold page (SPEC §9.5). Plain-free.

| Metric             | Default weight |
| Schema validity    | gate: 0 if invalid |
| Faithfulness       | 0.30 |
| Component accuracy | 0.30 |
| Coverage           | 0.10 |
| Example validity   | 0.10 |
| Prose quality      | 0.20 (judge, 1–5 scaled to 0–1) |
"""

from dataclasses import dataclass, field

from d2u.schemas.docpage import ApiSurface, DocPage
from d2u.schemas.judging import JudgeVerdict

from app.evals.metrics.components import (
    COMPONENT_WEIGHTS,
    component_scores,
    coverage,
    operation_differences,
)
from app.evals.metrics.examples import example_validity
from app.evals.metrics.faithfulness import faithfulness

METRIC_WEIGHTS: dict[str, float] = {
    "faithfulness": 0.30,
    "component_accuracy": 0.30,
    "coverage": 0.10,
    "example_validity": 0.10,
    "prose_quality": 0.20,
}
METRICS = tuple(METRIC_WEIGHTS)


@dataclass(frozen=True, slots=True)
class Weights:
    """Metric weights and the component weights inside component accuracy."""

    metrics: dict[str, float] = field(default_factory=lambda: dict(METRIC_WEIGHTS))
    components: dict[str, float] = field(
        default_factory=lambda: dict(COMPONENT_WEIGHTS)
    )


@dataclass(frozen=True, slots=True)
class ExampleScore:
    """Every metric and component for one example, and the weighted total.

    `details` holds what the results page shows: invented and missing
    operations, and the judge's rationales.
    """

    valid: bool
    metrics: dict[str, float]
    components: dict[str, float]
    total: float
    details: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        """The score as stored on a result."""
        return {
            "valid": self.valid,
            "total": self.total,
            "metrics": self.metrics,
            "components": self.components,
        }


def prose_quality(verdict: JudgeVerdict | None) -> float:
    """The judge's 1–5 rating as 0–1; 0 without a verdict."""
    return (verdict.prose_quality - 1) / 4 if verdict is not None else 0.0


def weighted_total(metrics: dict[str, float], weights: dict[str, float]) -> float:
    """The weighted mean of the metrics (weights need not sum to 1)."""
    total_weight = sum(weights.get(name, 0.0) for name in METRICS)
    if total_weight <= 0:
        return 0.0
    return (
        sum(metrics[name] * weights.get(name, 0.0) for name in METRICS) / total_weight
    )


def invalid_score(reason: str) -> ExampleScore:
    """The score of an output that failed or didn't validate: zero everywhere."""
    return ExampleScore(
        valid=False,
        metrics=dict.fromkeys(METRICS, 0.0),
        components=dict.fromkeys(("precision", "recall", *COMPONENT_WEIGHTS), 0.0),
        total=0.0,
        details={"reason": reason},
    )


def score_example(
    *,
    output: DocPage,
    gold: DocPage,
    parser: ApiSurface | None,
    verdict: JudgeVerdict | None,
    weights: Weights,
) -> ExampleScore:
    """Score a valid output page. Without a judge verdict, judged parts score 0."""
    components = component_scores(output, gold)
    faithful = faithfulness(output, gold, parser=parser, verdict=verdict)
    validity, checked = example_validity(output, gold)
    metrics = {
        "faithfulness": faithful.score,
        "component_accuracy": components.weighted(weights.components),
        "coverage": coverage(output, gold),
        "example_validity": validity,
        "prose_quality": prose_quality(verdict),
    }
    metrics = {name: round(value, 6) for name, value in metrics.items()}
    return ExampleScore(
        valid=True,
        metrics=metrics,
        components=components.as_dict(),
        total=round(weighted_total(metrics, weights.metrics), 6),
        details={
            "faithfulness_deterministic": round(faithful.deterministic, 6),
            "faithfulness_judge": round(faithful.judge, 6),
            "invented": list(faithful.invented),
            "examples_checked": checked,
            **operation_differences(output, gold),
        },
    )
