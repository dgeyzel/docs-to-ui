"""Exporting OpenTelemetry spans into the `traces_tracespan` table.

Runs on the BatchSpanProcessor's background thread with its own raw psycopg
connection: request connections are never shared across threads, and these
inserts stay out of Plain's query instrumentation (no spans about spans).
Export failures are logged and dropped; they never affect a generation.
"""

import logging
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import format_span_id, format_trace_id
from psycopg import sql
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)

TABLE = "traces_tracespan"
COLUMNS = (
    "trace_id",
    "span_id",
    "parent_span_id",
    "name",
    "kind",
    "start_time",
    "end_time",
    "duration_ms",
    "status_code",
    "status_message",
    "attributes",
    "events",
    "resource",
    "generation_id",
    "is_llm",
    "eval_run_id",
)
TRUNCATION_MARKER = "…[truncated]"
GENERATION_ID_ATTRIBUTE = "docs.generation_id"
EVAL_RUN_ID_ATTRIBUTE = "docs.eval_run_id"
OPENINFERENCE_KIND = "openinference.span.kind"
WARNING_INTERVAL_S = 60.0


@dataclass(frozen=True, slots=True)
class SpanRow:
    """One row for the spans table, in `COLUMNS` order."""

    trace_id: str
    span_id: str
    parent_span_id: str
    name: str
    kind: str
    start_time: datetime
    end_time: datetime
    duration_ms: float
    status_code: str
    status_message: str
    attributes: dict[str, Any]
    events: list[dict[str, Any]]
    resource: dict[str, Any]
    generation_id: int | None
    is_llm: bool
    eval_run_id: int | None

    def values(self) -> tuple[Any, ...]:
        """Column values, with JSON columns wrapped for psycopg."""
        return (
            self.trace_id,
            self.span_id,
            self.parent_span_id,
            self.name,
            self.kind,
            self.start_time,
            self.end_time,
            self.duration_ms,
            self.status_code,
            self.status_message,
            Jsonb(self.attributes),
            Jsonb(self.events),
            Jsonb(self.resource),
            self.generation_id,
            self.is_llm,
            self.eval_run_id,
        )


def truncate_value(value: Any, max_bytes: int) -> Any:
    """Cut long strings (alone or in sequences) to `max_bytes` UTF-8 bytes."""
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        if len(encoded) <= max_bytes:
            return value
        return encoded[:max_bytes].decode("utf-8", errors="ignore") + TRUNCATION_MARKER
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [truncate_value(item, max_bytes) for item in value]
    return value


def _attributes(values: Mapping[str, Any] | None, max_bytes: int) -> dict[str, Any]:
    if not values:
        return {}
    return {key: truncate_value(value, max_bytes) for key, value in values.items()}


def _timestamp(nanoseconds: int | None) -> datetime:
    return datetime.fromtimestamp((nanoseconds or 0) / 1e9, tz=UTC)


def _generation_id(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def span_to_row(span: ReadableSpan, *, max_attribute_bytes: int) -> SpanRow:
    """Map a finished SDK span to a table row."""
    span_context = span.get_span_context()
    if span_context is None:
        raise ValueError("Span has no context")
    attributes = _attributes(span.attributes, max_attribute_bytes)
    start = span.start_time or 0
    end = span.end_time or start
    parent = span.parent
    return SpanRow(
        trace_id=format_trace_id(span_context.trace_id),
        span_id=format_span_id(span_context.span_id),
        parent_span_id=format_span_id(parent.span_id) if parent else "",
        name=span.name[:512],
        kind=span.kind.name,
        start_time=_timestamp(start),
        end_time=_timestamp(end),
        duration_ms=(end - start) / 1e6,
        status_code=span.status.status_code.name,
        status_message=span.status.description or "",
        attributes=attributes,
        events=[
            {
                "name": event.name,
                "timestamp": _timestamp(event.timestamp).isoformat(),
                "attributes": _attributes(event.attributes, max_attribute_bytes),
            }
            for event in span.events
        ],
        resource=_attributes(span.resource.attributes, max_attribute_bytes),
        generation_id=_generation_id(attributes.get(GENERATION_ID_ATTRIBUTE)),
        is_llm=attributes.get(OPENINFERENCE_KIND) == "LLM",
        eval_run_id=_generation_id(attributes.get(EVAL_RUN_ID_ATTRIBUTE)),
    )


def insert_statement(row_count: int) -> sql.Composed:
    """One parameterized INSERT for `row_count` rows; duplicates are skipped."""
    placeholders = sql.SQL("({})").format(
        sql.SQL(", ").join(sql.Placeholder() for _ in COLUMNS)
    )
    return sql.SQL(
        "INSERT INTO {table} ({columns}) VALUES {rows} "
        "ON CONFLICT (trace_id, span_id) DO NOTHING"
    ).format(
        table=sql.Identifier(TABLE),
        columns=sql.SQL(", ").join(sql.Identifier(column) for column in COLUMNS),
        rows=sql.SQL(", ").join(placeholders for _ in range(row_count)),
    )


class PostgresSpanExporter(SpanExporter):
    """Bulk-inserts span batches with a dedicated psycopg connection.

    Args:
        database_url: Postgres connection URL.
        max_attribute_bytes: Longest stored attribute string, in UTF-8 bytes.
    """

    def __init__(self, *, database_url: str, max_attribute_bytes: int) -> None:
        self._database_url = database_url
        self._max_attribute_bytes = max_attribute_bytes
        self._connection: psycopg.Connection | None = None
        self._lock = threading.Lock()
        self._last_warning = float("-inf")

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Insert the batch in one statement. Never raises."""
        if not spans:
            return SpanExportResult.SUCCESS
        with self._lock:
            try:
                rows = [
                    span_to_row(span, max_attribute_bytes=self._max_attribute_bytes)
                    for span in spans
                ]
                params = [value for row in rows for value in row.values()]
                connection = self._connect()
                with connection.cursor() as cursor:
                    cursor.execute(insert_statement(len(rows)), params)
                return SpanExportResult.SUCCESS
            except Exception:
                # Telemetry boundary: an export failure must never affect a generation.
                self._close()
                if self._should_warn():
                    logger.warning(
                        "Dropped %s spans: native trace export failed",
                        len(spans),
                        exc_info=True,
                    )
                return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        """Close the connection."""
        with self._lock:
            self._close()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Nothing is buffered here; the processor does the batching."""
        return True

    def _connect(self) -> psycopg.Connection:
        if self._connection is None or self._connection.closed:
            self._connection = psycopg.connect(self._database_url, autocommit=True)
        return self._connection

    def _close(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.close()
            except psycopg.Error:
                logger.debug("Error closing span export connection", exc_info=True)

    def _should_warn(self) -> bool:
        # At most one warning a minute, so a down database doesn't flood logs.
        now = time.monotonic()
        if now - self._last_warning < WARNING_INTERVAL_S:
            return False
        self._last_warning = now
        return True
