import pytest
from d2u.schemas.docpage import DocPage, OperationDocs

from app.evals.metrics.examples import example_validity
from tests.tuning_app.unit.evals.pages import example, http_op, page

GOLD = page(http_op("GET", "/pets/{id}"))


def with_examples(*examples: object) -> DocPage:
    base = page(http_op("GET", "/pets/{id}"))
    return base.model_copy(
        update={
            "operations": [
                OperationDocs(
                    operation_id="GET /pets/{id}",
                    summary="Get a pet",
                    description_md="",
                    param_descriptions={},
                    examples=list(examples),  # ty: ignore[invalid-argument-type]
                )
            ]
        }
    )


@pytest.mark.parametrize(
    ("snippet", "valid"),
    [
        (example("json", '{"id": 1}'), 1.0),
        (example("json", "{id: 1}"), 0.0),
        (example("python", "client.get(1)"), 1.0),
        (example("python", "def ("), 0.0),
        (example("curl", "curl https://api.example.com/v1/pets/7"), 1.0),
        (example("curl", "curl https://api.example.com/owners/7"), 0.0),
    ],
)
def test_each_checkable_language_is_validated(snippet: object, valid: float) -> None:
    assert example_validity(with_examples(snippet), GOLD) == (valid, 1)


def test_unknown_languages_are_skipped_and_no_examples_scores_zero() -> None:
    assert example_validity(with_examples(example("ruby", "Pet.get")), GOLD) == (0.0, 0)
    assert example_validity(with_examples(), GOLD) == (0.0, 0)
