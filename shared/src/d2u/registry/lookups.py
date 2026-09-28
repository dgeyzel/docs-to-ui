"""Reading the runtime choices both apps share."""

from d2u.generation.exceptions import LLMConfigurationError
from d2u.registry.models import (
    ModelConfig,
    PromptStatus,
    PromptVersion,
    RuntimeSettings,
)


def active_model() -> ModelConfig | None:
    """The model the Docs app generates with, if one is set."""
    return RuntimeSettings.load().active_model


def require_active_model() -> ModelConfig:
    """The active model.

    Raises:
        LLMConfigurationError: None is set.
    """
    model = active_model()
    if model is None:
        raise LLMConfigurationError(
            "No active model is set. Choose one in the Tuning app."
        )
    return model


def trace_backends() -> list[str]:
    """The trace backend names chosen in the Tuning app."""
    return [str(name) for name in RuntimeSettings.load().trace_backends]


def active_prompt(*, language: str, strategy: str) -> PromptVersion | None:
    """The active prompt version for a language and strategy, if any."""
    return PromptVersion.query.get_or_none(
        language=language, strategy=strategy, status=PromptStatus.ACTIVE.value
    )


def active_prompt_labels(strategy: str) -> list[str]:
    """The active versions for a strategy, one per language, e.g. `openapi/llm/v3`."""
    prompts = PromptVersion.query.filter(
        strategy=strategy, status=PromptStatus.ACTIVE.value
    ).order_by("language")
    return [str(prompt) for prompt in prompts]


def require_active_prompt(*, language: str, strategy: str) -> PromptVersion:
    """The active prompt version for a language and strategy.

    Raises:
        LLMConfigurationError: None is active.
    """
    prompt = active_prompt(language=language, strategy=strategy)
    if prompt is None:
        raise LLMConfigurationError(
            f"No active {strategy} prompt for {language}. Promote one in the Tuning app."
        )
    return prompt
