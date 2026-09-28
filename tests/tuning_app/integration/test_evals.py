import pytest
from d2u.registry.models import ModelConfig, PromptVersion
from d2u.schemas.gold import GoldInput
from d2u.traces.queries import recent_traces
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from plain.jobs.models import JobRequest
from plain.test import Client

from app.evals import jobs
from app.evals.models import EvalResult, EvalRun, MetricVersion
from app.goldsets.models import GoldSet
from app.goldsets.services import content_hash, create_example, parser_page
from tests.helpers import read_fixture

pytestmark = pytest.mark.usefixtures("db")

PETSTORE = read_fixture("openapi/petstore-3.0.yaml")


@pytest.fixture
def gold_set() -> GoldSet:
    gold_set = GoldSet(name="Pets", language="openapi")
    gold_set.create()
    gold_input = GoldInput(origin="paste", files={"input.yaml": PETSTORE})
    for split in ("dev", "dev", "train"):
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


def run_form(gold_set: GoldSet, judge: ModelConfig, **fields: str) -> dict[str, str]:
    fake = ModelConfig.query.get(name="Fake")
    return {
        "gold_set": str(gold_set.id),
        "split": "dev",
        "strategy": "llm",
        "model": str(fake.id),
        "prompt_version": "",
        "judge": str(judge.id),
        "concurrency": "2",
    } | fields


def start(gold_set: GoldSet, judge: ModelConfig, **fields: str) -> EvalRun:
    response = Client().post(
        "/tuning/evals/new", data=run_form(gold_set, judge, **fields)
    )
    assert response.status_code == 302, response.content.decode()
    return EvalRun.query.order_by("-id").first()  # ty: ignore[invalid-return-type]


def run_queued() -> None:
    request = (
        JobRequest.query.filter(job_class="app.evals.jobs.EvalRunJob")
        .order_by("-id")
        .first()
    )
    assert request is not None
    assert request.parameters is not None
    jobs.EvalRunJob(*request.parameters["args"], **request.parameters["kwargs"]).run()


def test_a_run_is_created_with_the_active_prompt_and_queued_for_the_tuning_worker(
    gold_set: GoldSet, judge: ModelConfig
) -> None:
    run = start(gold_set, judge)

    assert run.status == "pending"
    assert run.prompt_label == "openapi/llm/baseline"
    assert (run.model_name, run.judge_name) == ("Fake", "Fake Judge")
    assert run.metric_version.version == 1
    assert JobRequest.query.get(job_class="app.evals.jobs.EvalRunJob").queue == "tuning"


def test_the_job_scores_every_approved_example_of_the_split(
    gold_set: GoldSet, judge: ModelConfig
) -> None:
    run = start(gold_set, judge)

    run_queued()

    run = EvalRun.query.get(run.id)
    results = list(EvalResult.query.filter(run=run))
    assert run.status == "succeeded"
    assert (run.examples_total, run.examples_done, len(results)) == (2, 2, 2)
    assert run.gold_set_hash == content_hash(gold_set)
    assert run.summary["total"]["total"]["mean"] > 0
    for result in results:
        assert result.status == "succeeded"
        assert result.output["strategy"] == "llm"
        assert result.verdict["prose_quality"] == 4
        assert result.scores["metrics"]["prose_quality"] == 0.75
        assert result.scores["metrics"]["coverage"] > 0
        assert result.details["faithfulness_judge"] == 0.75
    assert run.input_tokens >= 0


def test_the_parser_strategy_needs_no_model(
    gold_set: GoldSet, judge: ModelConfig
) -> None:
    run = start(gold_set, judge, strategy="parser", model="")

    run_queued()

    run = EvalRun.query.get(run.id)
    assert (run.status, run.model_name, run.prompt_label) == ("succeeded", "", "")
    result = EvalResult.query.filter(run=run).first()
    assert result is not None
    # The parser's page is the gold page here, so structure agrees fully.
    assert result.scores["metrics"]["component_accuracy"] == 1.0


def test_a_failing_example_scores_zero_without_stopping_the_run(
    gold_set: GoldSet, judge: ModelConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    claude = ModelConfig.query.get(name="Claude Sonnet 4.5")
    run = start(gold_set, judge, model=str(claude.id))

    run_queued()

    run = EvalRun.query.get(run.id)
    results = list(EvalResult.query.filter(run=run))
    assert run.status == "succeeded"
    assert {result.status for result in results} == {"failed"}
    assert all(result.total == 0.0 for result in results)
    assert "provider_error" in results[0].error
    assert "ANTHROPIC_API_KEY" in results[0].error
    assert run.summary["total"]["total"]["mean"] == 0.0


def test_a_failing_judge_leaves_the_judged_metrics_at_zero(
    gold_set: GoldSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    claude = ModelConfig.query.get(name="Claude Sonnet 4.5")
    run = start(gold_set, claude)

    run_queued()

    result = EvalResult.query.filter(run__id=run.id).first()
    assert result is not None
    assert result.status == "succeeded"
    assert result.scores["metrics"]["prose_quality"] == 0.0
    assert result.error.startswith("judge: provider_error")


def test_running_the_job_twice_does_nothing_the_second_time(
    gold_set: GoldSet, judge: ModelConfig
) -> None:
    run = start(gold_set, judge)
    run_queued()
    finished = EvalRun.query.get(run.id)

    run_queued()

    assert EvalResult.query.filter(run=run).count() == 2
    assert EvalRun.query.get(run.id).finished_at == finished.finished_at


def test_an_aborted_run_is_marked_failed(gold_set: GoldSet, judge: ModelConfig) -> None:
    run = start(gold_set, judge)

    jobs.EvalRunJob(run.id).on_aborted(result=None)  # ty: ignore[invalid-argument-type]

    run = EvalRun.query.get(run.id)
    assert run.status == "failed"
    assert run.error.startswith("worker_lost")


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"split": "test"}, "has no approved test examples"),
        ({"model": ""}, "The llm strategy needs a model."),
        ({"concurrency": "99"}, "At most 4"),
    ],
)
def test_invalid_runs_are_rejected(
    gold_set: GoldSet, judge: ModelConfig, fields: dict[str, str], message: str
) -> None:
    response = Client().post(
        "/tuning/evals/new", data=run_form(gold_set, judge, **fields)
    )

    assert response.status_code in (200, 422)
    assert message in response.content.decode()
    assert not EvalRun.query.exists()


