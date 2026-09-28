"""Comparing eval runs on the same gold set (SPEC §9.3). Plain-free.

The first run is the baseline: every other run's metrics and examples are
reported as deltas from it.
"""

from dataclasses import dataclass

# Changes smaller than this are noise, not an example getting better or worse.
CHANGE_THRESHOLD = 0.01


@dataclass(frozen=True, slots=True)
class RunScores:
    """What a comparison needs from one run."""

    run_id: int
    label: str
    summary: dict
    totals: dict[int, float]
    labels: dict[int, str]


@dataclass(frozen=True, slots=True)
class MetricComparison:
    """One metric across runs: each run's mean and its delta from the baseline."""

    name: str
    means: tuple[float | None, ...]
    deltas: tuple[float | None, ...]


@dataclass(frozen=True, slots=True)
class ExampleComparison:
    """One example's total in each run, and each run's change from the baseline."""

    example_id: int
    label: str
    totals: tuple[float | None, ...]
    deltas: tuple[float | None, ...]

    @property
    def change(self) -> str:
        """ "better", "worse" or "same", judged on the last run against the baseline."""
        delta = self.deltas[-1] if self.deltas else None
        if delta is None or abs(delta) < CHANGE_THRESHOLD:
            return "same"
        return "better" if delta > 0 else "worse"


def _mean(summary: dict, section: str, name: str) -> float | None:
    value = summary.get(section, {}).get(name)
    return None if value is None else float(value["mean"])


def _deltas(values: tuple[float | None, ...]) -> tuple[float | None, ...]:
    base = values[0]
    return tuple(
        None if base is None or value is None else round(value - base, 6)
        for value in values
    )


def compare_metrics(
    runs: list[RunScores], section: str, names: list[str]
) -> list[MetricComparison]:
    """Rows for the total ("total" section), metrics or components."""
    rows = []
    for name in names:
        means = tuple(_mean(run.summary, section, name) for run in runs)
        if all(mean is None for mean in means):
            continue
        rows.append(MetricComparison(name=name, means=means, deltas=_deltas(means)))
    return rows


def compare_examples(runs: list[RunScores]) -> list[ExampleComparison]:
    """Every example in any run, most improved first, then most regressed last."""
    example_ids = sorted({example_id for run in runs for example_id in run.totals})
    labels = {
        example_id: label for run in runs for example_id, label in run.labels.items()
    }
    rows = []
    for example_id in example_ids:
        totals = tuple(run.totals.get(example_id) for run in runs)
        rows.append(
            ExampleComparison(
                example_id=example_id,
                label=labels.get(example_id, f"#{example_id}"),
                totals=totals,
                deltas=_deltas(totals),
            )
        )
    return sorted(rows, key=lambda row: -(row.deltas[-1] or 0.0))


def comparison_warnings(
    *, gold_hashes: list[str], splits: list[str], metric_versions: list[int]
) -> list[str]:
    """What makes the runs less comparable, in words."""
    warnings = []
    if len(set(gold_hashes)) > 1:
        warnings.append(
            "The gold set changed between these runs (different content hashes)."
        )
    if len(set(splits)) > 1:
        warnings.append("The runs used different splits.")
    if len(set(metric_versions)) > 1:
        warnings.append("The runs were scored with different metric versions.")
    return warnings
