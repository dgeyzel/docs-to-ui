from datetime import datetime
from enum import StrEnum

from plain import postgres
from plain.postgres import Field, types

from d2u.registry.models import ModelConfig, PromptVersion


class GenerationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class GenerationStage(StrEnum):
    BUNDLE = "bundle"
    EXTRACT = "extract"
    GENERATE = "generate"
    ENRICH = "enrich"
    OVERVIEW = "overview"
    MERGE = "merge"


class ErrorCode(StrEnum):
    INPUT_ERROR = "input_error"
    VALIDATION_ERROR = "validation_error"
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"
    WORKER_LOST = "worker_lost"
    ENQUEUE_ERROR = "enqueue_error"
    INTERNAL_ERROR = "internal_error"


class Strategy(StrEnum):
    LLM = "llm"
    HYBRID = "hybrid"
    PARSER = "parser"


class InputOrigin(StrEnum):
    PASTE = "paste"
    FILE = "file"
    ZIP = "zip"


def _choices(enum_class: type[StrEnum]) -> list[tuple[str, str]]:
    return [(member.value, member.value) for member in enum_class]


@postgres.register_model
class Generation(postgres.Model):
    """One request to document an input, from upload to rendered page."""

    # The requested language ("" means auto-detect) until extraction, then
    # the language of the adapter that was used.
    language: Field[str] = types.TextField(max_length=32, required=False, default="")
    input_origin: Field[str] = types.TextField(
        max_length=8, choices=_choices(InputOrigin)
    )
    input_filename: Field[str] = types.TextField(
        max_length=255, required=False, default=""
    )
    # For multi-file input: the entry file the user chose ("" = detect it).
    input_entry: Field[str] = types.TextField(
        max_length=255, required=False, default=""
    )
    input_blob: Field[bytes | memoryview] = types.BinaryField()
    input_sha256: Field[str] = types.TextField(max_length=64)
    input_bytes: Field[int] = types.IntegerField()
    input_manifest: Field[dict] = types.JSONField(required=False, default={})

    status: Field[str] = types.TextField(
        max_length=16,
        choices=_choices(GenerationStatus),
        default=GenerationStatus.PENDING.value,
    )
    stage: Field[str] = types.TextField(max_length=16, required=False, default="")
    progress: Field[dict] = types.JSONField(required=False, default={})
    strategy: Field[str] = types.TextField(
        max_length=8, choices=_choices(Strategy), default=Strategy.LLM.value
    )
    # The registry entries used, plus their names at the time, which stay
    # readable if an entry is later edited or deleted.
    llm_model: Field[ModelConfig | None] = types.ForeignKeyField(
        ModelConfig,
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
        related_query_name="generations",
    )
    prompt_version: Field[PromptVersion | None] = types.ForeignKeyField(
        PromptVersion,
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
        related_query_name="generations",
    )
    model: Field[str] = types.TextField(max_length=128, required=False, default="")
    prompt_label: Field[str] = types.TextField(
        max_length=200, required=False, default=""
    )
    input_tokens: Field[int] = types.IntegerField(default=0)
    output_tokens: Field[int] = types.IntegerField(default=0)
    cost_usd: Field[float] = types.FloatField(default=0.0)
    latency_ms: Field[int] = types.IntegerField(default=0)
    doc_json: Field[dict | None] = types.JSONField(
        required=False, allow_null=True, default=None
    )
    error_code: Field[str] = types.TextField(max_length=32, required=False, default="")
    error_detail: Field[dict] = types.JSONField(required=False, default={})
    trace_id: Field[str] = types.TextField(max_length=32, required=False, default="")
    # The request span the generation's job continues, so both share one trace.
    trace_span_id: Field[str] = types.TextField(
        max_length=16, required=False, default=""
    )

    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    updated_at: Field[datetime] = types.DateTimeField(create_now=True, update_now=True)
    started_at: Field[datetime | None] = types.DateTimeField(
        allow_null=True, required=False, default=None
    )
    finished_at: Field[datetime | None] = types.DateTimeField(
        allow_null=True, required=False, default=None
    )

    model_options = postgres.Options(
        indexes=[
            postgres.Index(
                fields=["created_at"], name="generations_generation_created_at_idx"
            ),
            postgres.Index(
                fields=["llm_model"], name="generations_generation_llm_model_idx"
            ),
            postgres.Index(
                fields=["prompt_version"],
                name="generations_generation_prompt_version_idx",
            ),
        ],
    )

    def __str__(self) -> str:
        return f"Generation {self.id}"

    @property
    def display_name(self) -> str:
        """Filename for uploads, or "Pasted input"."""
        if self.input_filename:
            return self.input_filename
        return "Pasted input"


@postgres.register_model
class Feedback(postgres.Model):
    """A 👍 / 👎 on a whole page (empty `operation_id`) or one operation."""

    generation: Field[Generation] = types.ForeignKeyField(
        Generation, on_delete=postgres.CASCADE
    )
    operation_id: Field[str] = types.TextField(
        max_length=512, required=False, default=""
    )
    score: Field[int] = types.SmallIntegerField()
    comment: Field[str] = types.TextField(required=False, default="")
    trace_id: Field[str] = types.TextField(max_length=32, required=False, default="")
    created_at: Field[datetime] = types.DateTimeField(create_now=True)

    model_options = postgres.Options(
        indexes=[
            postgres.Index(
                fields=["generation"], name="generations_feedback_generation_idx"
            ),
        ],
        constraints=[
            postgres.CheckConstraint(
                check=postgres.Q(score__in=[1, -1]),
                name="generations_feedback_score_check",
            ),
        ],
    )

    def __str__(self) -> str:
        return f"Feedback {self.id} ({self.score:+d})"
