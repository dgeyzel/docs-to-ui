"""Recording a 👍 / 👎, from the page or from the API."""

from typing import Literal

from d2u.generations.models import Feedback, Generation
from d2u.schemas.docpage import DocPage
from d2u.telemetry.api import record_feedback
from d2u.telemetry.events import FeedbackEvent


def is_known_operation(page: DocPage, operation_id: str | None) -> bool:
    """Whether feedback may target this operation (None means the whole page)."""
    if operation_id is None:
        return True
    return operation_id in {op.id for op in page.surface.operations}


def submit_feedback(
    generation: Generation,
    *,
    operation_id: str | None,
    score: Literal[1, -1],
    comment: str,
) -> Feedback:
    """Save feedback on a generation and mirror it to the selected backends.

    Callers check the operation with `is_known_operation` first.
    """
    return record_feedback(
        generation,
        FeedbackEvent(
            generation_id=generation.id,
            operation_id=operation_id,
            score=score,
            comment=comment.strip(),
        ),
    )
