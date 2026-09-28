from datetime import datetime
from enum import StrEnum

from d2u.registry.models import ModelConfig, PromptVersion
from plain import postgres
from plain.postgres import Field, types

from app.evals.metrics.scoring import Weights
from app.goldsets.models import GoldExample, GoldSet


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def _choices(enum_class: type[StrEnum]) -> list[tuple[str, str]]:
    return [(member.value, member.value) for member in enum_class]


@postgres.register_model
class MetricVersion(postgres.Model):
    """Metric and component weights (SPEC §9.5). Editing creates a new version."""

    version: Field[int] = types.IntegerField()
    weights: Field[dict] = types.JSONField()
    component_weights: Field[dict] = types.JSONField()
    notes: Field[str] = types.TextField(required=False, default="")
    created_at: Field[datetime] = types.DateTimeField(create_now=True)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["version"], name="evals_metricversion_version_unique"
            ),
        ],
    )

    def __str__(self) -> str:
        return f"Metrics v{self.version}"

    def to_weights(self) -> Weights:
        """The weights as the scoring code uses them."""
        return Weights(
            metrics={name: float(value) for name, value in self.weights.items()},
            components={
                name: float(value) for name, value in self.component_weights.items()
            },
        )


@postgres.register_model
class EvalRun(postgres.Model):
    """One evaluation of a strategy, model and prompt on a gold set split (SPEC §9.3).

    Names are copied when the run is created, so the run still says what it
    measured after registry entries change.
    """

    gold_set: Field[GoldSet] = types.ForeignKeyField(
        GoldSet, on_delete=postgres.RESTRICT, related_query_name="eval_runs"
    )
    split: Field[str] = types.TextField(max_length=8)
    strategy: Field[str] = types.TextField(max_length=16)
    llm_model: Field[ModelConfig | None] = types.ForeignKeyField(
        ModelConfig,
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
        related_query_name="eval_runs_generating",
    )
    prompt_version: Field[PromptVersion | None] = types.ForeignKeyField(
        PromptVersion,
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
        related_query_name="eval_runs",
    )
    judge_model: Field[ModelConfig | None] = types.ForeignKeyField(
        ModelConfig,
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
        related_query_name="eval_runs_judging",
    )
    metric_version: Field[MetricVersion] = types.ForeignKeyField(
        MetricVersion, on_delete=postgres.RESTRICT, related_query_name="eval_runs"
    )
    model_name: Field[str] = types.TextField(max_length=100, required=False, default="")
    prompt_label: Field[str] = types.TextField(
        max_length=200, required=False, default=""
    )
    judge_name: Field[str] = types.TextField(max_length=100, required=False, default="")
    gold_set_hash: Field[str] = types.TextField(
        max_length=64, required=False, default=""
    )
    concurrency: Field[int] = types.IntegerField(default=1)
    status: Field[str] = types.TextField(
        max_length=16, choices=_choices(RunStatus), default=RunStatus.PENDING.value
    )
    error: Field[str] = types.TextField(required=False, default="")
    examples_total: Field[int] = types.IntegerField(default=0)
    examples_done: Field[int] = types.IntegerField(default=0)
    summary: Field[dict] = types.JSONField(required=False, default={})
    input_tokens: Field[int] = types.IntegerField(default=0)
    output_tokens: Field[int] = types.IntegerField(default=0)
    cost_usd: Field[float] = types.FloatField(default=0.0)
    judge_cost_usd: Field[float] = types.FloatField(default=0.0)
    latency_ms: Field[int] = types.IntegerField(default=0)
    trace_id: Field[str] = types.TextField(max_length=32, required=False, default="")
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    started_at: Field[datetime | None] = types.DateTimeField(
        allow_null=True, required=False, default=None
    )
    finished_at: Field[datetime | None] = types.DateTimeField(
        allow_null=True, required=False, default=None
    )

    model_options = postgres.Options(
        indexes=[
            postgres.Index(fields=["gold_set"], name="evals_evalrun_gold_set_idx"),
            postgres.Index(fields=["llm_model"], name="evals_evalrun_llm_model_idx"),
            postgres.Index(
                fields=["prompt_version"], name="evals_evalrun_prompt_version_idx"
            ),
            postgres.Index(
                fields=["judge_model"], name="evals_evalrun_judge_model_idx"
            ),
            postgres.Index(
                fields=["metric_version"], name="evals_evalrun_metric_version_idx"
            ),
            postgres.Index(fields=["created_at"], name="evals_evalrun_created_at_idx"),
        ],
    )

    def __str__(self) -> str:
        return f"Eval run {self.id}"

    @property
    def finished(self) -> bool:
        """Whether the run has stopped, successfully or not."""
        return self.status in (RunStatus.SUCCEEDED, RunStatus.FAILED)

    @property
    def self_judged(self) -> bool:
        """Whether the judge is also the model being evaluated (SPEC D16)."""
        return self.llm_model is not None and (
            self.judge_model is not None and self.llm_model.id == self.judge_model.id
        )


@postgres.register_model
class EvalResult(postgres.Model):
    """One example's output, scores and costs in a run (SPEC §9.3)."""

    run: Field[EvalRun] = types.ForeignKeyField(
        EvalRun, on_delete=postgres.CASCADE, related_query_name="results"
    )
    example: Field[GoldExample | None] = types.ForeignKeyField(
        GoldExample,
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
        related_query_name="eval_results",
    )
    label: Field[str] = types.TextField(max_length=255, required=False, default="")
    status: Field[str] = types.TextField(max_length=16, choices=_choices(ResultStatus))
    error: Field[str] = types.TextField(required=False, default="")
    expected: Field[dict] = types.JSONField(required=False, default={})
    output: Field[dict] = types.JSONField(required=False, default={})
    scores: Field[dict] = types.JSONField(required=False, default={})
    details: Field[dict] = types.JSONField(required=False, default={})
    verdict: Field[dict] = types.JSONField(required=False, default={})
    total: Field[float] = types.FloatField(default=0.0)
    input_tokens: Field[int] = types.IntegerField(default=0)
    output_tokens: Field[int] = types.IntegerField(default=0)
    cost_usd: Field[float] = types.FloatField(default=0.0)
    judge_cost_usd: Field[float] = types.FloatField(default=0.0)
    latency_ms: Field[int] = types.IntegerField(default=0)
    created_at: Field[datetime] = types.DateTimeField(create_now=True)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["run", "example"], name="evals_evalresult_run_example_unique"
            ),
        ],
        indexes=[
            postgres.Index(fields=["example"], name="evals_evalresult_example_idx"),
        ],
    )

    def __str__(self) -> str:
        return f"Result {self.id} of run {self.run.id}"
