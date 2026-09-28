import pytest
from d2u.generation.params import (
    PARAMS_BY_NAME,
    coerce_param,
    offered_params,
    supported_by_litellm,
)


def names(litellm_model: str) -> list[str]:
    return [spec.name for spec in offered_params(litellm_model)]


def test_gemini_3_models_are_never_offered_sampling_parameters() -> None:
    offered = names("gemini/gemini-3.8-flash")

    assert "reasoning_effort" in offered
    assert "max_tokens" in offered
    assert not {"temperature", "top_p", "top_k"} & set(offered)


def test_older_gemini_models_are_offered_sampling_parameters() -> None:
    assert {"temperature", "top_p"} <= set(names("gemini/gemini-2.5-flash"))


def test_only_parameters_litellm_supports_are_offered() -> None:
    offered = names("anthropic/claude-sonnet-4-5")
    supported = supported_by_litellm("anthropic/claude-sonnet-4-5")

    assert supported is not None
    assert set(offered) <= supported
    assert {"temperature", "max_tokens", "reasoning_effort"} <= set(offered)
    assert "seed" not in offered


@pytest.mark.parametrize("litellm_model", ["fake", "", "no-such-provider/model"])
def test_unknown_model_strings_are_offered_nothing(litellm_model: str) -> None:
    assert offered_params(litellm_model) == []


@pytest.mark.parametrize(
    ("name", "raw", "value"),
    [
        ("temperature", "0.7", 0.7),
        ("max_tokens", " 32000 ", 32000),
        ("reasoning_effort", "medium", "medium"),
        ("frequency_penalty", "-2", -2.0),
    ],
)
def test_submitted_values_are_coerced_to_the_parameter_type(
    name: str, raw: str, value: object
) -> None:
    assert coerce_param(PARAMS_BY_NAME[name], raw) == value


@pytest.mark.parametrize(
    ("name", "raw", "message"),
    [
        ("temperature", "hot", "Enter a number."),
        ("max_tokens", "1.5", "Enter a whole number."),
        ("temperature", "2.5", "Must be at most 2."),
        ("max_tokens", "0", "Must be at least 1."),
        ("reasoning_effort", "extreme", "Choose one of: minimal, low, medium, high."),
    ],
)
def test_invalid_values_are_rejected_with_a_message(
    name: str, raw: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        coerce_param(PARAMS_BY_NAME[name], raw)
