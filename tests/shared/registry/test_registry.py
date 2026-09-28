import pytest
from d2u.generation.exceptions import LLMConfigurationError
from d2u.registry.lookups import (
    active_model,
    active_prompt,
    require_active_model,
    require_active_prompt,
)
from d2u.registry.models import ModelConfig, PromptVersion, RuntimeSettings
from plain.exceptions import ValidationError

pytestmark = pytest.mark.usefixtures("db")


def test_seeds_register_gemini_and_a_claude_judge() -> None:
    gemini = ModelConfig.query.get(name="Gemini 3.8 Flash")
    claude = ModelConfig.query.get(name="Claude Sonnet 4.5")
    runtime = RuntimeSettings.load()

    assert gemini.litellm_model == "gemini/gemini-3.8-flash"
    assert gemini.api_key_env == "GEMINI_API_KEY"
    assert "temperature" not in gemini.params
    assert claude.litellm_model.startswith("anthropic/")
    assert claude.enabled_for_judging is True
    assert runtime.default_judge_model is not None
    assert runtime.default_judge_model.id == claude.id
    assert runtime.trace_backends == ["native"]


@pytest.mark.parametrize("strategy", ["llm", "hybrid"])
@pytest.mark.parametrize("language", ["openapi", "python"])
def test_seeds_activate_a_baseline_prompt_per_language_and_strategy(
    language: str, strategy: str
) -> None:
    prompt = require_active_prompt(language=language, strategy=strategy)

    assert prompt.version == "baseline"
    assert prompt.source == "seed"
    assert prompt.to_spec().instructions == prompt.instructions


def test_only_one_prompt_per_language_and_strategy_can_be_active() -> None:
    with pytest.raises(ValidationError):
        PromptVersion(
            language="openapi",
            strategy="llm",
            version="v2",
            instructions="x",
            status="active",
        ).create()


def test_model_config_to_spec_carries_what_the_client_needs() -> None:
    spec = ModelConfig.query.get(name="Gemini 3.8 Flash").to_spec()

    assert spec.litellm_model == "gemini/gemini-3.8-flash"
    assert spec.api_key_env == "GEMINI_API_KEY"
    assert spec.params == {"reasoning_effort": "medium"}
    assert spec.max_input_tokens == 1048576


def test_missing_choices_raise_clear_configuration_errors() -> None:
    RuntimeSettings.query.update(active_model=None)
    PromptVersion.query.filter(language="python", strategy="llm").update(status="draft")

    assert active_model() is None
    assert active_prompt(language="python", strategy="llm") is None
    with pytest.raises(LLMConfigurationError, match="Tuning app"):
        require_active_model()
    with pytest.raises(LLMConfigurationError, match="No active llm prompt for python"):
        require_active_prompt(language="python", strategy="llm")


def test_prompt_examples_are_validated_for_their_strategy() -> None:
    prompt = PromptVersion(
        language="openapi",
        strategy="llm",
        version="v3",
        instructions="x",
        examples=[
            {
                "input_files": {"a.yaml": "openapi: 3.1.0"},
                "output": {"title": "T", "overview_md": "", "operations": []},
            }
        ],
    )

    spec = prompt.to_spec()

    assert spec.page_examples[0].input_files == {"a.yaml": "openapi: 3.1.0"}
    assert spec.docs_examples == []
