import pytest

from app.evals.metrics.compare import (
    RunScores,
    compare_examples,
    compare_metrics,
    comparison_warnings,
)


def summary(total: float, coverage: float) -> dict:
    def est(value: float) -> dict:
        return {"mean": value, "low": value, "high": value}

    return {
        "total": {"total": est(total)},
        "metrics": {"coverage": est(coverage)},
        "components": {},
    }


BASE = RunScores(
    1, "#1", summary(0.5, 0.4), {10: 0.5, 11: 0.8, 12: 0.2}, {10: "a", 11: "b", 12: "c"}
)
NEXT = RunScores(
    2, "#2", summary(0.7, 0.4), {10: 0.9, 11: 0.3, 13: 0.6}, {10: "a", 11: "b", 13: "d"}
)


def test_metrics_are_reported_as_deltas_from_the_baseline() -> None:
    (total,) = compare_metrics([BASE, NEXT], "total", ["total"])
    (coverage,) = compare_metrics([BASE, NEXT], "metrics", ["coverage", "unknown"])

    assert total.means == (0.5, 0.7)
    assert total.deltas[1] == pytest.approx(0.2)
    assert coverage.deltas == (0.0, 0.0)


def test_examples_are_sorted_from_most_improved_to_most_regressed() -> None:
    rows = compare_examples([BASE, NEXT])

    assert [(row.label, row.change) for row in rows] == [
        ("a", "better"),
        ("c", "same"),
        ("d", "same"),
        ("b", "worse"),
    ]
    assert rows[1].totals == (0.2, None)


def test_tiny_changes_count_as_the_same() -> None:
    first = RunScores(1, "#1", {}, {1: 0.500}, {1: "x"})
    second = RunScores(2, "#2", {}, {1: 0.505}, {1: "x"})

    assert compare_examples([first, second])[0].change == "same"


def test_warnings_name_what_differs_between_runs() -> None:
    assert (
        comparison_warnings(
            gold_hashes=["a", "a"], splits=["dev", "dev"], metric_versions=[1, 1]
        )
        == []
    )
    assert (
        len(
            comparison_warnings(
                gold_hashes=["a", "b"], splits=["dev", "test"], metric_versions=[1, 2]
            )
        )
        == 3
    )
