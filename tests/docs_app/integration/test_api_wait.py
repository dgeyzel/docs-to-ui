import pytest
from d2u.generations.models import Generation, InputOrigin

from app.api.waiting import POLL_INTERVAL_S, wait_for_finish
from app.generate.jobs import GenerateDocJob
from app.generate.pipeline import SubmittedInput, create_generation
from tests.helpers import read_fixture

pytestmark = pytest.mark.usefixtures("db")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.pauses: list[float] = []

    def __call__(self) -> float:
        return self.now

    def pause(self, seconds: float) -> None:
        self.pauses.append(seconds)
        self.now += seconds


def pending_generation() -> Generation:
    text = read_fixture("openapi/petstore-3.0.yaml").encode("utf-8")
    return create_generation(
        SubmittedInput(
            origin=InputOrigin.PASTE, filename="", data=text, language="openapi"
        )
    )


def test_wait_sees_the_worker_finish_the_generation() -> None:
    generation = pending_generation()
    clock = FakeClock()

    def pause_while_the_worker_runs(seconds: float) -> None:
        clock.pause(seconds)
        GenerateDocJob(generation.id).run()

    finished = wait_for_finish(
        generation, timeout_s=10, clock=clock, pause=pause_while_the_worker_runs
    )

    assert finished.status == "succeeded"
    assert clock.pauses == [POLL_INTERVAL_S]


def test_wait_gives_up_at_the_timeout() -> None:
    generation = pending_generation()
    clock = FakeClock()

    still_pending = wait_for_finish(
        generation, timeout_s=1.2, clock=clock, pause=clock.pause
    )

    assert still_pending.status == "pending"
    assert sum(clock.pauses) == pytest.approx(1.2)
    assert max(clock.pauses) <= POLL_INTERVAL_S
