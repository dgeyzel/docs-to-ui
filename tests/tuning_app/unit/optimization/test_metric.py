import dspy
from d2u.generation.convert import generated_to_docpage
from d2u.schemas.generated import GeneratedOperation, GeneratedPage
from d2u.schemas.judging import JudgeVerdict

from app.evals.metrics.scoring import Weights
from app.optimization.metric import GoldCase, make_metric, score_prediction

OP = GeneratedOperation(
    kind="http",
    method="GET",
    path="/pets",
    signature="GET /pets",
    group="Pets",
    summary="List",
)
PAGE = GeneratedPage(title="API", overview_md="", operations=[OP])
GOLD, _ = generated_to_docpage(PAGE, language="openapi", line_counts={})
CASE = GoldCase(files={"api.yaml": "x"}, expected=GOLD, parser=None)


def judge(files: dict[str, str], page: object) -> JudgeVerdict:
    return JudgeVerdict(claims=[], prose_quality=5)


def test_a_matching_prediction_scores_like_an_eval() -> None:
    total = score_prediction(
        dspy.Prediction(page=PAGE),
        CASE,
        language="openapi",
        judge=judge,
        weights=Weights(),
    )

    # Everything but example validity (no examples): 0.9 with the default weights.
    assert round(total, 6) == 0.9


def test_a_prediction_that_is_not_a_page_scores_zero() -> None:
    assert (
        score_prediction(
            dspy.Prediction(page={"title": 1}),
            CASE,
            language="openapi",
            judge=None,
            weights=Weights(),
        )
        == 0.0
    )


def test_the_metric_is_pass_fail_while_bootstrapping() -> None:
    metric = make_metric(
        cases={"src": CASE},
        language="openapi",
        judge=judge,
        weights=Weights(),
        threshold=0.95,
    )
    example = dspy.Example(source="src").with_inputs("source")
    prediction = dspy.Prediction(page=PAGE)

    assert round(metric(example, prediction), 6) == 0.9
    assert metric(example, prediction, trace=[]) is False
    assert metric(dspy.Example(source="unknown"), prediction) == 0.0
