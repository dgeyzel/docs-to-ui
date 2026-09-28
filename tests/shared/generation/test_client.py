import json
from pathlib import Path

import pytest
from d2u.generation.client import (
    FakeResponses,
    ModelSpec,
    Usage,
    check_params,
    complete_structured,
    is_gemini_3_or_newer,
)
from d2u.generation.exceptions import (
    LLMConfigurationError,
    OutputValidationError,
    ProviderError,
)
from pydantic import BaseModel

FAKE = ModelSpec(name="Fake", litellm_model="fake")
MESSAGES = [
    {"role": "system", "content": "Answer."},
    {"role": "user", "content": "Question A"},
]


class Answer(BaseModel):
    title: str
    count: int


def test_structured_output_is_validated_into_the_pydantic_model() -> None:
    fake = FakeResponses({"Question A": {"title": "t", "count": 2}})

    result = complete_structured(
        model=FAKE, messages=MESSAGES, response_model=Answer, fake=fake
    )

    assert result.value == Answer(title="t", count=2)
    assert result.usage.calls == 1
    assert result.usage.input_tokens > 0


def test_invalid_answers_are_retried_once_with_the_error() -> None:
    class Sequenced(FakeResponses):
        def __init__(self) -> None:
            super().__init__({})
            self.seen: list[list[dict[str, str]]] = []

        def answer(self, messages: list[dict[str, str]]) -> str:
            self.seen.append(list(messages))
            return (
                '{"title": "t"}'
                if len(self.seen) == 1
                else '{"title": "t", "count": 1}'
            )

    fake = Sequenced()

    result = complete_structured(
        model=FAKE, messages=MESSAGES, response_model=Answer, fake=fake
    )

    assert result.value.count == 1
    assert result.usage.calls == 2
    retry = fake.seen[1]
    assert retry[-2] == {"role": "assistant", "content": '{"title": "t"}'}
    assert "count: Field required" in retry[-1]["content"]


def test_two_invalid_answers_raise() -> None:
    fake = FakeResponses({"Question A": {"title": "t"}})

    with pytest.raises(OutputValidationError, match="did not match Answer"):
        complete_structured(
            model=FAKE, messages=MESSAGES, response_model=Answer, fake=fake
        )


def test_unmatched_fake_answers_fail_validation() -> None:
    with pytest.raises(OutputValidationError):
        complete_structured(
            model=FAKE, messages=MESSAGES, response_model=Answer, fake=FakeResponses({})
        )


def test_the_fake_model_needs_fixtures() -> None:
    with pytest.raises(LLMConfigurationError, match="fixture"):
        complete_structured(model=FAKE, messages=MESSAGES, response_model=Answer)


def test_a_missing_api_key_variable_is_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("D2U_TEST_MISSING_KEY", raising=False)
    model = ModelSpec(
        name="Real",
        litellm_model="gemini/gemini-3.8-flash",
        api_key_env="D2U_TEST_MISSING_KEY",
    )

    with pytest.raises(LLMConfigurationError, match="D2U_TEST_MISSING_KEY is not set"):
        complete_structured(model=model, messages=MESSAGES, response_model=Answer)


def test_provider_failures_become_provider_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import litellm

    def refuse(**kwargs: object) -> None:
        raise litellm.exceptions.RateLimitError(
            message="slow down", llm_provider="gemini", model="m"
        )

    monkeypatch.setattr(litellm, "completion", refuse)
    model = ModelSpec(name="Gemini", litellm_model="gemini/gemini-3.8-flash")

    with pytest.raises(ProviderError, match="Gemini: RateLimitError"):
        complete_structured(model=model, messages=MESSAGES, response_model=Answer)


def test_the_api_key_is_read_from_the_named_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import litellm

    real_completion = litellm.completion
    captured: dict[str, object] = {}

    def capture(**kwargs: object) -> object:
        captured.update(kwargs)
        return real_completion(
            model="openai/fake",
            messages=MESSAGES,
            mock_response='{"title": "t", "count": 1}',
        )

    monkeypatch.setenv("D2U_TEST_KEY", "secret-value")
    monkeypatch.setattr(litellm, "completion", capture)
    model = ModelSpec(
        name="Gemini",
        litellm_model="gemini/gemini-3.8-flash",
        api_key_env="D2U_TEST_KEY",
        params={"reasoning_effort": "high"},
    )

    complete_structured(model=model, messages=MESSAGES, response_model=Answer)

    assert captured["api_key"] == "secret-value"
    assert captured["reasoning_effort"] == "high"
    assert captured["response_format"] is Answer
    assert "temperature" not in captured


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gemini/gemini-3.8-flash", True),
        ("gemini/gemini-3-pro", True),
        ("vertex_ai/gemini-4.0-flash", True),
        ("gemini/gemini-2.5-flash", False),
        ("anthropic/claude-sonnet-4-5", False),
    ],
)
def test_gemini_3_detection(model: str, expected: bool) -> None:
    assert is_gemini_3_or_newer(model) is expected


@pytest.mark.parametrize("param", ["temperature", "top_p", "top_k"])
def test_gemini_3_never_receives_sampling_parameters(param: str) -> None:
    with pytest.raises(LLMConfigurationError, match="reasoning_effort"):
        check_params("gemini/gemini-3.8-flash", {param: 0.2})


def test_other_models_may_use_sampling_parameters() -> None:
    check_params(
        "anthropic/claude-sonnet-4-5", {"temperature": 0.2, "max_tokens": 1000}
    )


@pytest.mark.parametrize(
    "param", ["api_key", "model", "messages", "response_format", "mock_response"]
)
def test_reserved_parameters_cannot_be_stored_on_a_model(param: str) -> None:
    with pytest.raises(LLMConfigurationError, match="set by the client"):
        check_params("anthropic/claude-sonnet-4-5", {param: "x"})


def test_fake_responses_match_the_first_key_in_the_final_user_message(
    tmp_path: Path,
) -> None:
    path = tmp_path / "fake.json"
    path.write_text(
        json.dumps(
            {"Question": {"title": "generic", "count": 0}, "Question A": "unused"}
        )
    )
    fake = FakeResponses.from_file(path)

    assert json.loads(fake.answer(MESSAGES)) == {"title": "generic", "count": 0}
    assert fake.answer([{"role": "user", "content": "nothing"}]) == "{}"


def test_fake_responses_must_be_a_json_object(tmp_path: Path) -> None:
    path = tmp_path / "fake.json"
    path.write_text("[]")

    with pytest.raises(LLMConfigurationError, match="JSON object"):
        FakeResponses.from_file(path)


def test_usage_adds_up() -> None:
    total = Usage(1, 2, 0.5, 10, 1) + Usage(3, 4, 0.25, 5, 1)

    assert total == Usage(4, 6, 0.75, 15, 2)
