import pytest
from d2u.registry.models import ModelConfig, RuntimeSettings
from plain.jobs.models import JobRequest
from plain.test import Client

from app.models_ui import jobs
from app.models_ui.models import ModelTest, ModelTestStatus

pytestmark = pytest.mark.usefixtures("db")

CLAUDE = {
    "name": "Claude Test",
    "litellm_model": "anthropic/claude-sonnet-4-5",
    "api_key_env": "ANTHROPIC_API_KEY",
    "api_base": "",
    "max_input_tokens": "200000",
    "enabled_for_generation": "true",
    "notes": "",
}


def post_model(url: str = "/tuning/models/new", **fields: str):
    return Client().post(url, data=CLAUDE | fields)


def fake_model() -> ModelConfig:
    return ModelConfig.query.get(name="Fake")


def queued_test_job() -> JobRequest:
    return JobRequest.query.get(job_class="app.models_ui.jobs.TestModelJob")


def run_queued_test() -> None:
    request = queued_test_job()
    assert request.parameters is not None
    jobs.TestModelJob(*request.parameters["args"], **request.parameters["kwargs"]).run()


def test_model_list_shows_roles_and_key_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    html = Client().get("/tuning/models").content.decode()

    assert "Gemini 3.8 Flash" in html
    assert "Docs app model" in html
    assert "Default judge" in html
    assert 'GEMINI_API_KEY</span> <span class="form-error">missing' in html


def test_adding_a_model_keeps_only_offered_typed_parameters() -> None:
    response = post_model(
        param_temperature="0.2",
        param_max_tokens="4000",
        param_reasoning_effort="",
        param_seed="7",
    )

    model = ModelConfig.query.get(name="Claude Test")
    assert response.status_code == 302
    assert response.headers["Location"] == f"/tuning/models/{model.id}"
    assert model.params == {"temperature": 0.2, "max_tokens": 4000}
    assert model.enabled_for_generation is True
    assert model.enabled_for_judging is False


def test_gemini_3_models_never_store_sampling_parameters() -> None:
    post_model(
        name="Gemini Test",
        litellm_model="gemini/gemini-3.8-flash",
        param_temperature="0.5",
        param_reasoning_effort="low",
    )

    assert ModelConfig.query.get(name="Gemini Test").params == {
        "reasoning_effort": "low"
    }


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"param_temperature": "hot"}, "Enter a number."),
        ({"name": "Gemini 3.8 Flash"}, "A model with this name already exists."),
        ({"api_key_env": "my key"}, "Use an environment variable name"),
        ({"max_input_tokens": "10"}, "greater than or equal to 1000"),
    ],
)
def test_invalid_models_are_rejected(fields: dict[str, str], message: str) -> None:
    response = post_model(**fields)

    assert response.status_code == 200
    assert message in response.content.decode()
    assert not ModelConfig.query.filter(name="Claude Test").exists()


def test_the_form_offers_parameters_for_the_model_string() -> None:
    gemini = (
        Client()
        .get(
            "/tuning/models/params?litellm_model=gemini/gemini-3.8-flash&param_max_tokens=9"
        )
        .content.decode()
    )
    unknown = (
        Client().get("/tuning/models/params?litellm_model=nope/nope").content.decode()
    )

    assert 'name="param_reasoning_effort"' in gemini
    assert 'name="param_temperature"' not in gemini
    assert 'value="9"' in gemini
    assert "LiteLLM doesn't recognize this model string" in unknown


def test_editing_a_model_updates_it_and_drops_unsupported_parameters() -> None:
    post_model(param_temperature="0.2")
    model = ModelConfig.query.get(name="Claude Test")

    response = post_model(
        f"/tuning/models/{model.id}",
        litellm_model="gemini/gemini-3.8-flash",
        param_temperature="0.2",
        enabled_for_judging="true",
    )

    model = ModelConfig.query.get(model.id)
    assert response.headers["Location"] == f"/tuning/models/{model.id}?saved=1"
    assert model.litellm_model == "gemini/gemini-3.8-flash"
    assert model.params == {}
    assert model.enabled_for_judging is True


def test_the_edit_page_warns_before_dropping_parameters() -> None:
    post_model(param_temperature="0.2")
    model = ModelConfig.query.get(name="Claude Test")
    model.litellm_model = "gemini/gemini-3.8-flash"
    model.update()

    html = Client().get(f"/tuning/models/{model.id}").content.decode()

    assert (
        "Saving removes parameters this model string doesn't support: temperature."
        in html
    )


