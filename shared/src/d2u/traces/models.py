from datetime import datetime

from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class TraceSpan(postgres.Model):
    """One exported OpenTelemetry span. Written only by `PostgresSpanExporter`."""

    trace_id: Field[str] = types.TextField(max_length=32)
    span_id: Field[str] = types.TextField(max_length=16)
    parent_span_id: Field[str] = types.TextField(
        max_length=16, required=False, default=""
    )
    name: Field[str] = types.TextField(max_length=512)
    kind: Field[str] = types.TextField(max_length=16)
    start_time: Field[datetime] = types.DateTimeField()
    end_time: Field[datetime] = types.DateTimeField()
    duration_ms: Field[float] = types.FloatField()
    status_code: Field[str] = types.TextField(max_length=8)
    status_message: Field[str] = types.TextField(required=False, default="")
    attributes: Field[dict] = types.JSONField(required=False, default={})
    events: Field[list] = types.JSONField(required=False, default=[])
    resource: Field[dict] = types.JSONField(required=False, default={})
    generation_id: Field[int | None] = types.BigIntegerField(
        allow_null=True, required=False, default=None
    )
    is_llm: Field[bool] = types.BooleanField(default=False)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["trace_id", "span_id"],
                name="traces_tracespan_trace_id_span_id_unique",
            ),
        ],
        indexes=[
            postgres.Index(
                fields=["generation_id"], name="traces_tracespan_generation_id_idx"
            ),
            postgres.Index(fields=["is_llm"], name="traces_tracespan_is_llm_idx"),
            postgres.Index(
                fields=["start_time"], name="traces_tracespan_start_time_idx"
            ),
        ],
    )

    def __str__(self) -> str:
        return f"{self.name} ({self.span_id})"
