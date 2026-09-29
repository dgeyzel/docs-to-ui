"""The DSPy LM for a registered model. Plain-free.

Real models go through `dspy.LM` (LiteLLM underneath) with the registry's
settings. The fake model answers from the same fixtures as the rest of the
test suite, through DSPy's `DummyLM`, matched on the final user message.
"""

import json

import dspy
from d2u.generation.client import (
    FAKE_MODEL,
    FakeResponses,
    ModelSpec,
    litellm_request_kwargs,
)
from d2u.generation.exceptions import LLMConfigurationError
from d2u.schemas.generated import GeneratedPage
from dspy.utils import DummyLM
from pydantic import ValidationError


def fake_lm(fake: FakeResponses) -> DummyLM:
    """A DummyLM answering `page` with every fixture that is a GeneratedPage."""
    answers: dict[str, dict[str, str]] = {}
    for key, value in fake.items():
        try:
            page = GeneratedPage.model_validate(value)
        except ValidationError:
            continue
        answers[key] = {"page": json.dumps(page.model_dump(mode="json"))}
    return DummyLM(answers)


def make_lm(model: ModelSpec, *, fake: FakeResponses | None) -> dspy.BaseLM:
    """The LM DSPy should call for a registered model.

    Raises:
        LLMConfigurationError: A missing key, bad parameters, or the fake
            model without fixtures.
    """
    if model.litellm_model == FAKE_MODEL:
        if fake is None:
            raise LLMConfigurationError("The fake model needs fixture responses.")
        return fake_lm(fake)
    kwargs = litellm_request_kwargs(model)
    # No disk cache: every trial is a fresh, billed call, as in eval runs.
    return dspy.LM(cache=False, **kwargs)
