import pytest
from d2u.schemas.judging import ClaimVerdict, JudgeVerdict

from app.evals.metrics.faithfulness import (
    deterministic_faithfulness,
    faithfulness,
    judge_faithfulness,
)
from tests.tuning_app.unit.evals.pages import http_op, page, param

GOLD = page(http_op("GET", "/pets", param("limit")))


def verdict(*supported: bool) -> JudgeVerdict:
    return JudgeVerdict(
        claims=[
            ClaimVerdict(operation_id="", claim=f"c{i}", supported=s)
            for i, s in enumerate(supported)
        ],
        prose_quality=3,
    )


def test_nothing_invented_is_fully_faithful() -> None:
    assert deterministic_faithfulness(GOLD, GOLD, None) == (1.0, ())


def test_invented_operations_parameters_and_types_are_counted() -> None:
    output = page(
        http_op("GET", "/pets", param("limit", type="string"), param("secret")),
        http_op("DELETE", "/pets"),
    )

    score, invented = deterministic_faithfulness(output, GOLD, None)

    # Supported: the operation, the limit parameter. Invented: its type, secret, DELETE.
    assert score == pytest.approx(2 / 5)
    assert invented == ("GET /pets#limit: string", "GET /pets#secret", "DELETE /pets")


def test_the_parser_surface_also_counts_as_support() -> None:
    parser = page(http_op("DELETE", "/pets")).surface
    output = page(http_op("DELETE", "/pets"))

    assert deterministic_faithfulness(output, GOLD, parser)[0] == 1.0
    assert deterministic_faithfulness(output, GOLD, None)[0] == 0.0


def test_an_empty_output_invents_nothing() -> None:
    assert deterministic_faithfulness(page(), GOLD, None)[0] == 1.0


@pytest.mark.parametrize(
    ("judged", "expected"),
    [(verdict(True, True, False, True), 0.75), (verdict(), 1.0), (None, 0.0)],
)
def test_the_judge_half_is_the_share_of_supported_claims(
    judged: JudgeVerdict | None, expected: float
) -> None:
    assert judge_faithfulness(judged) == expected


def test_faithfulness_is_the_equal_weight_mean_of_both_halves() -> None:
    output = page(http_op("GET", "/pets", param("limit")), http_op("DELETE", "/pets"))

    score = faithfulness(output, GOLD, parser=None, verdict=verdict(True, False))

    assert score.deterministic == pytest.approx(3 / 4)
    assert score.judge == 0.5
    assert score.score == pytest.approx(0.625)
