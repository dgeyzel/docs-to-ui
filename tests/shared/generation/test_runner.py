import pytest
from d2u.generation.client import FakeResponses, ModelSpec
from d2u.generation.exceptions import LLMConfigurationError
from d2u.generation.prompts import PromptSpec, baseline_instructions
from d2u.generation.runner import generate_for_bundle
from d2u.generation.strategies import GenerationConfig
from d2u.sources.adapters.openapi import OpenApiAdapter
from d2u.sources.exceptions import InputError

from tests.helpers import FIXTURES_DIR, bundle_of, read_fixture

PETSTORE = read_fixture("openapi/petstore-3.0.yaml")
FAKE = ModelSpec(name="Fake", litellm_model="fake", max_input_tokens=1_000_000)
PROMPT = PromptSpec(
    language="openapi",
    strategy="llm",
    version="baseline",
    instructions=baseline_instructions("openapi", "llm"),
)


@pytest.fixture
def config() -> GenerationConfig:
    return GenerationConfig(
        fake=FakeResponses.from_file(FIXTURES_DIR / "llm/fake.json")
    )


def test_the_parser_strategy_needs_no_model(config: GenerationConfig) -> None:
    result = generate_for_bundle(
        strategy="parser",
        bundle=bundle_of("petstore.yaml", PETSTORE),
        adapter=OpenApiAdapter(),
        config=config,
    )

    assert result.page.strategy == "parser"
    assert result.page.surface.operations
    assert result.usage.calls == 0


def test_the_llm_strategy_runs_the_production_generation(
    config: GenerationConfig,
) -> None:
    result = generate_for_bundle(
        strategy="llm",
        bundle=bundle_of("petstore.yaml", PETSTORE),
        adapter=OpenApiAdapter(),
        config=config,
        model=FAKE,
        prompt=PROMPT,
    )

    assert result.page.strategy == "llm"
    assert result.usage.calls == 1
    assert "GET /pets" in {op.id for op in result.page.surface.operations}


def test_broken_input_fails_before_any_model_call(config: GenerationConfig) -> None:
    with pytest.raises(InputError):
        generate_for_bundle(
            strategy="llm",
            bundle=bundle_of("api.yaml", "openapi: [unclosed"),
            adapter=OpenApiAdapter(),
            config=config,
        )


@pytest.mark.parametrize("strategy", ["llm", "hybrid"])
def test_llm_strategies_need_a_model_and_a_prompt(
    strategy: str, config: GenerationConfig
) -> None:
    with pytest.raises(LLMConfigurationError, match="needs a model and a prompt"):
        generate_for_bundle(
            strategy=strategy,
            bundle=bundle_of("petstore.yaml", PETSTORE),
            adapter=OpenApiAdapter(),
            config=config,
        )


def test_unknown_strategies_are_rejected(config: GenerationConfig) -> None:
    with pytest.raises(ValueError, match="Unknown strategy"):
        generate_for_bundle(
            strategy="magic",
            bundle=bundle_of("petstore.yaml", PETSTORE),
            adapter=OpenApiAdapter(),
            config=config,
        )
