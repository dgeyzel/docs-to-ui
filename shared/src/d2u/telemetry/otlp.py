"""Langfuse OTLP export settings. Plain-free, so eval runs can use it too."""

import base64

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

OTLP_TRACES_PATH = "/api/public/otel/v1/traces"


def langfuse_traces_endpoint(base_url: str) -> str:
    """The OTLP/HTTP traces endpoint under a Langfuse base URL."""
    return base_url.rstrip("/") + OTLP_TRACES_PATH


def langfuse_auth_header(*, public_key: str, secret_key: str) -> dict[str, str]:
    """Basic auth built from `public_key:secret_key`."""
    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def langfuse_span_exporter(
    *, base_url: str, public_key: str, secret_key: str
) -> OTLPSpanExporter:
    """An OTLP exporter that sends spans to a Langfuse project."""
    return OTLPSpanExporter(
        endpoint=langfuse_traces_endpoint(base_url),
        headers=langfuse_auth_header(public_key=public_key, secret_key=secret_key),
    )
