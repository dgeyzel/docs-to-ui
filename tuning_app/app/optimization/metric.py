"""The DSPy objective: the configured eval metric on production-path pages. Plain-free.

A prediction's `GeneratedPage` is converted with `d2u.generation`'s own
conversion (IDs derived in code), judged, and scored with the same code as
eval runs, so the optimizer optimizes exactly what evals report.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import dspy
from d2u.generation.convert import generated_to_docpage
from d2u.generation.exceptions import GenerationError
from d2u.schemas.docpage import ApiSurface, DocPage
from d2u.schemas.generated import GeneratedPage
from d2u.schemas.judging import JudgeVerdict
from pydantic import ValidationError

from app.evals.metrics.scoring import Weights, score_example

logger = logging.getLogger(__name__)

Judge = Callable[[dict[str, str], DocPage], JudgeVerdict]


@dataclass(frozen=True, slots=True)
class GoldCase:
    """What the metric needs about one training example."""

    files: dict[str, str]
    expected: DocPage
    parser: ApiSurface | None


def make_metric(
    *,
    cases: dict[str, GoldCase],
    language: str,
    judge: Judge | None,
    weights: Weights,
    threshold: float,
) -> Callable[..., float | bool]:
    """A DSPy metric: the weighted total, or pass/fail while bootstrapping.

    `cases` maps each example's formatted source to its gold case.
    """

    def metric(
        example: dspy.Example, prediction: Any, trace: Any = None
    ) -> float | bool:
        # Any: DSPy passes predictions and traces of its own internal types.
        case = cases.get(example.source)
        total = 0.0
        if case is not None:
            total = score_prediction(
                prediction, case, language=language, judge=judge, weights=weights
            )
        if trace is not None:
            return total >= threshold
        return total

    return metric


def score_prediction(
    prediction: Any,
    case: GoldCase,
    *,
    language: str,
    judge: Judge | None,
    weights: Weights,
) -> float:
    """The eval total of one prediction; 0 when it isn't a valid page."""
    # Any: a dspy.Prediction, whose fields are dynamic.
    try:
        generated = prediction.page
        if not isinstance(generated, GeneratedPage):
            generated = GeneratedPage.model_validate(generated)
    except AttributeError, ValidationError:
        return 0.0
    line_counts = {path: text.count("\n") + 1 for path, text in case.files.items()}
    page, _ = generated_to_docpage(
        generated, language=language, line_counts=line_counts
    )
    verdict = None
    if judge is not None:
        try:
            verdict = judge(case.files, page)
        except GenerationError:
            logger.info("The judge failed during optimization", exc_info=True)
    score = score_example(
        output=page,
        gold=case.expected,
        parser=case.parser,
        verdict=verdict,
        weights=weights,
    )
    return score.total
