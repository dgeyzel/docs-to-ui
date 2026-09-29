"""The one place LLM calls are made: LiteLLM with structured output (SPEC §6.1).

Every call requests a Pydantic model as its response format and validates
the answer; an invalid answer is retried once with the validation error.
"""

import json
import logging
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import litellm
import openai
import pydantic

from d2u.generation.exceptions import (
    LLMConfigurationError,
    OutputValidationError,
    ProviderError,
)
from d2u.generation.prompts import Message

logger = logging.getLogger(__name__)

FAKE_MODEL = "fake"
# LiteLLM needs a provider prefix even for mock responses; nothing is sent.
_FAKE_LITELLM_MODEL = "openai/fake"
SAMPLING_PARAMS = ("temperature", "top_p", "top_k")
# Set by the client itself; a model's stored params may not override them.
RESERVED_PARAMS = (
    "model",
    "messages",
    "response_format",
    "api_key",
    "api_base",
    "mock_response",
)
_GEMINI_VERSION = re.compile(r"gemini-(\d+)")
MAX_ERROR_CHARS = 300


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """A registered model, as the client needs it (SPEC §7)."""

    name: str
    litellm_model: str
    api_key_env: str = ""
    api_base: str = ""
    params: Mapping[str, Any] = field(default_factory=dict)
    max_input_tokens: int = 128000


