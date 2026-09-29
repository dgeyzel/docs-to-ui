"""Running an optimization: DSPy search on train, a candidate, an eval on dev (SPEC §9.4)."""

import logging
from contextlib import redirect_stdout
from datetime import UTC, datetime

import dspy
import psycopg
from d2u.generation.client import FakeResponses
from d2u.generation.judging import judge_page
from d2u.generations.fakes import fake_responses
from d2u.registry.models import ModelConfig, PromptStatus, PromptVersion
from d2u.schemas.docpage import DocPage
from d2u.schemas.judging import JudgeVerdict
from d2u.telemetry.api import current_trace_context
from opentelemetry import trace
from plain.postgres import transaction
from plain.runtime import settings

from app.evals.models import EvalRun
from app.evals.runner import (
    approved_examples,
    current_metric_version,
    parser_surface,
)
from app.evals.runner import (
    create_run as create_eval_run,
)
from app.goldsets.models import GoldSet
from app.goldsets.services import adapter_for, content_hash
from app.optimization.exceptions import OptimizationRunError
from app.optimization.lm import make_lm
from app.optimization.metric import GoldCase, Judge, make_metric
from app.optimization.models import (
    OptimizationRun,
    OptimizationStage,
    OptimizationStatus,
)
from app.optimization.optimizers import (
    Optimizer,
    build_optimizer,
    compile_kwargs,
    mipro_available,
)
from app.optimization.program import build_program, export_prompt, source_text
from app.prompts.services import spec_examples

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
MAX_ERROR_CHARS = 1000
MAX_LOG_LINES = 500
DEFAULT_METRIC_THRESHOLD = 0.7
CANDIDATE_EVAL_CONCURRENCY = 2


class TrialLog(logging.Handler):
    """The optimizer's trial log for the run page.

    DSPy reports progress both through its loggers and with `print`, so this
    is a logging handler and a text stream at once (for `redirect_stdout`).
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self._add(self.format(record))

    def write(self, text: str) -> int:
        """Collect printed output, one entry per non-empty line."""
        for line in text.splitlines():
            self._add(line)
        return len(text)

    def flush(self) -> None:
        """Nothing is buffered."""

    def _add(self, line: str) -> None:
        if line.strip() and len(self.lines) < MAX_LOG_LINES:
            self.lines.append(line.rstrip())


def create_run(
    *,
    base_prompt: PromptVersion,
    gold_set: GoldSet,
    task_model: ModelConfig,
    judge_model: ModelConfig,
    optimizer: Optimizer,
    params: dict,
) -> OptimizationRun:
    """Record a pending run and queue its job.

    Raises:
        OptimizationRunError: The prompt, gold set and optimizer don't fit together.
    """
    from app.optimization.jobs import OptimizationRunJob

    if base_prompt.strategy != "llm":
        raise OptimizationRunError("Only llm prompt versions can be optimized.")
    if base_prompt.language != gold_set.language:
        raise OptimizationRunError(
            f"{base_prompt} is {base_prompt.language}, but {gold_set.name} is {gold_set.language}."
        )
    for split in ("train", "dev"):
        if not approved_examples(gold_set, split):
            raise OptimizationRunError(
                f"{gold_set.name} has no approved {split} examples."
            )
    if optimizer == Optimizer.MIPRO and not mipro_available():
        raise OptimizationRunError(
            "MIPROv2 needs optuna: run uv sync --all-packages --group optimize."
        )
    run = OptimizationRun(
        language=base_prompt.language,
        base_prompt=base_prompt,
        gold_set=gold_set,
        task_model=task_model,
        judge_model=judge_model,
        optimizer=optimizer.value,
        params=params,
        task_model_name=task_model.name,
        judge_name=judge_model.name,
    )
    run.create()
    try:
        queued = OptimizationRunJob(run.id).run_in_worker()
    except psycopg.Error:
        logger.exception("Could not queue optimization run %s", run.id)
        queued = None
    if queued is None:
        fail_run(run.id, "The run could not be queued. Try again.")
    return run


def claim_run(run_id: int) -> OptimizationRun | None:
    """Move a pending run to running; None if it isn't pending."""
    claimed = OptimizationRun.query.filter(
        id=run_id, status=OptimizationStatus.PENDING.value
    ).update(status=OptimizationStatus.RUNNING.value, started_at=datetime.now(UTC))
    if claimed == 0:
        return None
    return OptimizationRun.query.get(run_id)


def fail_run(run_id: int, error: str, *, trial_log: list[str] | None = None) -> None:
    """Record that an unfinished run failed, keeping any trial log so far."""
    values: dict = {
        "status": OptimizationStatus.FAILED.value,
        "error": error[:MAX_ERROR_CHARS],
        "finished_at": datetime.now(UTC),
    }
    if trial_log is not None:
        values["trial_log"] = trial_log
    OptimizationRun.query.filter(
        id=run_id,
        status__in=[OptimizationStatus.PENDING.value, OptimizationStatus.RUNNING.value],
    ).update(**values)


