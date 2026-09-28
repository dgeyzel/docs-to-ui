from datetime import UTC, datetime, timedelta

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from plain.postgres import get_connection
from plain.postgres.database_url import build_database_url
from plain.test import Client

from app.generations.models import Generation
from app.telemetry.backends.native import NativeBackend
from app.traces.exporter import TRUNCATION_MARKER, PostgresSpanExporter
from app.traces.jobs import PruneTracesJob
from app.traces.models import TraceSpan

pytestmark = pytest.mark.usefixtures("isolated_db")


def database_url() -> str:
    return build_database_url(get_connection().settings_dict)


def record_generation_trace(generation_id: int) -> list:
    """Spans shaped like a real generation: request, job stage and an LLM call."""
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span(
        "POST /generations", kind=trace.SpanKind.SERVER
    ) as request:
        request.set_attribute("docs.generation_id", generation_id)
        with tracer.start_as_current_span("generate") as job:
            job.set_attribute("docs.generation_id", str(generation_id))
            with tracer.start_as_current_span("DummyLM.__call__") as llm:
                llm.set_attribute("openinference.span.kind", "LLM")
                llm.set_attribute("llm.model_name", "gemini/gemini-3.8-flash")
                llm.set_attribute("llm.input_messages.0.message.role", "user")
                llm.set_attribute(
                    "llm.input_messages.0.message.content", "Document GET /pets"
                )
                llm.set_attribute("llm.output_messages.0.message.role", "assistant")
                llm.set_attribute(
                    "llm.output_messages.0.message.content", "Lists pets."
                )
                llm.set_attribute("llm.token_count.total", 150)
                llm.set_attribute("llm.token_count.prompt", 120)
                llm.set_attribute("prompt.huge", "x" * 500)
            with tracer.start_as_current_span("extract") as failed:
                failed.set_status(trace.StatusCode.ERROR, "bad input")
    return list(memory.get_finished_spans())


def export(spans: list) -> None:
    exporter = PostgresSpanExporter(
        database_url=database_url(), max_attribute_bytes=100
    )
    assert exporter.export(spans).name == "SUCCESS"
    exporter.shutdown()


def first_trace_id() -> str:
    span = TraceSpan.query.first()
    assert span is not None
    return span.trace_id


def make_generation(trace_id: str = "") -> Generation:
    generation = Generation(
        input_origin="paste",
        input_blob=b"openapi: 3.0.0",
        input_sha256="0" * 64,
        input_bytes=14,
        status="succeeded",
        trace_id=trace_id,
    )
    generation.create()
    return generation


def test_exporter_writes_spans_with_generation_and_llm_flags() -> None:
    spans = record_generation_trace(7)

    export(spans)

    rows = {row.name: row for row in TraceSpan.query.all()}
    assert set(rows) == {"POST /generations", "generate", "DummyLM.__call__", "extract"}
    assert rows["generate"].generation_id == 7
    assert rows["POST /generations"].generation_id == 7
    assert rows["DummyLM.__call__"].is_llm is True
    assert rows["generate"].is_llm is False
    assert rows["extract"].status_code == "ERROR"
    assert (
        rows["DummyLM.__call__"].attributes["prompt.huge"]
        == "x" * 100 + TRUNCATION_MARKER
    )
    assert rows["generate"].parent_span_id == rows["POST /generations"].span_id


def test_exporting_the_same_spans_twice_does_not_duplicate_rows() -> None:
    spans = record_generation_trace(7)

    export(spans)
    export(spans)

    assert TraceSpan.query.count() == 4


def test_native_backend_processor_exports_on_flush() -> None:
    backend = NativeBackend(database_url=database_url(), max_attribute_bytes=1000)
    provider = TracerProvider()
    provider.add_span_processor(backend.span_processor())

    with provider.get_tracer("test").start_as_current_span("batched"):
        pass
    provider.force_flush()
    provider.shutdown()

    assert [row.name for row in TraceSpan.query.all()] == ["batched"]


def test_trace_list_shows_root_spans_and_filters() -> None:
    export(record_generation_trace(7))
    trace_id = first_trace_id()

    html = Client().get("/traces").content.decode()
    errors_only = Client().get("/traces?status=error").content.decode()
    ok_only = Client().get("/traces?status=ok").content.decode()
    other_generation = Client().get("/traces?generation=999").content.decode()

    assert f'href="/traces/{trace_id}"' in html
    assert "POST /generations" in html
    assert 'href="/generations/7"' in html
    assert trace_id in errors_only
    assert trace_id not in ok_only
    assert trace_id not in other_generation


def test_trace_detail_renders_the_waterfall() -> None:
    export(record_generation_trace(7))
    trace_id = first_trace_id()

    html = Client().get(f"/traces/{trace_id}").content.decode()

    assert "span-request" in html
    assert "span-llm" in html
    assert "span-error" in html
    assert "error</span>" in html
    assert "1 LLM calls" in html
    assert "150 tokens" in html
    assert (
        html.index("POST /generations") < html.index("generate") < html.index("DummyLM")
    )


def test_span_panel_shows_the_llm_call_view() -> None:
    export(record_generation_trace(7))
    llm = TraceSpan.query.get(TraceSpan.name.equals("DummyLM.__call__"))

    html = Client().get(f"/traces/{llm.trace_id}/spans/{llm.span_id}").content.decode()

    assert "LLM call" in html
    assert "gemini/gemini-3.8-flash" in html
    assert "Document GET /pets" in html
    assert "Lists pets." in html
    assert "150" in html


@pytest.mark.parametrize(
    "path",
    [
        "/traces/not-a-trace",
        "/traces/" + "0" * 32 + "/spans/zz",
        "/traces/" + "0" * 32 + "/spans/" + "0" * 16,
    ],
)
def test_malformed_or_unknown_ids_return_404(path: str) -> None:
    assert Client().get(path).status_code == 404


def test_a_trace_without_spans_yet_waits_and_polls() -> None:
    response = Client().get("/traces/" + "0" * 32)

    html = response.content.decode()
    assert response.status_code == 200
    assert "Waiting for spans" in html
    assert 'hx-trigger="load delay:2s"' in html


def test_generation_page_shows_the_trace_summary_strip(settings) -> None:
    spans = record_generation_trace(1)
    export(spans)
    trace_id = first_trace_id()
    generation = make_generation(trace_id=trace_id)
    now = datetime.now(UTC)
    Generation.query.filter(id=generation.id).update(
        started_at=now - timedelta(seconds=65), finished_at=now
    )

    html = Client().get(f"/generations/{generation.id}").content.decode()

    assert "LLM calls" in html
    assert "Total tokens" in html
    assert "150" in html
    assert "1m 05s" in html


def test_prune_job_deletes_spans_past_retention(settings) -> None:
    export(record_generation_trace(7))
    old = datetime.now(UTC) - timedelta(days=45)
    TraceSpan.query.filter(name="generate").update(start_time=old)
    settings.TRACES_RETENTION_DAYS = 30

    PruneTracesJob().run()

    assert sorted(row.name for row in TraceSpan.query.all()) == [
        "DummyLM.__call__",
        "POST /generations",
        "extract",
    ]
