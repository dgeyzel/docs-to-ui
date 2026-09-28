"""The `ExtractApiSurface` metric. Unused in v1, where every language has a parser."""

from typing import Any

import pydantic
from d2u.schemas.docpage import ApiSurface


def score_extraction(*, reference: ApiSurface, predicted: Any) -> float:
    """F1 of operation IDs between the prediction and the reference; 0 if invalid."""
    try:
        surface = (
            predicted
            if isinstance(predicted, ApiSurface)
            else ApiSurface.model_validate(predicted)
        )
    except pydantic.ValidationError:
        return 0.0
    expected = {op.id for op in reference.operations}
    found = {op.id for op in surface.operations}
    if not expected or not found:
        return 0.0
    true_positives = len(expected & found)
    if true_positives == 0:
        return 0.0
    precision = true_positives / len(found)
    recall = true_positives / len(expected)
    return round(2 * precision * recall / (precision + recall), 6)
