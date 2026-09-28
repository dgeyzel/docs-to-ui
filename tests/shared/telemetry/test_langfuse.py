import base64
from typing import Any, ClassVar

import pytest
from d2u.telemetry.backends import langfuse as langfuse_backend
from d2u.telemetry.backends.langfuse import LangfuseBackend
from d2u.telemetry.config import build_available_backends
from d2u.telemetry.events import FeedbackEvent
from d2u.telemetry.otlp import langfuse_auth_header, langfuse_traces_endpoint

from tests.helpers import use_trace_backends

TRACE_ID = "a" * 32


def make_backend() -> LangfuseBackend:
    return LangfuseBackend(
        base_url="https://langfuse.example/",
        public_key="pk-lf-1",
        secret_key="sk-lf-1",
        project_id="proj-1",
    )


class FakeLangfuse:
    instances: ClassVar[list[FakeLangfuse]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.scores: list[dict[str, Any]] = []
        self.flushed = False
        self.closed = False
        FakeLangfuse.instances.append(self)

    def create_score(self, **kwargs: Any) -> None:
        self.scores.append(kwargs)

    def flush(self) -> None:
        self.flushed = True

    def shutdown(self) -> None:
        self.closed = True


def test_otlp_endpoint_and_basic_auth() -> None:
    header = langfuse_auth_header(public_key="pk", secret_key="sk")

    assert langfuse_traces_endpoint("https://lf.example/") == (
        "https://lf.example/api/public/otel/v1/traces"
    )
    assert header == {"Authorization": "Basic " + base64.b64encode(b"pk:sk").decode()}


def test_trace_url_points_at_the_langfuse_project() -> None:
    assert make_backend().trace_url(TRACE_ID) == (
        f"https://langfuse.example/project/proj-1/traces/{TRACE_ID}"
    )


def test_span_processor_is_a_batch_processor() -> None:
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    processor = make_backend().span_processor()

    assert isinstance(processor, BatchSpanProcessor)
    processor.shutdown()


def test_delivering_feedback_creates_a_score(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeLangfuse.instances.clear()
    monkeypatch.setattr(langfuse_backend, "Langfuse", FakeLangfuse)

    make_backend().deliver_feedback(
        TRACE_ID,
        FeedbackEvent(
            generation_id=3, operation_id="GET /pets", score=-1, comment="Wrong."
        ),
    )

    (client,) = FakeLangfuse.instances
    assert client.kwargs["public_key"] == "pk-lf-1"
    assert client.kwargs["base_url"] == "https://langfuse.example"
    assert client.kwargs["tracer_provider"] is not None
    assert client.scores == [
        {
            "name": "user_feedback",
            "value": -1.0,
            "data_type": "NUMERIC",
            "trace_id": TRACE_ID,
            "comment": "Wrong.",
            "metadata": {"generation_id": 3, "operation_id": "GET /pets"},
        }
    ]
    assert client.flushed
    assert client.closed


def test_langfuse_client_never_attaches_to_the_app_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentelemetry import trace

    FakeLangfuse.instances.clear()
    monkeypatch.setattr(langfuse_backend, "Langfuse", FakeLangfuse)

    make_backend().deliver_feedback(
        TRACE_ID, FeedbackEvent(generation_id=1, operation_id=None, score=1, comment="")
    )

    assert (
        FakeLangfuse.instances[0].kwargs["tracer_provider"]
        is not trace.get_tracer_provider()
    )


def test_record_feedback_never_raises_when_queueing_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from d2u.telemetry import jobs

    def broken(self: object, **kwargs: object) -> None:
        raise RuntimeError("queue down")

    monkeypatch.setattr(jobs.MirrorFeedbackJob, "run_in_worker", broken)

    make_backend().record_feedback(
        TRACE_ID, FeedbackEvent(generation_id=1, operation_id=None, score=1, comment="")
    )


def test_langfuse_is_unavailable_while_any_setting_is_missing(settings) -> None:
    settings.TELEMETRY_LANGFUSE_BASE_URL = "https://lf.example"
    settings.TELEMETRY_LANGFUSE_PUBLIC_KEY = ""
    settings.TELEMETRY_LANGFUSE_SECRET_KEY = ""
    settings.TELEMETRY_LANGFUSE_PROJECT_ID = "p"

    backends = build_available_backends()

    assert [backend.name for backend in backends] == ["native"]


def test_both_backends_are_available_when_langfuse_is_configured(settings) -> None:
    settings.TELEMETRY_LANGFUSE_BASE_URL = "https://lf.example"
    settings.TELEMETRY_LANGFUSE_PUBLIC_KEY = "pk"
    settings.TELEMETRY_LANGFUSE_SECRET_KEY = "sk"
    settings.TELEMETRY_LANGFUSE_PROJECT_ID = "p"

    backends = build_available_backends()

    assert [backend.name for backend in backends] == ["native", "langfuse"]


def test_trace_url_prefers_the_first_backend_with_a_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from d2u.telemetry.api import trace_url

    use_trace_backends(monkeypatch, [make_backend()])

    assert (
        trace_url(TRACE_ID)
        == f"https://langfuse.example/project/proj-1/traces/{TRACE_ID}"
    )
