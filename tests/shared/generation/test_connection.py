import pytest
from d2u.generation.client import (
    FakeResponses,
    ModelSpec,
    api_key_is_set,
    litellm_request_kwargs,
)
from d2u.generation.connection import check_connection
from d2u.generation.exceptions import LLMConfigurationError, OutputValidationError

FAKE = ModelSpec(name="Fake", litellm_model="fake")


def test_a_working_model_answers_the_connection_check() -> None:
    usage = check_connection(
        FAKE, fake=FakeResponses({"Connection check:": {"ok": True}})
    )

    assert usage.calls == 1


def test_an_answer_that_is_not_ok_fails_the_check() -> None:
    with pytest.raises(OutputValidationError, match="not with ok=true"):
        check_connection(FAKE, fake=FakeResponses({"Connection check:": {"ok": False}}))


def test_a_missing_key_fails_before_any_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("D2U_TEST_MISSING_KEY", raising=False)
    model = ModelSpec(
        name="Real", litellm_model="openai/gpt-4o", api_key_env="D2U_TEST_MISSING_KEY"
    )

    with pytest.raises(LLMConfigurationError, match="D2U_TEST_MISSING_KEY is not set"):
        check_connection(model)


@pytest.mark.parametrize(
    ("api_key_env", "value", "is_set"),
    [("", None, True), ("D2U_TEST_KEY", "secret", True), ("D2U_TEST_KEY", None, False)],
)
def test_api_key_presence_is_reported_without_the_key(
    monkeypatch: pytest.MonkeyPatch, api_key_env: str, value: str | None, is_set: bool
) -> None:
    monkeypatch.delenv("D2U_TEST_KEY", raising=False)
    if value is not None:
        monkeypatch.setenv("D2U_TEST_KEY", value)

    spec = ModelSpec(name="M", litellm_model="openai/gpt-4o", api_key_env=api_key_env)

    assert api_key_is_set(spec) is is_set


def test_litellm_settings_include_the_key_base_and_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("D2U_TEST_KEY", "secret")
    model = ModelSpec(
        name="M",
        litellm_model="openai/gpt-4o",
        api_key_env="D2U_TEST_KEY",
        api_base="https://proxy.example",
        params={"max_tokens": 10},
    )

    assert litellm_request_kwargs(model) == {
        "model": "openai/gpt-4o",
        "max_tokens": 10,
        "api_key": "secret",
        "api_base": "https://proxy.example",
    }


@pytest.mark.parametrize(
    ("model", "message"),
    [
        (ModelSpec(name="F", litellm_model="fake"), "no LiteLLM settings"),
        (
            ModelSpec(
                name="G",
                litellm_model="gemini/gemini-3.8-flash",
                params={"temperature": 1},
            ),
            "don't take sampling parameters",
        ),
        (
            ModelSpec(
                name="K",
                litellm_model="openai/gpt-4o",
                api_key_env="D2U_TEST_MISSING_KEY",
            ),
            "D2U_TEST_MISSING_KEY is not set",
        ),
    ],
)
def test_litellm_settings_refuse_unusable_models(
    monkeypatch: pytest.MonkeyPatch, model: ModelSpec, message: str
) -> None:
    monkeypatch.delenv("D2U_TEST_MISSING_KEY", raising=False)

    with pytest.raises(LLMConfigurationError, match=message):
        litellm_request_kwargs(model)
