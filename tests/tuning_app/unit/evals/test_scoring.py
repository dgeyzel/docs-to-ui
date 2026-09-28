import pytest
from d2u.schemas.judging import ClaimVerdict, JudgeVerdict

from app.evals.metrics.scoring import (
    METRIC_WEIGHTS,
    Weights,
    invalid_score,
    prose_quality,
    score_example,
    weighted_total,
)
from app.evals.metrics.stats import estimate, summarize
from tests.tuning_app.unit.evals.pages import http_op, page, param

GOLD = page(http_op("GET", "/pets", param("limit")))
PERFECT_JUDGE = JudgeVerdict(
    claims=[
        ClaimVerdict(operation_id="GET /pets", claim="Lists pets.", supported=True)
    ],
    prose_quality=5,
)


def test_default_metric_weights_match_the_spec() -> None:
    assert METRIC_WEIGHTS == {
        "faithfulness": 0.30,
        "component_accuracy": 0.30,
        "coverage": 0.10,
        "example_validity": 0.10,
        "prose_quality": 0.20,
    }


def test_invalid_output_scores_zero_everywhere() -> None:
    score = invalid_score("validation_error: bad")

    assert score.valid is False
    assert score.total == 0.0
    assert set(score.metrics.values()) == {0.0}
    assert score.details == {"reason": "validation_error: bad"}


def test_a_perfect_page_scores_everything_but_missing_examples() -> None:
    score = score_example(
        output=GOLD, gold=GOLD, parser=None, verdict=PERFECT_JUDGE, weights=Weights()
    )

    assert score.metrics == {
        "faithfulness": 1.0,
        "component_accuracy": 1.0,
        "coverage": 1.0,
        "example_validity": 0.0,
        "prose_quality": 1.0,
    }
    assert score.total == pytest.approx(0.9)


def test_without_a_verdict_the_judged_parts_score_zero() -> None:
    score = score_example(
        output=GOLD, gold=GOLD, parser=None, verdict=None, weights=Weights()
    )

    assert score.metrics["prose_quality"] == 0.0
    assert score.metrics["faithfulness"] == 0.5


@pytest.mark.parametrize(("rating", "scaled"), [(1, 0.0), (3, 0.5), (5, 1.0)])
def test_prose_quality_scales_the_rating(rating: int, scaled: float) -> None:
    assert prose_quality(JudgeVerdict(claims=[], prose_quality=rating)) == scaled


def test_weights_are_relative() -> None:
    metrics = {name: 1.0 if name == "coverage" else 0.0 for name in METRIC_WEIGHTS}

    assert weighted_total(metrics, {"coverage": 2.0, "faithfulness": 2.0}) == 0.5
    assert weighted_total(metrics, {}) == 0.0


def test_estimates_have_a_deterministic_interval_around_the_mean() -> None:
    values = [0.2, 0.4, 0.6, 0.8, 1.0]

    first, second = estimate(values), estimate(values)

    assert first == second
    assert first.mean == pytest.approx(0.6)
    assert first.low <= first.mean <= first.high
    assert estimate([0.5]) == estimate([0.5, 0.5]).__class__(0.5, 0.5, 0.5)
    assert estimate([]).mean == 0.0


def test_summaries_cover_the_total_every_metric_and_every_component() -> None:
    good = score_example(
        output=GOLD, gold=GOLD, parser=None, verdict=PERFECT_JUDGE, weights=Weights()
    )
    failed = invalid_score("timeout")

    summary = summarize([good.as_dict(), failed.as_dict()])

    assert summary["total"]["total"]["mean"] == pytest.approx(0.45)
    assert summary["metrics"]["coverage"]["mean"] == 0.5
    assert summary["components"]["operations"]["mean"] == 0.5
    assert summarize([]) == {"total": {}, "metrics": {}, "components": {}}
