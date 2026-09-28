"""Tracing setup: one shared TracerProvider, routed to the chosen backends.

Every backend that could be used is attached at startup; which of them
receive spans is chosen in the Tuning app and read from the database by the
routing processor (SPEC §11.2).
"""

import logging
from dataclasses import dataclass

import psycopg
from openinference.instrumentation.litellm import LiteLLMInstrumentor
from opentelemetry import trace
from opentelemetry.processor.baggage import BaggageSpanProcessor
from opentelemetry.sdk import trace as sdk_trace
from opentelemetry.sdk.resources import Resource
from plain.packages import PackageConfig, register_config
from plain.runtime import settings
from psycopg import sql

from d2u.telemetry.backends.base import TraceBackend
from d2u.telemetry.routing import RoutingSpanProcessor, SelectionCache

logger = logging.getLogger(__name__)

DOCS_BAGGAGE_PREFIX = "docs."
BACKEND_NAMES = ("native", "langfuse")
BACKEND_LABELS = {"native": "Native", "langfuse": "Langfuse"}
# Read with a raw connection, like the span exporter, so the lookup stays out
# of Plain's query instrumentation and never touches a request's transaction.
SETTINGS_TABLE = "registry_runtimesettings"
SETTINGS_KEY = "default"
# What RuntimeSettings.load() would create if the row were missing.
DEFAULT_SELECTION = frozenset({"native"})
CONNECT_TIMEOUT_S = 2

_available: dict[str, TraceBackend] = {}
_selection: SelectionCache | None = None
_configured = False


@dataclass(frozen=True, slots=True)
class BackendOption:
    """A trace backend as the Settings page offers it.

    `missing` names the environment variables this process still needs
    before the backend can be chosen; it is empty for an available backend.
    """

    name: str
    label: str
    missing: tuple[str, ...]

    @property
    def available(self) -> bool:
        """Whether the backend can be chosen in this process."""
        return not self.missing


def is_docs_baggage_key(key: str) -> bool:
    """Only `docs.*` baggage is copied onto spans."""
    return key.startswith(DOCS_BAGGAGE_PREFIX)


def langfuse_missing_variables() -> list[str]:
    """The `LANGFUSE_*` variables that are not set, in a stable order."""
    values = {
        "LANGFUSE_BASE_URL": settings.TELEMETRY_LANGFUSE_BASE_URL,
        "LANGFUSE_PUBLIC_KEY": settings.TELEMETRY_LANGFUSE_PUBLIC_KEY,
        "LANGFUSE_SECRET_KEY": str(settings.TELEMETRY_LANGFUSE_SECRET_KEY),
        "LANGFUSE_PROJECT_ID": settings.TELEMETRY_LANGFUSE_PROJECT_ID,
    }
    return [name for name, value in values.items() if not value]


def backend_options() -> list[BackendOption]:
    """Every trace backend, with what this process needs to use it."""
    missing = {"native": (), "langfuse": tuple(langfuse_missing_variables())}
    return [
        BackendOption(name=name, label=BACKEND_LABELS[name], missing=missing[name])
        for name in BACKEND_NAMES
    ]


def normalize_selection(names: list[str] | tuple[str, ...]) -> list[str]:
    """Known backend names only, without duplicates, in `BACKEND_NAMES` order."""
    return [name for name in BACKEND_NAMES if name in names]


def selection_summary(names: list[str]) -> str:
    """A read-only description of a selection, e.g. "Native, Langfuse".

    A chosen backend this process can't use is marked, so an app missing the
    `LANGFUSE_*` variables says so instead of implying spans reach Langfuse.
    """
    options = {option.name: option for option in backend_options()}
    labels = [
        options[name].label
        + ("" if options[name].available else " (not configured in this app)")
        for name in normalize_selection(names)
    ]
    return ", ".join(labels) if labels else "none"


