"""Blocking until a generation finishes, for the API's `wait` parameter."""

import time
from collections.abc import Callable

from d2u.generations.models import Generation, GenerationStatus
from plain.http import BadRequestError400
from plain.runtime import settings

POLL_INTERVAL_S = 0.5
FINISHED_STATUSES = (GenerationStatus.SUCCEEDED.value, GenerationStatus.FAILED.value)


def is_finished(generation: Generation) -> bool:
    """Whether the generation has succeeded or failed."""
    return generation.status in FINISHED_STATUSES


def parse_wait(raw: str | None) -> float:
    """Seconds to wait from a `wait` query value, capped by `API_MAX_WAIT_S`.

    Raises:
        BadRequestError400: The value isn't a whole number of seconds, or is negative.
    """
    if not raw:
        return 0
    try:
        seconds = int(raw)
    except ValueError as exc:
        raise BadRequestError400("wait must be a whole number of seconds.") from exc
    if seconds < 0:
        raise BadRequestError400("wait must not be negative.")
    return min(seconds, settings.API_MAX_WAIT_S)


def wait_for_finish(
    generation: Generation,
    *,
    timeout_s: float,
    clock: Callable[[], float] = time.monotonic,
    pause: Callable[[float], None] = time.sleep,
) -> Generation:
    """The generation once it has finished, or as it is when the time runs out.

    The row is read afresh on every check, outside any transaction, so the
    worker's updates are seen as soon as they commit.
    """
    deadline = clock() + timeout_s
    while not is_finished(generation):
        remaining = deadline - clock()
        if remaining <= 0:
            break
        pause(min(POLL_INTERVAL_S, remaining))
        generation = Generation.query.get(generation.id)
    return generation
