"""Summaries across examples: means with 95% confidence intervals. Plain-free."""

import random
from collections.abc import Sequence
from dataclasses import dataclass

BOOTSTRAP_RESAMPLES = 1000
# Fixed, so the same results always give the same interval.
BOOTSTRAP_SEED = 7


@dataclass(frozen=True, slots=True)
class Estimate:
    """A mean and its 95% bootstrap percentile interval."""

    mean: float
    low: float
    high: float

    def as_dict(self) -> dict[str, float]:
        return {
            "mean": round(self.mean, 6),
            "low": round(self.low, 6),
            "high": round(self.high, 6),
        }


def estimate(values: Sequence[float]) -> Estimate:
    """The mean of `values` with a 95% bootstrap confidence interval.

    One value (or none) has no spread, so its interval is the value itself.
    """
    if not values:
        return Estimate(0.0, 0.0, 0.0)
    mean = sum(values) / len(values)
    if len(values) == 1:
        return Estimate(mean, mean, mean)
    rng = random.Random(BOOTSTRAP_SEED)
    means = sorted(
        sum(rng.choices(values, k=len(values))) / len(values)
        for _ in range(BOOTSTRAP_RESAMPLES)
    )
    low = means[int(0.025 * BOOTSTRAP_RESAMPLES)]
    high = means[int(0.975 * BOOTSTRAP_RESAMPLES) - 1]
    return Estimate(mean, low, high)


def summarize(scores: Sequence[dict]) -> dict[str, dict[str, dict[str, float]]]:
    """Estimates for the total, every metric and every component.

    `scores` are stored example scores (`ExampleScore.as_dict()`); failed
    examples are included with their zeros.
    """
    if not scores:
        return {"total": {}, "metrics": {}, "components": {}}
    metric_names = list(scores[0]["metrics"])
    component_names = list(scores[0]["components"])
    return {
        "total": {"total": estimate([score["total"] for score in scores]).as_dict()},
        "metrics": {
            name: estimate([score["metrics"][name] for score in scores]).as_dict()
            for name in metric_names
        },
        "components": {
            name: estimate([score["components"][name] for score in scores]).as_dict()
            for name in component_names
        },
    }
