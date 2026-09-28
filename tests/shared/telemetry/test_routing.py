import logging

import pytest
from d2u.telemetry.routing import RoutingSpanProcessor, SelectionCache
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class RecordingProcessor(SpanProcessor):
    def __init__(self) -> None:
        self.ended: list[str] = []
        self.shut_down = False
        self.flushed = False

    def on_end(self, span: ReadableSpan) -> None:
        self.ended.append(span.name)

    def shutdown(self) -> None:
        self.shut_down = True

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        self.flushed = True
        return True


class BrokenProcessor(SpanProcessor):
    def on_end(self, span: ReadableSpan) -> None:
        raise RuntimeError("exporter down")


def finish_span(processor: SpanProcessor, name: str) -> None:
    provider = TracerProvider()
    provider.add_span_processor(processor)
    with provider.get_tracer("test").start_as_current_span(name):
        pass


def test_spans_reach_only_the_selected_backends() -> None:
    native, langfuse = RecordingProcessor(), RecordingProcessor()
    router = RoutingSpanProcessor(
        {"native": native, "langfuse": langfuse}, lambda: frozenset({"langfuse"})
    )

    finish_span(router, "request")

    assert native.ended == []
    assert langfuse.ended == ["request"]


def test_an_empty_selection_sends_spans_nowhere() -> None:
    native = RecordingProcessor()
    router = RoutingSpanProcessor({"native": native}, frozenset)

    finish_span(router, "request")

    assert native.ended == []


def test_selected_backends_that_are_unavailable_are_ignored() -> None:
    native = RecordingProcessor()
    router = RoutingSpanProcessor(
        {"native": native}, lambda: frozenset({"native", "langfuse"})
    )

    finish_span(router, "request")

    assert native.ended == ["request"]


def test_a_changed_selection_applies_to_the_next_span() -> None:
    native, langfuse = RecordingProcessor(), RecordingProcessor()
    selection = {"current": frozenset({"native"})}
    router = RoutingSpanProcessor(
        {"native": native, "langfuse": langfuse}, lambda: selection["current"]
    )

    finish_span(router, "first")
    selection["current"] = frozenset({"langfuse"})
    finish_span(router, "second")

    assert native.ended == ["first"]
    assert langfuse.ended == ["second"]


def test_a_failing_backend_does_not_stop_the_others() -> None:
    langfuse = RecordingProcessor()
    router = RoutingSpanProcessor(
        {"native": BrokenProcessor(), "langfuse": langfuse},
        lambda: frozenset({"native", "langfuse"}),
    )

    finish_span(router, "request")

    assert langfuse.ended == ["request"]


def test_a_failing_selection_drops_the_span_without_raising() -> None:
    native = RecordingProcessor()

    def broken() -> frozenset[str]:
        raise RuntimeError("no database")

    router = RoutingSpanProcessor({"native": native}, broken)

    finish_span(router, "request")

    assert native.ended == []


def test_shutdown_and_flush_reach_every_backend_selected_or_not() -> None:
    native, langfuse = RecordingProcessor(), RecordingProcessor()
    router = RoutingSpanProcessor(
        {"native": native, "langfuse": langfuse}, lambda: frozenset({"native"})
    )

    assert router.force_flush() is True
    router.shutdown()

    assert [native.flushed, langfuse.flushed] == [True, True]
    assert [native.shut_down, langfuse.shut_down] == [True, True]


def test_routed_spans_reach_a_real_exporter_intact() -> None:
    exporter = InMemorySpanExporter()
    router = RoutingSpanProcessor(
        {"native": SimpleSpanProcessor(exporter)}, lambda: frozenset({"native"})
    )

    finish_span(router, "generate")

    assert [span.name for span in exporter.get_finished_spans()] == ["generate"]


def test_selection_is_reloaded_only_after_the_ttl() -> None:
    clock = FakeClock()
    loads: list[frozenset[str]] = [frozenset({"native"}), frozenset({"langfuse"})]
    cache = SelectionCache(lambda: loads.pop(0), ttl_s=10, clock=clock)

    assert cache.current() == {"native"}
    clock.now = 9.9
    assert cache.current() == {"native"}
    clock.now = 10.0
    assert cache.current() == {"langfuse"}


def test_invalidating_reloads_the_selection_immediately() -> None:
    clock = FakeClock()
    loads = [frozenset({"native"}), frozenset()]
    cache = SelectionCache(lambda: loads.pop(0), ttl_s=10, clock=clock)
    cache.current()

    cache.invalidate()

    assert cache.current() == frozenset()


def test_a_failed_reload_keeps_the_previous_selection_until_the_next_ttl(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = FakeClock()
    calls = {"count": 0}

    def load() -> frozenset[str]:
        calls["count"] += 1
        if calls["count"] == 2:
            raise ConnectionError("database down")
        return frozenset({"native"} if calls["count"] == 1 else {"langfuse"})

    cache = SelectionCache(load, ttl_s=10, clock=clock)
    cache.current()
    clock.now = 10.0

    with caplog.at_level(logging.WARNING, logger="d2u.telemetry.routing"):
        assert cache.current() == {"native"}
    clock.now = 15.0
    assert cache.current() == {"native"}
    assert calls["count"] == 2
    clock.now = 20.0
    assert cache.current() == {"langfuse"}
    assert "Could not load the trace backend selection" in caplog.text


def test_selection_is_empty_until_the_first_successful_load() -> None:
    def load() -> frozenset[str]:
        raise ConnectionError("database down")

    assert SelectionCache(load, ttl_s=10, clock=FakeClock()).current() == frozenset()
