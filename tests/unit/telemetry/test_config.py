import pytest

from app.telemetry.api import trace_url
from app.telemetry.config import active_backends, build_backends, is_docs_baggage_key
from app.telemetry.exceptions import TelemetryConfigurationError


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


def test_build_backends_creates_the_native_backend() -> None:
    (backend,) = build_backends(["native"])

    assert backend.name == "native"
    assert backend.trace_url("a" * 32) == "/traces/" + "a" * 32


def test_build_backends_rejects_unknown_names() -> None:
    with pytest.raises(TelemetryConfigurationError, match="Unknown telemetry backend"):
        build_backends(["zipkin"])


def test_tests_run_without_active_backends() -> None:
    assert active_backends() == []
    assert trace_url("a" * 32) is None
