from datetime import datetime
from enum import StrEnum

from d2u.registry.models import ModelConfig
from plain import postgres
from plain.postgres import Field, types


class ModelTestStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@postgres.register_model
class ModelTest(postgres.Model):
    """One Test connection run for a registered model (SPEC §7).

    The model's settings are copied when the test starts, so the result
    stays meaningful after the model is edited.
    """

    llm_model: Field[ModelConfig] = types.ForeignKeyField(
        ModelConfig, on_delete=postgres.CASCADE, related_query_name="tests"
    )
    litellm_model: Field[str] = types.TextField(max_length=200)
    status: Field[str] = types.TextField(
        max_length=16,
        choices=[(status.value, status.value) for status in ModelTestStatus],
        default=ModelTestStatus.PENDING.value,
    )
    latency_ms: Field[int | None] = types.IntegerField(
        allow_null=True, required=False, default=None
    )
    error: Field[str] = types.TextField(required=False, default="")
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    finished_at: Field[datetime | None] = types.DateTimeField(
        allow_null=True, required=False, default=None
    )

    model_options = postgres.Options(
        indexes=[
            postgres.Index(
                fields=["llm_model", "created_at"],
                name="models_ui_modeltest_llm_model_created_at_idx",
            ),
        ],
    )

    def __str__(self) -> str:
        return f"Test of {self.litellm_model} ({self.status})"

    @property
    def finished(self) -> bool:
        """Whether the test has a result."""
        return self.status in (ModelTestStatus.SUCCEEDED, ModelTestStatus.FAILED)
