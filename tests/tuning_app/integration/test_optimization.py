import pytest
from d2u.registry.models import ModelConfig, PromptVersion
from d2u.schemas.gold import GoldInput
from plain.jobs import Job
from plain.jobs.models import JobRequest
from plain.test import Client

from app.evals import jobs as eval_jobs
from app.evals.models import EvalRun
from app.goldsets.models import GoldSet
from app.goldsets.services import create_example, parser_page
from app.optimization import jobs
from app.optimization.models import OptimizationRun
from tests.helpers import read_fixture

pytestmark = pytest.mark.usefixtures("db")

PETSTORE = read_fixture("openapi/petstore-3.0.yaml")


@pytest.fixture
def gold_set() -> GoldSet:
    gold_set = GoldSet(name="Pets", language="openapi")
    gold_set.create()
    gold_input = GoldInput(origin="paste", files={"input.yaml": PETSTORE})
    for split in ("train", "dev"):
        create_example(
            gold_set,
            gold_input=gold_input,
            expected=parser_page("openapi", gold_input),
            source="parser_seed",
            split=split,
            status="approved",
        )
    return gold_set


@pytest.fixture
def judge() -> ModelConfig:
    model = ModelConfig(
        name="Fake Judge",
        litellm_model="fake",
        enabled_for_generation=False,
        enabled_for_judging=True,
    )
    model.create()
    return model


def baseline() -> PromptVersion:
    return PromptVersion.query.get(
        language="openapi", strategy="llm", version="baseline"
    )


def run_form(gold_set: GoldSet, judge: ModelConfig, **fields: str) -> dict[str, str]:
    return {
        "base_prompt": str(baseline().id),
        "gold_set": str(gold_set.id),
        "task_model": str(ModelConfig.query.get(name="Fake").id),
        "judge": str(judge.id),
        "optimizer": "bootstrap_few_shot",
        "bootstrap_few_shot__max_bootstrapped_demos": "1",
        "bootstrap_few_shot__max_labeled_demos": "1",
        "bootstrap_few_shot__max_rounds": "1",
        "bootstrap_few_shot__metric_threshold": "0.1",
    } | fields


def start(gold_set: GoldSet, judge: ModelConfig, **fields: str) -> OptimizationRun:
    response = Client().post(
        "/tuning/optimization/new", data=run_form(gold_set, judge, **fields)
    )
    assert response.status_code == 302, response.content.decode()
    run = OptimizationRun.query.order_by("-id").first()
    assert run is not None
    return run


def run_job(job: type[Job]) -> None:
    job_class = f"{job.__module__}.{job.__name__}"
    request = JobRequest.query.filter(job_class=job_class).order_by("-id").first()
    assert request is not None
    assert request.parameters is not None
    job(*request.parameters["args"], **request.parameters["kwargs"]).run()


def run_optimization() -> None:
    run_job(jobs.OptimizationRunJob)


def run_candidate_eval() -> None:
    run_job(eval_jobs.EvalRunJob)


def test_a_run_is_queued_for_the_tuning_worker_with_typed_parameters(
    gold_set: GoldSet, judge: ModelConfig
) -> None:
    run = start(gold_set, judge)

    assert run.status == "pending"
    assert run.params == {
        "max_bootstrapped_demos": 1,
        "max_labeled_demos": 1,
        "max_rounds": 1,
        "metric_threshold": 0.1,
    }
    assert JobRequest.query.get(
        job_class="app.optimization.jobs.OptimizationRunJob"
    ).queue == ("tuning")


def test_the_search_exports_a_candidate_and_evaluates_it_on_dev(
    gold_set: GoldSet, judge: ModelConfig
) -> None:
    run = start(gold_set, judge)

    run_optimization()

    run = OptimizationRun.query.get(run.id)
    assert run.status == "succeeded"
    assert run.train_examples == 1
    assert run.candidate is not None
    candidate = PromptVersion.query.get(run.candidate.id)
    assert (candidate.version, candidate.status, candidate.source) == (
        f"opt-{run.id}",
        "candidate",
        f"optimization:{run.id}",
    )
    # DSPy strips surrounding whitespace from instructions.
    assert candidate.instructions == baseline().instructions.strip()
    assert len(candidate.to_spec().page_examples) == 1
    assert run.eval_run is not None
    eval_run = EvalRun.query.get(run.eval_run.id)
    assert eval_run.prompt_version is not None
    assert (eval_run.split, eval_run.prompt_version.id) == ("dev", candidate.id)


