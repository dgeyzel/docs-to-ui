import pytest

from app.evals.metrics.components import (
    COMPONENT_WEIGHTS,
    component_scores,
    coverage,
    operation_differences,
)
from tests.tuning_app.unit.evals.pages import http_op, page, param

GOLD = page(
    http_op("GET", "/pets", param("limit", default="20"), returns="200 array"),
    http_op("POST", "/pets", param("body", location="body", type="Pet", required=True)),
)


def test_default_component_weights_sum_to_one() -> None:
    assert sum(COMPONENT_WEIGHTS.values()) == pytest.approx(1.0)


def test_an_identical_page_agrees_on_every_component() -> None:
    scores = component_scores(GOLD, GOLD)

    assert set(scores.as_dict().values()) == {1.0}
    assert scores.weighted(COMPONENT_WEIGHTS) == pytest.approx(1.0)


def test_the_operation_set_is_scored_by_precision_recall_and_f1() -> None:
    output = page(
        http_op("GET", "/pets", param("limit", default="20"), returns="200 array"),
        http_op("DELETE", "/pets"),
    )

    scores = component_scores(output, GOLD)

    assert (scores.precision, scores.recall, scores.operations) == (0.5, 0.5, 0.5)
    assert operation_differences(output, GOLD) == {
        "missing": ["POST /pets"],
        "invented": ["DELETE /pets"],
    }


def test_matched_parameters_are_compared_field_by_field() -> None:
    output = page(
        http_op(
            "GET",
            "/pets",
            param("limit", type="string", default="'20'"),
            returns="201 array",
        ),
        http_op(
            "POST", "/pets", param("body", location="query", type="pet", required=False)
        ),
    )

    scores = component_scores(output, GOLD)

    assert scores.param_names == 1.0
    assert scores.param_types == 0.5
    assert scores.param_locations == 0.5
    assert scores.param_required == 0.5
    assert scores.param_defaults == 1.0
    assert scores.returns == 0.5


def test_parameter_names_are_an_f1_per_operation() -> None:
    output = page(
        http_op(
            "GET",
            "/pets",
            param("limit", default="20"),
            param("q"),
            returns="200 array",
        )
    )

    assert component_scores(output, GOLD).param_names == pytest.approx(2 / 3)


def test_no_matched_operations_scores_zero_on_field_components() -> None:
    scores = component_scores(page(http_op("GET", "/other")), GOLD)

    assert scores.operations == 0.0
    assert scores.signatures == 0.0
    assert scores.weighted(COMPONENT_WEIGHTS) == 0.0


def test_operations_without_parameters_on_both_sides_agree() -> None:
    gold = page(http_op("GET", "/health"))

    assert component_scores(page(http_op("GET", "/health")), gold).param_types == 1.0


def test_groups_and_signatures_are_compared_loosely() -> None:
    output = page(
        http_op(
            "GET",
            "/pets",
            param("limit", default="20"),
            returns="200 array",
            group="pets",
            signature="GET  /pets",
        )
    )

    gold = page(
        http_op("GET", "/pets", param("limit", default="20"), returns="200 ARRAY")
    )

    scores = component_scores(output, gold)

    assert (scores.groups, scores.signatures, scores.returns) == (1.0, 1.0, 1.0)


def test_component_accuracy_uses_the_given_weights() -> None:
    output = page(
        http_op(
            "GET",
            "/pets",
            param("limit", type="string", default="20"),
            returns="200 array",
        )
    )
    gold = page(
        http_op("GET", "/pets", param("limit", default="20"), returns="200 array")
    )
    scores = component_scores(output, gold)

    assert scores.weighted({"param_types": 1.0}) == 0.0
    assert scores.weighted({"operations": 1.0, "param_types": 1.0}) == 0.5
    assert scores.weighted({}) == 0.0


@pytest.mark.parametrize(
    ("output_ops", "expected"),
    [((), 0.0), (("GET",), 0.5), (("GET", "POST"), 1.0)],
)
def test_coverage_is_the_share_of_gold_operations_present(
    output_ops: tuple[str, ...], expected: float
) -> None:
    output = page(*[http_op(method, "/pets") for method in output_ops])

    assert coverage(output, GOLD) == expected


def test_an_empty_gold_page_is_fully_covered() -> None:
    assert coverage(GOLD, page()) == 1.0
