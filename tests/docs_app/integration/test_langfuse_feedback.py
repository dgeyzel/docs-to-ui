from typing import Any, ClassVar

import pytest
from d2u.generations.models import Feedback, Generation
from d2u.telemetry.backends import langfuse as langfuse_backend
from d2u.telemetry.backends.langfuse import LangfuseBackend
from d2u.telemetry.jobs import MirrorFeedbackJob
from plain.jobs.models import JobRequest
from plain.test import Client

from app.generate.jobs import GenerateDocJob
from tests.helpers import read_fixture, use_trace_backends

pytestmark = pytest.mark.usefixtures("db")


class FakeLangfuse:
    scores: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        pass

    def create_score(self, **kwargs: Any) -> None:
        FakeLangfuse.scores.append(kwargs)

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def test_feedback_is_saved_then_mirrored_to_langfuse_by_a_job(monkeypatch) -> None:
    backend = LangfuseBackend(
        base_url="https://lf.example", public_key="pk", secret_key="sk", project_id="p"
    )
    use_trace_backends(monkeypatch, [backend])
    monkeypatch.setattr(langfuse_backend, "Langfuse", FakeLangfuse)
    FakeLangfuse.scores.clear()
    Client().post(
        "/generations",
        data={"text": read_fixture("openapi/petstore-3.0.yaml"), "language": ""},
    )
    generation = Generation.query.order_by("-id").first()
    assert generation is not None
    GenerateDocJob(generation.id).run()

    Client().post(
        f"/generations/{generation.id}/feedback",
        data={
            "operation_id": "GET /pets",
            "score": "-1",
            "comment": "Wrong.",
            "anchor": "",
        },
    )

    assert Feedback.query.count() == 1
    request = JobRequest.query.get(job_class="d2u.telemetry.jobs.MirrorFeedbackJob")
    assert FakeLangfuse.scores == []
    assert request.parameters is not None
    MirrorFeedbackJob(**request.parameters["kwargs"]).run()
    assert FakeLangfuse.scores[0]["trace_id"] == generation.trace_id
    assert FakeLangfuse.scores[0]["value"] == -1.0
    assert FakeLangfuse.scores[0]["comment"] == "Wrong."


def test_generation_page_links_to_langfuse_when_it_is_the_backend(monkeypatch) -> None:
    backend = LangfuseBackend(
        base_url="https://lf.example", public_key="pk", secret_key="sk", project_id="p"
    )
    use_trace_backends(monkeypatch, [backend])
    Client().post(
        "/generations",
        data={"text": read_fixture("openapi/petstore-3.0.yaml"), "language": ""},
    )
    generation = Generation.query.order_by("-id").first()
    assert generation is not None

    html = Client().get(f"/generations/{generation.id}").content.decode()

    assert f'href="https://lf.example/project/p/traces/{generation.trace_id}"' in html