def test_the_candidate_is_promoted_once_its_eval_finishes(
    gold_set: GoldSet, judge: ModelConfig
) -> None:
    run = start(gold_set, judge)
    run_optimization()
    early = Client().post(f"/tuning/optimization/{run.id}")
    assert early.status_code == 422

    run_candidate_eval()
    page = Client().get(f"/tuning/optimization/{run.id}").content.decode()
    response = Client().post(f"/tuning/optimization/{run.id}")

    run = OptimizationRun.query.get(run.id)
    assert run.candidate is not None
    candidate = PromptVersion.query.get(run.candidate.id)
    assert "Promote opt-" in page
    assert response.status_code == 302
    assert candidate.status == "active"
    assert candidate.scores["split"] == "dev"
    assert baseline().status == "candidate"


def test_running_the_job_twice_does_nothing_the_second_time(
    gold_set: GoldSet, judge: ModelConfig
) -> None:
    start(gold_set, judge)
    run_optimization()

    run_optimization()

    assert PromptVersion.query.filter(source__startswith="optimization:").count() == 1
    assert EvalRun.query.count() == 1


def test_a_failing_task_model_fails_the_run_with_its_error(
    gold_set: GoldSet, judge: ModelConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    claude = ModelConfig.query.get(name="Claude Sonnet 4.5")
    run = start(gold_set, judge, task_model=str(claude.id))

    run_optimization()

    run = OptimizationRun.query.get(run.id)
    assert run.status == "failed"
    assert "ANTHROPIC_API_KEY is not set" in run.error
    assert run.candidate is None


def test_an_aborted_run_is_marked_failed(gold_set: GoldSet, judge: ModelConfig) -> None:
    run = start(gold_set, judge)

    jobs.OptimizationRunJob(run.id).on_aborted(result=None)  # ty: ignore[invalid-argument-type]

    assert OptimizationRun.query.get(run.id).error.startswith("worker_lost")


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        (
            {"bootstrap_few_shot__max_rounds": "0"},
            "Max rounds: must be between 1 and 10.",
        ),
        ({"optimizer": "mipro_v2"}, "MIPROv2 needs optuna"),
    ],
)
def test_invalid_runs_are_rejected(
    gold_set: GoldSet, judge: ModelConfig, fields: dict[str, str], message: str
) -> None:
    response = Client().post(
        "/tuning/optimization/new", data=run_form(gold_set, judge, **fields)
    )

    assert response.status_code in (200, 422)
    assert message in response.content.decode()
    assert not OptimizationRun.query.exists()


def test_copro_needs_a_model_that_accepts_temperature(
    gold_set: GoldSet, judge: ModelConfig
) -> None:
    gemini = ModelConfig.query.get(name="Gemini 3.8 Flash")

    response = Client().post(
        "/tuning/optimization/new",
        data=run_form(gold_set, judge, optimizer="copro", task_model=str(gemini.id)),
    )

    assert (
        "COPRO varies the temperature, which Gemini 3.8 Flash doesn&#39;t accept."
        in (response.content.decode())
    )


def test_the_set_needs_approved_train_and_dev_examples(judge: ModelConfig) -> None:
    empty = GoldSet(name="Empty", language="openapi")
    empty.create()

    response = Client().post("/tuning/optimization/new", data=run_form(empty, judge))

    assert "Empty has no approved train examples." in response.content.decode()


def test_the_prompt_and_gold_set_languages_must_match(
    gold_set: GoldSet, judge: ModelConfig
) -> None:
    python = PromptVersion.query.get(
        language="python", strategy="llm", version="baseline"
    )

    response = Client().post(
        "/tuning/optimization/new",
        data=run_form(gold_set, judge, base_prompt=str(python.id)),
    )

    assert (
        "python/llm/baseline is python, but Pets is openapi."
        in response.content.decode()
    )


def test_the_run_page_polls_until_the_search_stops(
    gold_set: GoldSet, judge: ModelConfig
) -> None:
    run = start(gold_set, judge)

    pending = Client().get(f"/tuning/optimization/{run.id}").content.decode()
    run_optimization()
    status = Client().get(f"/tuning/optimization/{run.id}/status")

    assert 'hx-trigger="every 2s"' in pending
    assert status.headers["HX-Redirect"] == f"/tuning/optimization/{run.id}"
    assert f"#{run.id}" in Client().get("/tuning/optimization").content.decode()


def test_dspy_calls_are_traced_in_the_tuning_app() -> None:
    from openinference.instrumentation.dspy import DSPyInstrumentor

    assert DSPyInstrumentor().is_instrumented_by_opentelemetry


def test_the_optimizers_log_is_kept_as_the_trial_log(
    gold_set: GoldSet, judge: ModelConfig
) -> None:
    run = start(gold_set, judge)

    run_optimization()

    log = OptimizationRun.query.get(run.id).trial_log
    assert any("Bootstrapped" in line for line in log)
    assert (
        "Trial log" in Client().get(f"/tuning/optimization/{run.id}").content.decode()
    )
