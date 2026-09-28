import pytest
from d2u.schemas.docpage import (
    ApiSurface,
    BatchEnrichment,
    Example,
    Operation,
    OperationDocs,
    Param,
)
from dspy.utils.dummies import DummyLM

from dspy_pipeline.metrics.enrich import (
    WEIGHTS,
    JudgeVerdict,
    coverage,
    example_validity,
    fidelity,
    llm_judge,
    make_enrich_metric,
    score_enrichment,
)
from dspy_pipeline.metrics.extract import score_extraction

OPS = [
    Operation(
        id="GET /pets/{id}",
        kind="http",
        signature="GET /pets/{id}",
        group_hint="pets",
        params=[
            Param(
                id="GET /pets/{id}#id",
                name="id",
                location="path",
                type="string",
                required=True,
            )
        ],
    ),
    Operation(
        id="POST /pets",
        kind="http",
        signature="POST /pets",
        group_hint="pets",
        params=[],
    ),
]


def docs(
    op_id: str,
    *,
    params: dict[str, str] | None = None,
    examples: list[Example] | None = None,
) -> OperationDocs:
    return OperationDocs(
        operation_id=op_id,
        summary="S",
        description_md="D",
        param_descriptions=params or {},
        examples=examples or [],
    )


def fixed_judge(consistency: float, prose: float):
    return lambda operations, documentation: JudgeVerdict(consistency, prose)


def test_weights_match_the_spec() -> None:
    assert WEIGHTS == {
        "coverage": 0.25,
        "fidelity": 0.25,
        "consistency": 0.15,
        "examples": 0.15,
        "prose": 0.20,
    }
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_invalid_output_scores_zero_regardless_of_judge() -> None:
    score = score_enrichment(
        operations=OPS, result={"operations": "nope"}, judge=fixed_judge(1, 1)
    )

    assert score.valid is False
    assert score.total == 0.0


def test_perfect_output_scores_one() -> None:
    result = BatchEnrichment(
        operations=[
            docs(
                "GET /pets/{id}",
                params={"GET /pets/{id}#id": "The pet ID."},
                examples=[
                    Example(
                        title="t",
                        language="curl",
                        code="curl https://api.test/v2/pets/42",
                    )
                ],
            ),
            docs(
                "POST /pets",
                examples=[Example(title="t", language="json", code='{"name": "Max"}')],
            ),
        ]
    )

    score = score_enrichment(operations=OPS, result=result, judge=fixed_judge(1.0, 1.0))

    assert score.total == 1.0


def test_coverage_is_the_share_of_documented_operations() -> None:
    assert coverage(OPS, [docs("POST /pets")]) == 0.5
    assert coverage(OPS, []) == 0.0


def test_fidelity_penalizes_invented_operations_and_params() -> None:
    entries = [
        docs("GET /pets/{id}", params={"GET /pets/{id}#id": "ok"}),
        docs("GET /pets/{id}", params={"GET /pets/{id}#invented": "no"}),
        docs("DELETE /everything"),
        docs("POST /pets"),
    ]

    assert fidelity(OPS, entries) == 0.5


@pytest.mark.parametrize(
    ("example", "valid"),
    [
        (Example(title="", language="json", code='{"a": 1}'), 1.0),
        (Example(title="", language="json", code="{a: 1}"), 0.0),
        (Example(title="", language="python", code="client.get('x')"), 1.0),
        (Example(title="", language="python", code="def (:"), 0.0),
        (
            Example(
                title="", language="curl", code="curl -X POST https://api.test/pets"
            ),
            1.0,
        ),
        (Example(title="", language="curl", code="curl https://api.test/owners"), 0.0),
        (Example(title="", language="curl", code="echo no url"), 0.0),
    ],
)
def test_example_validity_checks_each_language(example: Example, valid: float) -> None:
    assert example_validity(OPS, [docs("POST /pets", examples=[example])]) == valid


def test_example_validity_ignores_unknown_languages_and_needs_examples() -> None:
    ruby = Example(title="", language="ruby", code="puts 1")

    assert example_validity(OPS, [docs("POST /pets", examples=[ruby])]) == 0.0
    assert example_validity(OPS, [docs("POST /pets")]) == 0.0


def test_metric_returns_pass_fail_while_bootstrapping() -> None:
    import dspy

    metric = make_enrich_metric(fixed_judge(1.0, 1.0))
    example = dspy.Example(operations=OPS).with_inputs("operations")
    good = dspy.Prediction(
        result=BatchEnrichment(operations=[docs("GET /pets/{id}"), docs("POST /pets")])
    )
    bad = dspy.Prediction(result={"broken": True})

    assert metric(example, good) == pytest.approx(0.85)
    assert metric(example, good, trace=[]) is True
    assert metric(example, bad, trace=[]) is False


def test_llm_judge_normalizes_scores() -> None:
    lm = DummyLM(
        [
            {"consistency": 1.7, "prose_quality": 5},
            {"consistency": 0.5, "prose_quality": 1},
        ]
    )
    judge = llm_judge(lm)
    documentation = BatchEnrichment(operations=[docs("POST /pets")])

    assert judge(OPS, documentation) == JudgeVerdict(consistency=1.0, prose=1.0)
    assert judge(OPS, documentation) == JudgeVerdict(consistency=0.5, prose=0.0)


def test_extraction_metric_is_f1_over_operation_ids() -> None:
    reference = ApiSurface(title="A", language="x", operations=OPS)
    partial = ApiSurface(title="A", language="x", operations=OPS[:1])

    assert score_extraction(reference=reference, predicted=reference) == 1.0
    assert score_extraction(reference=reference, predicted=partial) == pytest.approx(
        2 / 3, abs=1e-6
    )
    assert score_extraction(reference=reference, predicted={"bad": 1}) == 0.0
