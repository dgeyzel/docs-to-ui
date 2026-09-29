from datetime import datetime
from enum import StrEnum

from d2u.registry.models import ModelConfig, PromptVersion
from plain import postgres
from plain.postgres import Field, types

from app.evals.models import EvalRun
from app.goldsets.models import GoldSet
from app.optimization.optimizers import Optimizer


class OptimizationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OptimizationStage(StrEnum):
    QUEUED = ""
    OPTIMIZING = "optimizing"
    EXPORTING = "exporting"
    EVALUATING = "evaluating"


def _choices(values: list[str]) -> list[tuple[str, str]]:
    return [(value, value) for value in values]


@postgres.register_model
class OptimizationRun(postgres.Model):
    """One DSPy search for a better prompt version (SPEC §9.4).

    The gold set's train split drives the search; its dev split scores the
    resulting candidate through an eval run on the production path.
    """

    language: Field[str] = types.TextField(max_length=32)
    base_prompt: Field[PromptVersion] = types.ForeignKeyField(
        PromptVersion,
        on_delete=postgres.RESTRICT,
        related_query_name="optimization_bases",
    )
    gold_set: Field[GoldSet] = types.ForeignKeyField(
        GoldSet, on_delete=postgres.RESTRICT, related_query_name="optimization_runs"
    )
    task_model: Field[ModelConfig | None] = types.ForeignKeyField(
        ModelConfig,
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
        related_query_name="optimization_runs_task",
    )
    judge_model: Field[ModelConfig | None] = types.ForeignKeyField(
        ModelConfig,
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
        related_query_name="optimization_runs_judging",
    )
    optimizer: Field[str] = types.TextField(
        max_length=32, choices=_choices([optimizer.value for optimizer in Optimizer])
    )
    params: Field[dict] = types.JSONField(required=False, default={})
    task_model_name: Field[str] = types.TextField(
        max_length=100, required=False, default=""
    )
    judge_name: Field[str] = types.TextField(max_length=100, required=False, default="")
    gold_set_hash: Field[str] = types.TextField(
        max_length=64, required=False, default=""
    )
    status: Field[str] = types.TextField(
        max_length=16,
        choices=_choices([status.value for status in OptimizationStatus]),
        default=OptimizationStatus.PENDING.value,
    )
    stage: Field[str] = types.TextField(max_length=16, required=False, default="")
    train_examples: Field[int] = types.IntegerField(default=0)
    trial_log: Field[list] = types.JSONField(required=False, default=[])
    error: Field[str] = types.TextField(required=False, default="")
    candidate: Field[PromptVersion | None] = types.ForeignKeyField(
        PromptVersion,
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
        related_query_name="optimization_candidates",
    )
    eval_run: Field[EvalRun | None] = types.ForeignKeyField(
        EvalRun,
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
        related_query_name="optimization_runs",
    )
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
            postgres.Index(
                fields=["base_prompt"], name="optimization_run_base_prompt_idx"
            ),
            postgres.Index(fields=["gold_set"], name="optimization_run_gold_set_idx"),
            postgres.Index(
                fields=["task_model"], name="optimization_run_task_model_idx"
            ),
            postgres.Index(
                fields=["judge_model"], name="optimization_run_judge_model_idx"
            ),
            postgres.Index(fields=["candidate"], name="optimization_run_candidate_idx"),
            postgres.Index(fields=["eval_run"], name="optimization_run_eval_run_idx"),
            postgres.Index(
                fields=["created_at"], name="optimization_run_created_at_idx"
            ),
        ],
    )

    def __str__(self) -> str:
        return f"Optimization run {self.id}"

    @property
    def finished(self) -> bool:
        """Whether the search has stopped, successfully or not."""
        return self.status in (OptimizationStatus.SUCCEEDED, OptimizationStatus.FAILED)

    @property
    def candidate_label(self) -> str:
        """The label the candidate prompt version gets."""
        return f"opt-{self.id}"
