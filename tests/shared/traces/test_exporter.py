from collections.abc import Callable

from d2u.traces.exporter import (
    COLUMNS,
    TRUNCATION_MARKER,
    PostgresSpanExporter,
    insert_statement,
    span_to_row,
    truncate_value,
)
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode


def finished_spans(build: Callable[[trace.Tracer], None]) -> list[ReadableSpan]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    build(provider.get_tracer("test"))
    return list(exporter.get_finished_spans())


def test_span_to_row_maps_identity_timing_and_status() -> None:
    def build(tracer: trace.Tracer) -> None:
        with (
            tracer.start_as_current_span("parent", kind=trace.SpanKind.SERVER),
            tracer.start_as_current_span("child") as child,
        ):
            child.set_attribute("docs.generation_id", "42")
            child.set_attribute("openinference.span.kind", "LLM")
            child.add_event("merge.unknown_operation_ids", {"docs.ids": ["X"]})
            child.set_status(StatusCode.ERROR, "boom")

    child, parent = finished_spans(build)
    row = span_to_row(child, max_attribute_bytes=1000)
    parent_row = span_to_row(parent, max_attribute_bytes=1000)

    assert len(row.trace_id) == 32
    assert len(row.span_id) == 16
    assert row.trace_id == parent_row.trace_id
    assert row.parent_span_id == parent_row.span_id
    assert parent_row.parent_span_id == ""
    assert parent_row.kind == "SERVER"
    assert row.name == "child"
    assert row.status_code == "ERROR"
    assert row.status_message == "boom"
    assert row.generation_id == 42
    assert row.is_llm is True
    assert row.duration_ms >= 0
    assert row.start_time <= row.end_time
    assert row.events[0]["name"] == "merge.unknown_operation_ids"
    assert row.events[0]["attributes"] == {"docs.ids": ["X"]}
    assert len(row.values()) == len(COLUMNS)


def test_span_to_row_truncates_long_attribute_values() -> None:
    def build(tracer: trace.Tracer) -> None:
        with tracer.start_as_current_span("big") as span:
            span.set_attribute("prompt", "é" * 100)
            span.set_attribute("parts", ["x" * 50, "short"])

    (span,) = finished_spans(build)
    row = span_to_row(span, max_attribute_bytes=20)

    assert row.attributes["prompt"] == "é" * 10 + TRUNCATION_MARKER
    assert row.attributes["parts"] == ["x" * 20 + TRUNCATION_MARKER, "short"]


def test_truncate_value_leaves_short_and_non_string_values_alone() -> None:
    assert truncate_value("short", 10) == "short"
    assert truncate_value(12345, 1) == 12345
    assert truncate_value(True, 1) is True


def test_insert_statement_has_one_placeholder_per_value() -> None:
    statement = insert_statement(3).as_string(None)

    assert statement.count("%s") == 3 * len(COLUMNS)
    assert statement.startswith('INSERT INTO "traces_tracespan"')
    assert statement.endswith("ON CONFLICT (trace_id, span_id) DO NOTHING")


def test_export_never_raises_when_the_database_is_unreachable() -> None:
    def build(tracer: trace.Tracer) -> None:
        with tracer.start_as_current_span("span"):
            pass

    exporter = PostgresSpanExporter(
        database_url="postgresql://nobody@127.0.0.1:1/missing?connect_timeout=1",
        max_attribute_bytes=100,
    )

    result = exporter.export(finished_spans(build))

    assert result.name == "FAILURE"
    exporter.shutdown()
