"""Tracing setup: one shared TracerProvider feeding every active backend."""

import logging

from openinference.instrumentation.dspy import DSPyInstrumentor
from opentelemetry import trace
from opentelemetry.processor.baggage import BaggageSpanProcessor
from opentelemetry.sdk import trace as sdk_trace
from opentelemetry.sdk.resources import Resource
from plain.packages import PackageConfig, register_config
from plain.runtime import settings

from d2u.telemetry.backends.base import TraceBackend
from d2u.telemetry.exceptions import TelemetryConfigurationError

logger = logging.getLogger(__name__)

DOCS_BAGGAGE_PREFIX = "docs."

_active_backends: list[TraceBackend] = []
_configured = False


def is_docs_baggage_key(key: str) -> bool:
    """Only `docs.*` baggage is copied onto spans."""
    return key.startswith(DOCS_BAGGAGE_PREFIX)


def build_backends(names: list[str]) -> list[TraceBackend]:
    """Create the backends named in `TELEMETRY_BACKENDS`.

    Raises:
        TelemetryConfigurationError: A name is unknown, or a backend's required
            settings are missing.
    """
    backends: list[TraceBackend] = []
    for name in names:
        if name == "native":
            from d2u.telemetry.backends.native import NativeBackend

            backends.append(
                NativeBackend(
                    database_url=str(settings.POSTGRES_URL),
                    max_attribute_bytes=settings.TELEMETRY_NATIVE_MAX_ATTRIBUTE_BYTES,
                )
            )
        elif name == "langfuse":
            backends.append(_langfuse_backend())
        else:
            raise TelemetryConfigurationError(f"Unknown telemetry backend {name!r}")
    return backends


def _langfuse_backend() -> TraceBackend:
    required = {
        "LANGFUSE_BASE_URL": settings.TELEMETRY_LANGFUSE_BASE_URL,
        "LANGFUSE_PUBLIC_KEY": settings.TELEMETRY_LANGFUSE_PUBLIC_KEY,
        "LANGFUSE_SECRET_KEY": str(settings.TELEMETRY_LANGFUSE_SECRET_KEY),
        "LANGFUSE_PROJECT_ID": settings.TELEMETRY_LANGFUSE_PROJECT_ID,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise TelemetryConfigurationError(
            "The langfuse telemetry backend needs " + ", ".join(missing) + "."
        )
    from d2u.telemetry.backends.langfuse import LangfuseBackend

    return LangfuseBackend(
        base_url=required["LANGFUSE_BASE_URL"],
        public_key=required["LANGFUSE_PUBLIC_KEY"],
        secret_key=required["LANGFUSE_SECRET_KEY"],
        project_id=required["LANGFUSE_PROJECT_ID"],
    )


def active_backends() -> list[TraceBackend]:
    """Backends configured at startup, in `TELEMETRY_BACKENDS` order."""
    return list(_active_backends)


def configure_tracing() -> None:
    """Attach the docs baggage processor and every backend to the provider.

    An existing SDK TracerProvider is reused, so nothing installed earlier
    can disconnect the backends. A new one is created only when none exists.
    Safe to call more than once; later calls do nothing.
    """
    global _configured
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
    for backend in build_backends(settings.TELEMETRY_BACKENDS):
        provider.add_span_processor(backend.span_processor())
        _active_backends.append(backend)
    instrumentor = DSPyInstrumentor()
    if not instrumentor.is_instrumented_by_opentelemetry:
        instrumentor.instrument()
    _configured = True
    logger.info(
        "Tracing configured",
        extra={"backends": [backend.name for backend in _active_backends]},
    )


@register_config
class TelemetryConfig(PackageConfig):
    package_label = "telemetry"

    def ready(self) -> None:
        configure_tracing()
