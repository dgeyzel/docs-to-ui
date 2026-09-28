"""Choosing trace backends at runtime: stored in RuntimeSettings, read by the router."""

import psycopg
import pytest
from d2u.registry.models import RuntimeSettings
from d2u.telemetry.config import SETTINGS_TABLE, load_selection
from d2u.telemetry.routing import RoutingSpanProcessor, SelectionCache
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from plain.postgres import get_connection
from plain.postgres.database_url import build_database_url
from plain.test import Client


def database_url() -> str:
    return build_database_url(get_connection().settings_dict)


def choose(names: list[str]) -> None:
    runtime = RuntimeSettings.load()
    runtime.trace_backends = names
    runtime.update()


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_the_router_reads_the_settings_table() -> None:
    assert RuntimeSettings.model_options.db_table == SETTINGS_TABLE


@pytest.mark.usefixtures("isolated_db")
@pytest.mark.parametrize(
    ("stored", "loaded"),
    [
        (["native"], {"native"}),
        (["langfuse", "native"], {"native", "langfuse"}),
        ([], set()),
        (["zipkin", "langfuse"], {"langfuse"}),
    ],
)
def test_the_selection_is_read_from_runtime_settings(
    stored: list[str], loaded: set[str]
) -> None:
    choose(stored)

    assert load_selection(database_url()) == loaded


@pytest.mark.usefixtures("isolated_db")
def test_the_seeded_selection_is_native() -> None:
    assert load_selection(database_url()) == {"native"}


@pytest.mark.usefixtures("isolated_db")
def test_a_missing_settings_row_means_the_default_selection() -> None:
    RuntimeSettings.query.all().delete()

    assert load_selection(database_url()) == {"native"}


def test_an_unreachable_database_raises_for_the_cache_to_handle() -> None:
    with pytest.raises(psycopg.Error):
        load_selection("postgresql://postgres:postgres@127.0.0.1:1/none")


@pytest.mark.usefixtures("isolated_db")
def test_switching_backends_applies_within_the_ttl_without_a_restart() -> None:
    native, langfuse = InMemorySpanExporter(), InMemorySpanExporter()
    clock = FakeClock()
    url = database_url()
    cache = SelectionCache(lambda: load_selection(url), ttl_s=10, clock=clock)
    router = RoutingSpanProcessor(
        {
            "native": SimpleSpanProcessor(native),
            "langfuse": SimpleSpanProcessor(langfuse),
        },
        cache.current,
    )
    provider = TracerProvider()
    provider.add_span_processor(router)
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("before"):
        pass
    choose(["langfuse"])
    with tracer.start_as_current_span("cached"):
        pass
    clock.now = 10.0
    with tracer.start_as_current_span("after"):
        pass

    assert [s.name for s in native.get_finished_spans()] == ["before", "cached"]
    assert [s.name for s in langfuse.get_finished_spans()] == ["after"]


@pytest.mark.usefixtures("db")
def test_the_docs_app_shows_the_selection_read_only() -> None:
    choose(["native"])

    home = Client().get("/").content.decode()
    traces = Client().get("/traces").content.decode()

    assert "Traces: Native" in home
    assert "chosen in the Tuning app" in home
    assert "Traces are sent to: Native." in traces
    assert "Chosen in the Tuning app." in traces
    assert "/tuning/settings" not in home + traces


@pytest.mark.usefixtures("db")
def test_the_docs_app_says_when_no_backend_is_chosen() -> None:
    choose([])

    assert "Traces: none" in Client().get("/").content.decode()


@pytest.mark.usefixtures("db")
def test_the_docs_app_cannot_change_the_selection() -> None:
    response = Client().post("/tuning/settings", data={"trace_backends": []})

    assert response.status_code == 404
    assert RuntimeSettings.load().trace_backends == ["native"]


@pytest.mark.usefixtures("db")
def test_the_docs_app_shows_the_active_prompts_read_only() -> None:
    home = Client().get("/").content.decode()

    assert "Prompts: openapi/llm/baseline, python/llm/baseline" in home