@dataclass(frozen=True, slots=True)
class Usage:
    """Tokens, cost and time spent on one or more calls."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    calls: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
            latency_ms=self.latency_ms + other.latency_ms,
            calls=self.calls + other.calls,
        )


@dataclass(frozen=True, slots=True)
class CallResult[T: pydantic.BaseModel]:
    """A validated answer and what it cost."""

    value: T
    usage: Usage


class FakeResponses:
    """Fixture answers for the fake model (tests only).

    Each key is a string to look for in the final user message; the first
    key found selects the answer. With no match the answer is `{}`, which
    fails validation like a bad real answer would.
    """

    def __init__(self, answers: Mapping[str, Any]) -> None:
        self._answers = dict(answers)

    @classmethod
    def from_file(cls, path: Path) -> FakeResponses:
        """Load answers from a JSON object file.

        Raises:
            LLMConfigurationError: The file is missing or not a JSON object.
        """
        try:
            answers = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LLMConfigurationError(
                f"Could not read fake responses from {path}"
            ) from exc
        if not isinstance(answers, dict):
            raise LLMConfigurationError(f"{path} must contain a JSON object")
        return cls(answers)

    def items(self) -> list[tuple[str, Any]]:
        """Every fixture key and its answer, in file order."""
        # Any: fixture answers are arbitrary JSON, validated by their callers.
        return list(self._answers.items())

    def answer(self, messages: list[Message]) -> str:
        """The fixture answer for these messages."""
        final = next(
            (
                message["content"]
                for message in reversed(messages)
                if message["role"] == "user"
            ),
            "",
        )
        for key, value in self._answers.items():
            if key in final:
                return value if isinstance(value, str) else json.dumps(value)
        return "{}"


def is_gemini_3_or_newer(litellm_model: str) -> bool:
    """Whether a model string names Gemini 3 or later."""
    match = _GEMINI_VERSION.search(litellm_model)
    return bool(match) and int(match.group(1)) >= 3


def api_key_is_set(model: ModelSpec) -> bool:
    """Whether the variable named by `api_key_env` is set (or none is needed).

    Only presence is reported; the key itself never leaves this module.
    """
    return not model.api_key_env or bool(os.environ.get(model.api_key_env))


def litellm_request_kwargs(model: ModelSpec) -> dict[str, Any]:
    """The LiteLLM keyword arguments for a registered (non-fake) model.

    For callers that hand a model to another LiteLLM user, such as DSPy's LM
    in the Tuning app. The key is resolved here, so it is still read only by
    this module.

    Raises:
        LLMConfigurationError: Bad parameters, a missing key, or the fake model.
    """
    if model.litellm_model == FAKE_MODEL:
        raise LLMConfigurationError("The fake model has no LiteLLM settings.")
    check_params(model.litellm_model, model.params)
    kwargs: dict[str, Any] = {"model": model.litellm_model, **dict(model.params)}
    if model.api_key_env:
        key = os.environ.get(model.api_key_env)
        if not key:
            raise LLMConfigurationError(
                f"Environment variable {model.api_key_env} is not set."
            )
        kwargs["api_key"] = key
    if model.api_base:
        kwargs["api_base"] = model.api_base
    return kwargs


def check_params(litellm_model: str, params: Mapping[str, Any]) -> None:
    """Reject call parameters a model must never receive.

    Raises:
        LLMConfigurationError: A reserved key is set, or a Gemini 3 model is
            given a sampling parameter.
    """
    reserved = sorted(set(params) & set(RESERVED_PARAMS))
    if reserved:
        raise LLMConfigurationError(
            f"Parameters set by the client: {', '.join(reserved)}"
        )
    if is_gemini_3_or_newer(litellm_model):
        sampling = sorted(set(params) & set(SAMPLING_PARAMS))
        if sampling:
            raise LLMConfigurationError(
                f"Gemini 3 models don't take sampling parameters ({', '.join(sampling)}); "
                "use reasoning_effort."
            )


def _call(
    model: ModelSpec,
    messages: list[Message],
    response_model: type[pydantic.BaseModel],
    fake: FakeResponses | None,
) -> tuple[str, Usage]:
    kwargs: dict[str, Any] = dict(model.params)
    litellm_model = model.litellm_model
    if litellm_model == FAKE_MODEL:
        if fake is None:
            raise LLMConfigurationError("The fake model needs fixture responses.")
        litellm_model = _FAKE_LITELLM_MODEL
        kwargs["mock_response"] = fake.answer(messages)
    else:
        if model.api_key_env:
            key = os.environ.get(model.api_key_env)
            if not key:
                raise LLMConfigurationError(
                    f"Environment variable {model.api_key_env} is not set."
                )
            kwargs["api_key"] = key
        if model.api_base:
            kwargs["api_base"] = model.api_base

    start = time.monotonic()
    try:
        response = litellm.completion(
            model=litellm_model,
            messages=messages,
            response_format=response_model,
            **kwargs,
        )
    except openai.OpenAIError as exc:
        detail = str(exc)[:MAX_ERROR_CHARS]
        raise ProviderError(f"{model.name}: {type(exc).__name__}: {detail}") from exc
    latency_ms = round((time.monotonic() - start) * 1000)
    if not isinstance(response, litellm.ModelResponse):
        # Only streaming or async calls return anything else; neither is used.
        raise ProviderError(
            f"{model.name}: unexpected response type {type(response).__name__}"
        )

    usage_block = getattr(response, "usage", None)
    cost = (getattr(response, "_hidden_params", None) or {}).get("response_cost") or 0.0
    usage = Usage(
        input_tokens=getattr(usage_block, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage_block, "completion_tokens", 0) or 0,
        cost_usd=float(cost),
        latency_ms=latency_ms,
        calls=1,
    )
    content = response.choices[0].message.content or ""
    return content, usage


def complete_structured[T: pydantic.BaseModel](
    *,
    model: ModelSpec,
    messages: list[Message],
    response_model: type[T],
    fake: FakeResponses | None = None,
) -> CallResult[T]:
    """Call the model and validate its answer as `response_model`.

    An answer that doesn't validate is retried once, with the validation
    error included in the retry.

    Raises:
        LLMConfigurationError: Bad parameters, a missing key, or no fixtures
            for the fake model.
        ProviderError: The provider failed.
        OutputValidationError: The answer didn't validate twice.
    """
    check_params(model.litellm_model, model.params)
    usage = Usage()
    attempt_messages = list(messages)
    last_error: pydantic.ValidationError | None = None
    for attempt in (1, 2):
        content, call_usage = _call(model, attempt_messages, response_model, fake)
        usage = usage + call_usage
        try:
            return CallResult(
                value=response_model.model_validate_json(content), usage=usage
            )
        except pydantic.ValidationError as exc:
            last_error = exc
            logger.warning(
                "Attempt %s returned invalid %s", attempt, response_model.__name__
            )
            problems = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()[:5]
            )
            attempt_messages = [
                *attempt_messages,
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        f"That answer did not match the required schema ({problems}). "
                        "Answer again with valid output only."
                    ),
                },
            ]
    raise OutputValidationError(
        f"The model's answer did not match {response_model.__name__}."
    ) from last_error
