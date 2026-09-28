"""Telemetry payloads shared by business code and trace backends."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class FeedbackEvent(BaseModel):
    """A user's 👍 / 👎 on a page or one operation, with an optional comment."""

    model_config = ConfigDict(frozen=True)

    generation_id: int
    operation_id: str | None
    score: Literal[1, -1]
    comment: str