def build_available_backends() -> list[TraceBackend]:
    """Create every backend this process could send spans to.

    `native` is always available; `langfuse` only when its variables are set.
    """
    from d2u.telemetry.backends.native import NativeBackend

    backends: list[TraceBackend] = [
        NativeBackend(
            database_url=str(settings.POSTGRES_URL),
            max_attribute_bytes=settings.TELEMETRY_NATIVE_MAX_ATTRIBUTE_BYTES,
        )
    ]
    if not langfuse_missing_variables():
        from d2u.telemetry.backends.langfuse import LangfuseBackend

        backends.append(
            LangfuseBackend(
                base_url=settings.TELEMETRY_LANGFUSE_BASE_URL,
                public_key=settings.TELEMETRY_LANGFUSE_PUBLIC_KEY,
                secret_key=str(settings.TELEMETRY_LANGFUSE_SECRET_KEY),
                project_id=settings.TELEMETRY_LANGFUSE_PROJECT_ID,
            )
        )
    return backends


def load_selection(database_url: str) -> frozenset[str]:
    """Read `RuntimeSettings.trace_backends` with a short-lived connection.

    Raises:
        psycopg.Error: The database can't be reached or queried.
    """
    query = sql.SQL("SELECT trace_backends FROM {table} WHERE key = %s").format(
        table=sql.Identifier(SETTINGS_TABLE)
    )
    with psycopg.connect(
        database_url, autocommit=True, connect_timeout=CONNECT_TIMEOUT_S
    ) as connection:
        row = connection.execute(query, (SETTINGS_KEY,)).fetchone()
    if row is None:
        return DEFAULT_SELECTION
    names = row[0] if isinstance(row[0], list) else []
    return frozenset(normalize_selection([str(name) for name in names]))


def available_backends() -> list[TraceBackend]:
    """Backends attached at startup, whether selected or not."""
    return list(_available.values())


def selected_backends() -> list[TraceBackend]:
    """Attached backends that are currently selected, in `BACKEND_NAMES` order."""
    if _selection is None:
        return []
    selected = _selection.current()
    return [backend for name, backend in _available.items() if name in selected]


def invalidate_selection() -> None:
    """Make this process re-read the selection now instead of after the TTL."""
    if _selection is not None:
        _selection.invalidate()


def configure_tracing() -> None:
    """Attach the docs baggage processor and the backend router to the provider.

    An existing SDK TracerProvider is reused, so nothing installed earlier
    can disconnect the backends. A new one is created only when none exists.
    With `TELEMETRY_EXPORT_ENABLED` off, no backend is attached. Safe to call
    more than once; later calls do nothing.
    """
    global _configured, _selection
    if _configured:
        return
    existing = trace.get_tracer_provider()
    if isinstance(existing, sdk_trace.TracerProvider):
        provider = existing
    else:
        provider = sdk_trace.TracerProvider(
            resource=Resource.create({"service.name": settings.TELEMETRY_SERVICE_NAME})
        )
        trace.set_tracer_provider(provider)

    provider.add_span_processor(BaggageSpanProcessor(is_docs_baggage_key))
    if settings.TELEMETRY_EXPORT_ENABLED:
        database_url = str(settings.POSTGRES_URL)
        _selection = SelectionCache(
            lambda: load_selection(database_url),
            ttl_s=settings.TELEMETRY_SETTINGS_TTL_S,
        )
        for backend in build_available_backends():
            _available[backend.name] = backend
        provider.add_span_processor(
            RoutingSpanProcessor(
                {
                    name: backend.span_processor()
                    for name, backend in _available.items()
                },
                _selection.current,
            )
        )
    instrumentor = LiteLLMInstrumentor()
    if not instrumentor.is_instrumented_by_opentelemetry:
        instrumentor.instrument()
    _configured = True
    logger.info(
        "Tracing configured",
        extra={"available_backends": list(_available)},
    )


@register_config
class TelemetryConfig(PackageConfig):
    package_label = "telemetry"

    def ready(self) -> None:
        configure_tracing()