def test_the_prompt_must_match_the_language_and_strategy(
    gold_set: GoldSet, judge: ModelConfig
) -> None:
    python_prompt = PromptVersion.query.get(
        language="python", strategy="llm", version="baseline"
    )

    response = Client().post(
        "/tuning/evals/new",
        data=run_form(gold_set, judge, prompt_version=str(python_prompt.id)),
    )

    assert "Choose a openapi/llm prompt version." in response.content.decode()


def test_the_form_warns_when_the_judge_is_the_generation_model(
    gold_set: GoldSet,
) -> None:
    fake = ModelConfig.query.get(name="Fake")
    fake.enabled_for_judging = True
    fake.update()
    run = start(gold_set, fake)

    html = Client().get(f"/tuning/evals/{run.id}").content.decode()

    assert "the model graded its own output" in html


def test_the_run_page_polls_until_finished_then_shows_the_summary(
    gold_set: GoldSet, judge: ModelConfig
) -> None:
    run = start(gold_set, judge)

    pending = Client().get(f"/tuning/evals/{run.id}").content.decode()
    status = Client().get(f"/tuning/evals/{run.id}/status")
    run_queued()
    finished = Client().get(f"/tuning/evals/{run.id}").content.decode()

    assert 'hx-trigger="every 2s"' in pending
    assert "0 of" in status.content.decode()
    assert Client().get(f"/tuning/evals/{run.id}/status").headers["HX-Redirect"] == (
        f"/tuning/evals/{run.id}"
    )
    assert "Component accuracy" in finished
    assert "95% interval" in finished
    assert "Operation F1" in finished
    assert f"#{run.id}" in Client().get("/tuning/evals").content.decode()


def test_editing_weights_creates_a_new_metric_version_for_new_runs(
    gold_set: GoldSet, judge: ModelConfig
) -> None:
    current = MetricVersion.query.get(version=1)
    data = {f"metric_{name}": str(value) for name, value in current.weights.items()}
    data |= {
        f"component_{name}": str(value)
        for name, value in current.component_weights.items()
    }
    data |= {"metric_prose_quality": "0", "notes": "No prose."}

    response = Client().post("/tuning/metrics", data=data)

    assert response.headers["Location"] == "/tuning/metrics?saved=1"
    newest = MetricVersion.query.get(version=2)
    assert newest.weights["prose_quality"] == 0.0
    assert current.weights["prose_quality"] == 0.2
    assert start(gold_set, judge).metric_version.version == 2


def test_all_zero_weights_are_rejected() -> None:
    current = MetricVersion.query.get(version=1)
    data = dict.fromkeys((f"metric_{name}" for name in current.weights), "0")
    data |= {f"component_{name}": "1" for name in current.component_weights}
    data |= {"notes": ""}

    response = Client().post("/tuning/metrics", data=data)

    assert "At least one metric weight must be above zero." in response.content.decode()
    assert not MetricVersion.query.filter(version=2).exists()


def test_eval_traces_can_be_filtered_by_run() -> None:
    assert recent_traces(generation_id=None, status="", eval_run_id=123) == []


_exporter: InMemorySpanExporter | None = None


@pytest.fixture
def span_exporter() -> InMemorySpanExporter:
    """An in-memory backend on the app's shared tracer provider."""
    global _exporter
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    if _exporter is None:
        _exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(_exporter))
    _exporter.clear()
    return _exporter


def test_every_span_of_a_run_carries_its_id_and_shares_one_trace(
    gold_set: GoldSet, judge: ModelConfig, span_exporter: InMemorySpanExporter
) -> None:
    run = start(gold_set, judge)

    run_queued()

    spans = [
        span
        for span in span_exporter.get_finished_spans()
        if (span.attributes or {}).get("docs.eval_run_id") == str(run.id)
    ]
    llm_spans = [
        s for s in spans if (s.attributes or {}).get("openinference.span.kind") == "LLM"
    ]
    names = {span.name for span in spans}
    assert {"eval.run", "eval.example", "check", "generate.part[0]"} <= names
    assert len(llm_spans) == 4  # two examples: one generation and one judge call each
    assert len({span.context.trace_id for span in spans}) == 1
    assert EvalRun.query.get(run.id).trace_id == trace.format_trace_id(
        spans[0].context.trace_id
    )
