"""Request → job → DSPy spans must reach the backends and share one trace ID.

If the tracer provider wiring ever breaks, this fails in CI instead of the
trace viewer going quietly empty.
"""

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from plain.test import Client

from app.generations.jobs import GenerateDocJob
from app.generations.models import Generation
from tests.helpers import read_fixture

_exporter: InMemorySpanExporter | None = None


@pytest.fixture
def span_exporter() -> Iterator[InMemorySpanExporter]:
    """An in-memory backend attached to the app's shared tracer provider."""
    global _exporter
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider), (
        "app.telemetry installed no SDK provider"
    )
    if _exporter is None:
        _exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(_exporter))
    _exporter.clear()
    yield _exporter
    _exporter.clear()


@pytest.mark.usefixtures("db")
def test_request_job_and_llm_spans_share_one_trace(
    span_exporter: InMemorySpanExporter,
) -> None:
    Client().post(
        "/generations",
        data={"text": read_fixture("openapi/petstore-3.0.yaml"), "language": ""},
    )
    generation = Generation.query.order_by("-id").first()
    assert generation is not None
    GenerateDocJob(generation.id).run()

    spans = span_exporter.get_finished_spans()
    request = next(s for s in spans if s.kind == trace.SpanKind.SERVER)
    job = next(s for s in spans if s.name == "generate")
    llm = [
        s for s in spans if (s.attributes or {}).get("openinference.span.kind") == "LLM"
    ]
    stages = {s.name for s in spans} & {"bundle", "extract", "overview", "merge"}

    assert llm, "no DSPy LLM spans were recorded"
    assert stages == {"bundle", "extract", "overview", "merge"}
    assert any(s.name == "enrich.batch[0]" for s in spans)
    trace_ids = {request.context.trace_id, job.context.trace_id} | {
        s.context.trace_id for s in llm
    }
    assert len(trace_ids) == 1
    assert job.parent is not None
    assert job.parent.span_id == request.context.span_id
    assert Generation.query.get(generation.id).trace_id == trace.format_trace_id(
        request.context.trace_id
    )
    for span in [job, *llm]:
        assert span.attributes is not None
        assert span.attributes["docs.generation_id"] == str(generation.id)
        assert span.attributes["docs.program_version"] == "baseline"
    assert request.attributes is not None
    assert request.attributes["docs.generation_id"] == generation.id
