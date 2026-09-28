"""Reading stored spans for the trace viewer and the generation page."""

from dataclasses import dataclass
from datetime import datetime

from app.traces.models import TraceSpan
from app.traces.presentation import TraceTotals, trace_totals

RECENT_TRACES_LIMIT = 50


@dataclass(frozen=True, slots=True)
class TraceListRow:
    """One trace in the list: its root span and aggregate timing."""

    trace_id: str
    started_at: datetime
    ended_at: datetime
    has_error: bool
    generation_id: int | None
    span_count: int
    root_name: str

    @property
    def duration_ms(self) -> float:
        return (self.ended_at - self.started_at).total_seconds() * 1000


def recent_traces(*, generation_id: int | None, status: str) -> list[TraceListRow]:
    """The most recent traces, optionally filtered.

    Args:
        generation_id: Only traces with a span tagged with this generation.
        status: "error", "ok", or "" for all.
    """
    limit = RECENT_TRACES_LIMIT
    rows = TraceSpan.query.sql(
        t"""
        WITH traces AS (
            SELECT {TraceSpan.trace_id} AS trace_id,
                   min({TraceSpan.start_time}) AS started_at,
                   max({TraceSpan.end_time}) AS ended_at,
                   bool_or({TraceSpan.status_code} = 'ERROR') AS has_error,
                   max({TraceSpan.generation_id}) AS generation_id,
                   count(*) AS span_count
            FROM {TraceSpan}
            GROUP BY {TraceSpan.trace_id}
        )
        SELECT traces.trace_id AS trace_id,
               traces.started_at AS started_at,
               traces.ended_at AS ended_at,
               traces.has_error AS has_error,
               traces.generation_id AS generation_id,
               traces.span_count AS span_count,
               (
                   SELECT root.name FROM {TraceSpan} root
                   WHERE root.trace_id = traces.trace_id
                   ORDER BY (root.parent_span_id = '') DESC, root.start_time
                   LIMIT 1
               ) AS root_name
        FROM traces
        WHERE ({generation_id}::bigint IS NULL OR traces.generation_id = {generation_id}::bigint)
          AND ({status}::text = '' OR ({status}::text = 'error') = traces.has_error)
        ORDER BY traces.started_at DESC
        LIMIT {limit}
        """,
        result_type=TraceListRow,
    )
    return list(rows)


def trace_spans(trace_id: str) -> list[TraceSpan]:
    """Every stored span of a trace, by start time."""
    return list(
        TraceSpan.query.where(TraceSpan.trace_id.equals(trace_id)).order_by(
            "start_time"
        )
    )


def generation_trace_totals(trace_id: str) -> TraceTotals | None:
    """LLM calls and tokens for a generation's trace, if spans are stored."""
    if not trace_id:
        return None
    spans = trace_spans(trace_id)
    if not spans:
        return None
    return trace_totals(spans)
