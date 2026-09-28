import pytest
from d2u.generations.models import Feedback, Generation
from d2u.telemetry import config as telemetry_config
from d2u.telemetry.events import FeedbackEvent
from plain.test import Client

from app.generate.jobs import GenerateDocJob
from tests.helpers import read_fixture

pytestmark = pytest.mark.usefixtures("db")


def succeeded_generation() -> Generation:
    Client().post(
        "/generations",
        data={"text": read_fixture("openapi/petstore-3.0.yaml"), "language": ""},
    )
    generation = Generation.query.order_by("-id").first()
    assert generation is not None
    GenerateDocJob(generation.id).run()
    return Generation.query.get(generation.id)


def post_feedback(generation: Generation, **fields: str):
    data = {"operation_id": "", "score": "1", "comment": "", "anchor": ""} | fields
    return Client().post(f"/generations/{generation.id}/feedback", data=data)


class RecordingBackend:
    name = "recording"

    def __init__(self) -> None:
        self.calls: list[tuple[str, FeedbackEvent]] = []

    def record_feedback(self, trace_id: str, feedback: FeedbackEvent) -> None:
        self.calls.append((trace_id, feedback))

    def trace_url(self, trace_id: str) -> str | None:
        return None


def test_page_feedback_is_saved_and_shown() -> None:
    generation = succeeded_generation()

    response = post_feedback(generation, score="1", anchor="page")

    assert response.status_code == 302
    assert response.headers["Location"] == f"/generations/{generation.id}#feedback-page"
    feedback = Feedback.query.get(Feedback.generation.id.equals(generation.id))
    assert (feedback.operation_id, feedback.score, feedback.comment) == ("", 1, "")
    assert feedback.trace_id == generation.trace_id
    html = Client().get(f"/generations/{generation.id}").content.decode()
    assert "Thanks! You rated this helpful." in html


def test_operation_feedback_keeps_the_correction_comment() -> None:
    generation = succeeded_generation()

    post_feedback(
        generation,
        operation_id="GET /pets",
        score="-1",
        comment="  The limit maximum is 100, not unlimited.  ",
        anchor="op-get-pets",
    )

    feedback = Feedback.query.get(Feedback.generation.id.equals(generation.id))
    assert feedback.operation_id == "GET /pets"
    assert feedback.score == -1
    assert feedback.comment == "The limit maximum is 100, not unlimited."
    html = Client().get(f"/generations/{generation.id}").content.decode()
    assert "You rated this not helpful." in html


def test_the_latest_feedback_wins_on_the_page() -> None:
    generation = succeeded_generation()

    post_feedback(generation, score="1")
    post_feedback(generation, score="-1")

    assert Feedback.query.count() == 2
    html = Client().get(f"/generations/{generation.id}").content.decode()
    assert "You rated this not helpful." in html


def test_feedback_for_unknown_operations_is_rejected() -> None:
    generation = succeeded_generation()

    response = post_feedback(generation, operation_id="GET /nope")

    assert response.status_code == 404
    assert Feedback.query.count() == 0


@pytest.mark.parametrize("score", ["0", "2", "up"])
def test_feedback_scores_must_be_plus_or_minus_one(score: str) -> None:
    generation = succeeded_generation()

    response = post_feedback(generation, score=score)

    assert response.status_code == 400
    assert Feedback.query.count() == 0


def test_unsafe_anchors_are_dropped_from_the_redirect() -> None:
    generation = succeeded_generation()

    response = post_feedback(generation, anchor='x"><script>')

    assert response.headers["Location"] == f"/generations/{generation.id}"


def test_feedback_is_mirrored_to_active_backends(monkeypatch) -> None:
    generation = succeeded_generation()
    backend = RecordingBackend()
    monkeypatch.setattr(telemetry_config, "_active_backends", [backend])

    post_feedback(generation, operation_id="GET /pets", score="-1", comment="Wrong.")

    assert backend.calls == [
        (
            generation.trace_id,
            FeedbackEvent(
                generation_id=generation.id,
                operation_id="GET /pets",
                score=-1,
                comment="Wrong.",
            ),
        )
    ]


def test_feedback_buttons_appear_in_the_app_but_not_in_exports() -> None:
    generation = succeeded_generation()

    page = Client().get(f"/generations/{generation.id}").content.decode()
    export = Client().get(f"/generations/{generation.id}/export.html").content.decode()

    assert 'id="feedback-op-get-pets"' in page
    assert 'id="feedback-page"' in page
    assert "feedback" not in export.split("<style>")[0] + export.split("</style>")[-1]
