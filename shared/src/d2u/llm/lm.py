"""Building the language model a generation runs on."""

import json
from pathlib import Path
from typing import Any

import dspy
from dspy.utils.dummies import DummyLM

from d2u.llm.exceptions import LLMConfigurationError

FAKE_MODEL = "fake"
THINKING_LEVELS = ("low", "medium", "high")


def load_fake_responses(path: Path) -> dict[str, dict[str, Any]]:
    """Read DummyLM fixture responses: prompt substring to output fields.

    Raises:
        LLMConfigurationError: The file is missing or not a JSON object.
    """
    try:
        with path.open(encoding="utf-8") as handle:
            responses = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise LLMConfigurationError(
            f"Could not read fake LLM responses from {path}"
        ) from exc
    if not isinstance(responses, dict):
        raise LLMConfigurationError(f"{path} must contain a JSON object")
    return responses


def build_lm(
    *, model: str, thinking_level: str, fake_responses_path: Path | None = None
) -> dspy.BaseLM:
    """Return the LM for `model`.

    `fake` returns DSPy's `DummyLM` answering from the fixture file. Any other
    value is a LiteLLM model string. Gemini reads its key from the
    `GEMINI_API_KEY` environment variable. No sampling parameters are sent:
    the thinking level is passed as `reasoning_effort`, which LiteLLM maps to
    Gemini's `thinking_level`.

    Raises:
        LLMConfigurationError: Unknown thinking level, or `fake` without fixtures.
    """
    if model == FAKE_MODEL:
        if fake_responses_path is None:
            raise LLMConfigurationError("LLM_MODEL=fake needs LLM_FAKE_RESPONSES")
        return DummyLM(load_fake_responses(fake_responses_path))
    if thinking_level not in THINKING_LEVELS:
        raise LLMConfigurationError(
            f"Thinking level must be one of {', '.join(THINKING_LEVELS)}"
        )
    return dspy.LM(model, reasoning_effort=thinking_level, cache=False)