def test_the_active_model_must_stay_enabled_for_generation() -> None:
    model = fake_model()

    response = post_model(
        f"/tuning/models/{model.id}",
        name="Fake",
        litellm_model="fake",
        api_key_env="",
        max_input_tokens="1000000",
        enabled_for_generation="",
    )

    assert response.status_code == 200
    assert "activate another model first" in response.content.decode()
    assert ModelConfig.query.get(model.id).enabled_for_generation is True


def test_the_default_judge_must_stay_enabled_for_judging() -> None:
    judge = ModelConfig.query.get(name="Claude Sonnet 4.5")

    response = post_model(
        f"/tuning/models/{judge.id}", name="Claude Sonnet 4.5", enabled_for_judging=""
    )

    assert "choose another judge in Settings first" in response.content.decode()


def test_activating_a_model_makes_the_docs_app_use_it() -> None:
    gemini = ModelConfig.query.get(name="Gemini 3.8 Flash")

    response = Client().post(f"/tuning/models/{gemini.id}/activate")

    assert response.status_code == 302
    runtime = RuntimeSettings.load()
    assert runtime.active_model is not None
    assert runtime.active_model.id == gemini.id


def test_a_model_disabled_for_generation_cannot_be_activated() -> None:
    post_model(enabled_for_generation="")
    model = ModelConfig.query.get(name="Claude Test")

    response = Client().post(f"/tuning/models/{model.id}/activate")

    assert response.status_code == 400
    active = RuntimeSettings.load().active_model
    assert active is not None
    assert active.id == fake_model().id


def test_test_connection_is_queued_on_the_tuning_queue_and_records_success() -> None:
    model = fake_model()

    response = Client().post(f"/tuning/models/{model.id}/test")

    assert response.headers["Location"] == f"/tuning/models/{model.id}#connection-test"
    test = ModelTest.query.get(llm_model__id=model.id)
    assert test.status == ModelTestStatus.PENDING
    assert queued_test_job().queue == "tuning"
    run_queued_test()
    test = ModelTest.query.get(test.id)
    assert test.status == ModelTestStatus.SUCCEEDED
    assert test.latency_ms is not None
    assert test.finished_at is not None


def test_a_failed_connection_test_shows_the_error_without_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    model = ModelConfig.query.get(name="Claude Sonnet 4.5")
    Client().post(f"/tuning/models/{model.id}/test")

    run_queued_test()

    test = ModelTest.query.get(llm_model__id=model.id)
    assert test.status == ModelTestStatus.FAILED
    assert test.error == (
        "LLMConfigurationError: Environment variable ANTHROPIC_API_KEY is not set."
    )


def test_running_a_test_job_twice_does_nothing_the_second_time() -> None:
    model = fake_model()
    Client().post(f"/tuning/models/{model.id}/test")
    run_queued_test()
    finished = ModelTest.query.get(llm_model__id=model.id)

    run_queued_test()

    assert ModelTest.query.get(finished.id).finished_at == finished.finished_at


def test_the_test_result_is_polled_until_it_finishes() -> None:
    model = fake_model()
    Client().post(f"/tuning/models/{model.id}/test")
    test = ModelTest.query.get(llm_model__id=model.id)
    url = f"/tuning/models/{model.id}/tests/{test.id}"

    pending = Client().get(url)
    run_queued_test()
    finished = Client().get(url)
    detail = Client().get(f"/tuning/models/{model.id}").content.decode()

    assert pending.status_code == 200
    assert 'hx-trigger="every 1s"' in pending.content.decode()
    assert finished.status_code == 286
    assert "Answered in" in finished.content.decode()
    assert "Answered in" in detail


def test_a_test_of_another_model_is_not_found() -> None:
    model = fake_model()
    Client().post(f"/tuning/models/{model.id}/test")
    test = ModelTest.query.get(llm_model__id=model.id)
    other = ModelConfig.query.get(name="Gemini 3.8 Flash")

    assert Client().get(f"/tuning/models/{other.id}/tests/{test.id}").status_code == 404


def test_aborted_test_jobs_record_a_failure() -> None:
    model = fake_model()
    Client().post(f"/tuning/models/{model.id}/test")
    test = ModelTest.query.get(llm_model__id=model.id)

    jobs.TestModelJob(test.id).on_aborted(result=None)  # ty: ignore[invalid-argument-type]

    test = ModelTest.query.get(test.id)
    assert test.status == ModelTestStatus.FAILED
    assert "worker stopped" in test.error


def test_tuning_jobs_use_the_tuning_queue() -> None:
    assert jobs.TestModelJob(1).default_queue() == "tuning"
