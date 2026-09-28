import pytest
from d2u.telemetry.api import deliver_feedback, trace_url
from d2u.telemetry.backends.native import NativeBackend
from d2u.telemetry.config import (
    available_backends,
    backend_options,
    build_available_backends,
    is_docs_baggage_key,
    langfuse_missing_variables,
    normalize_selection,
    selected_backends,
    selection_summary,
)
from d2u.telemetry.events import FeedbackEvent
from opentelemetry.sdk.trace import SpanProcessor

from tests.helpers import use_trace_backends

TRACE_ID = "a" * 32
FEEDBACK = FeedbackEvent(generation_id=1, operation_id=None, score=1, comment="")


class StubBackend:
    """A backend with a viewer URL that records delivered feedback."""

    def __init__(self, name: str, url: str | None = None) -> None:
        self.name = name
        self._url = url
        self.delivered: list[str] = []

    def span_processor(self) -> SpanProcessor:
        return SpanProcessor()

    def trace_url(self, trace_id: str) -> str | None:
        return self._url

    def record_feedback(self, trace_id: str, feedback: FeedbackEvent) -> None:
        pass

    def deliver_feedback(self, trace_id: str, feedback: FeedbackEvent) -> None:
        self.delivered.append(trace_id)

    def shutdown(self) -> None:
        pass


@pytest.fixture
def no_langfuse(settings) -> None:
    settings.TELEMETRY_LANGFUSE_BASE_URL = ""
    settings.TELEMETRY_LANGFUSE_PUBLIC_KEY = ""
    settings.TELEMETRY_LANGFUSE_SECRET_KEY = ""
    settings.TELEMETRY_LANGFUSE_PROJECT_ID = ""


@pytest.mark.parametrize(
    ("key", "copied"),
    [
        ("docs.generation_id", True),
        ("docs.program_version", True),
        ("user.email", False),
        ("docsgeneration", False),
    ],
)
def test_only_docs_baggage_is_copied_to_spans(key: str, copied: bool) -> None:
    assert is_docs_baggage_key(key) is copied


@pytest.mark.usefixtures("no_langfuse")
def test_native_is_always_available() -> None:
    (backend,) = build_available_backends()

    assert isinstance(backend, NativeBackend)
    assert backend.trace_url(TRACE_ID) == "/traces/" + TRACE_ID


def test_missing_langfuse_variables_are_named_in_order(settings) -> None:
    settings.TELEMETRY_LANGFUSE_BASE_URL = ""
    settings.TELEMETRY_LANGFUSE_PUBLIC_KEY = "pk"
    settings.TELEMETRY_LANGFUSE_SECRET_KEY = ""
    settings.TELEMETRY_LANGFUSE_PROJECT_ID = "p"

    assert langfuse_missing_variables() == ["LANGFUSE_BASE_URL", "LANGFUSE_SECRET_KEY"]


@pytest.mark.usefixtures("no_langfuse")
def test_backend_options_mark_langfuse_unavailable_without_credentials() -> None:
    native, langfuse = backend_options()

    assert (native.name, native.available, native.missing) == ("native", True, ())
    assert langfuse.name == "langfuse"
    assert not langfuse.available
    assert langfuse.missing == (
        "LANGFUSE_BASE_URL",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_PROJECT_ID",
    )


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (["langfuse", "native"], ["native", "langfuse"]),
        (["native", "native"], ["native"]),
        (["zipkin", "langfuse"], ["langfuse"]),
        ([], []),
    ],
)
def test_selections_keep_known_backends_in_a_stable_order(
    names: list[str], expected: list[str]
) -> None:
    assert normalize_selection(names) == expected


@pytest.mark.usefixtures("no_langfuse")
@pytest.mark.parametrize(
    ("names", "summary"),
    [
        (["native"], "Native"),
        ([], "none"),
        (["langfuse", "native"], "Native, Langfuse (not configured in this app)"),
    ],
)
def test_selection_summary_describes_the_choice(names: list[str], summary: str) -> None:
    assert selection_summary(names) == summary


def test_tests_run_with_trace_export_disabled() -> None:
    assert available_backends() == []
    assert selected_backends() == []
    assert trace_url(TRACE_ID) is None


def test_only_selected_backends_are_used(monkeypatch: pytest.MonkeyPatch) -> None:
    native = StubBackend("native", url="/traces/x")
    langfuse = StubBackend("langfuse", url="https://lf.example/x")
    use_trace_backends(monkeypatch, [native, langfuse], selected={"langfuse", "gone"})

    assert selected_backends() == [langfuse]
    assert trace_url(TRACE_ID) == "https://lf.example/x"


def test_queued_feedback_reaches_a_backend_deselected_since(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    langfuse = StubBackend("langfuse")
    use_trace_backends(monkeypatch, [langfuse], selected=set())

    deliver_feedback(backend_name="langfuse", trace_id=TRACE_ID, event=FEEDBACK)

    assert langfuse.delivered == [TRACE_ID]