def _set_stage(run: OptimizationRun, stage: OptimizationStage) -> None:
    run.stage = stage.value
    run.update(fields=["stage"])


def _judge(model: ModelConfig, fake: FakeResponses | None) -> Judge:
    spec = model.to_spec()

    def judge(files: dict[str, str], page: DocPage) -> JudgeVerdict:
        return judge_page(model=spec, source_files=files, page=page, fake=fake).value

    return judge


def save_candidate(
    run: OptimizationRun, compiled: dspy.Module, files_by_source: dict
) -> PromptVersion:
    """Store the optimized program as a candidate prompt version (once per run)."""
    existing = PromptVersion.query.get_or_none(
        language=run.language, strategy="llm", version=run.candidate_label
    )
    if existing is not None:
        return existing
    spec = export_prompt(
        compiled,
        files_by_source=files_by_source,
        base=run.base_prompt.to_spec(),
        version=run.candidate_label,
    )
    candidate = PromptVersion(
        language=spec.language,
        strategy="llm",
        version=spec.version,
        instructions=spec.instructions,
        examples=spec_examples(spec),
        status=PromptStatus.CANDIDATE.value,
        source=f"optimization:{run.id}",
    )
    candidate.create()
    return candidate


def run_optimization(run: OptimizationRun) -> None:
    """Search, export the candidate, and start its eval on the dev split.

    Raises:
        OptimizationRunError: The task or judge model was deleted, or there
            are no approved train examples.
    """
    if run.task_model is None or run.judge_model is None:
        raise OptimizationRunError("The task or judge model was deleted.")
    examples = approved_examples(run.gold_set, "train")
    if not examples:
        raise OptimizationRunError(
            f"{run.gold_set.name} has no approved train examples."
        )
    run.gold_set_hash = content_hash(run.gold_set)
    run.train_examples = len(examples)
    run.update(fields=["gold_set_hash", "train_examples"])

    fake = fake_responses()
    adapter = adapter_for(run.language)
    cases: dict[str, GoldCase] = {}
    files_by_source: dict[str, dict[str, str]] = {}
    for example in examples:
        gold_input = example.gold_input()
        source = source_text(gold_input.files, gold_input.entry)
        files_by_source[source] = gold_input.files
        cases[source] = GoldCase(
            files=gold_input.files,
            expected=example.expected_page(),
            parser=parser_surface(gold_input, adapter),
        )
    trainset = [dspy.Example(source=source).with_inputs("source") for source in cases]
    optimizer = Optimizer(run.optimizer)
    metric = make_metric(
        cases=cases,
        language=run.language,
        judge=_judge(run.judge_model, fake),
        weights=current_metric_version().to_weights(),
        threshold=float(run.params.get("metric_threshold", DEFAULT_METRIC_THRESHOLD)),
    )
    task_lm = make_lm(run.task_model.to_spec(), fake=fake)

    log = TrialLog()
    log.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    dspy_logger = logging.getLogger("dspy")
    dspy_logger.addHandler(log)
    try:
        with tracer.start_as_current_span(
            "optimize", attributes={"docs.optimization_run_id": run.id}
        ):
            trace_context = current_trace_context()
            if trace_context is not None:
                OptimizationRun.query.filter(id=run.id).update(
                    trace_id=trace_context.trace_id
                )
            _set_stage(run, OptimizationStage.OPTIMIZING)
            teleprompter = build_optimizer(
                optimizer, run.params, metric=metric, prompt_model=task_lm
            )
            # stdout is process-wide; the worker runs one job per process.
            with dspy.context(lm=task_lm), redirect_stdout(log):
                compiled = teleprompter.compile(
                    build_program(run.base_prompt.to_spec()),
                    **compile_kwargs(
                        optimizer, run.params, trainset=trainset, valset=[]
                    ),
                )
    except Exception:
        # Keep what the optimizer logged; the job records the failure.
        run.trial_log = log.lines
        run.update(fields=["trial_log"])
        raise
    finally:
        dspy_logger.removeHandler(log)

    _set_stage(run, OptimizationStage.EXPORTING)
    with transaction.atomic():
        candidate = save_candidate(run, compiled, files_by_source)
        run.candidate = candidate
        run.trial_log = log.lines
        run.update(fields=["candidate", "trial_log"])

    _set_stage(run, OptimizationStage.EVALUATING)
    eval_run: EvalRun = create_eval_run(
        gold_set=run.gold_set,
        split="dev",
        strategy="llm",
        model=run.task_model,
        prompt=candidate,
        judge=run.judge_model,
        concurrency=min(
            CANDIDATE_EVAL_CONCURRENCY, settings.TUNING_MAX_EVAL_CONCURRENCY
        ),
    )
    OptimizationRun.query.filter(id=run.id).update(
        eval_run=eval_run,
        status=OptimizationStatus.SUCCEEDED.value,
        finished_at=datetime.now(UTC),
    )
    logger.info("Optimization run %s produced %s", run.id, candidate)
