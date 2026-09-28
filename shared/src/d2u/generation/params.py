"""Which call parameters a registered model may be given (SPEC §7).

Plain-free. The Tuning app's model form offers only the parameters listed
here that LiteLLM reports as supported for the model string, and never the
sampling parameters for Gemini 3 models.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import litellm

from d2u.generation.client import FAKE_MODEL, SAMPLING_PARAMS, is_gemini_3_or_newer


class ParamKind(StrEnum):
    FLOAT = "float"
    INTEGER = "integer"
    CHOICE = "choice"


@dataclass(frozen=True, slots=True)
class ParamSpec:
    """One editable call parameter and its allowed values."""

    name: str
    label: str
    kind: ParamKind
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    help: str = ""


EDITABLE_PARAMS: tuple[ParamSpec, ...] = (
    ParamSpec(
        "reasoning_effort",
        "Reasoning effort",
        ParamKind.CHOICE,
        choices=("minimal", "low", "medium", "high"),
        help="How much the model thinks before answering.",
    ),
    ParamSpec(
        "max_tokens",
        "Max output tokens",
        ParamKind.INTEGER,
        minimum=1,
        maximum=1_000_000,
    ),
    ParamSpec("temperature", "Temperature", ParamKind.FLOAT, minimum=0, maximum=2),
    ParamSpec("top_p", "Top p", ParamKind.FLOAT, minimum=0, maximum=1),
    ParamSpec("top_k", "Top k", ParamKind.INTEGER, minimum=1, maximum=1000),
    ParamSpec("seed", "Seed", ParamKind.INTEGER, minimum=0, maximum=2**31 - 1),
    ParamSpec(
        "frequency_penalty",
        "Frequency penalty",
        ParamKind.FLOAT,
        minimum=-2,
        maximum=2,
    ),
    ParamSpec(
        "presence_penalty",
        "Presence penalty",
        ParamKind.FLOAT,
        minimum=-2,
        maximum=2,
    ),
)
PARAMS_BY_NAME = {spec.name: spec for spec in EDITABLE_PARAMS}


def supported_by_litellm(litellm_model: str) -> set[str] | None:
    """The OpenAI-style parameters LiteLLM supports for a model string.

    Returns None when LiteLLM doesn't recognize the model string.
    """
    if not litellm_model.strip() or litellm_model == FAKE_MODEL:
        return None
    supported = litellm.get_supported_openai_params(model=litellm_model.strip())
    return set(supported) if supported else None


def offered_params(litellm_model: str) -> list[ParamSpec]:
    """The editable parameters to offer for a model string, in display order."""
    supported = supported_by_litellm(litellm_model)
    if supported is None:
        return []
    excluded = set(SAMPLING_PARAMS) if is_gemini_3_or_newer(litellm_model) else set()
    return [
        spec
        for spec in EDITABLE_PARAMS
        if spec.name in supported and spec.name not in excluded
    ]


def coerce_param(spec: ParamSpec, raw: str) -> Any:
    """Turn a submitted value into the parameter's type.

    Raises:
        ValueError: The value isn't valid for the parameter; the message is
            meant for the user.
    """
    text = raw.strip()
    if spec.kind == ParamKind.CHOICE:
        if text not in spec.choices:
            raise ValueError(f"Choose one of: {', '.join(spec.choices)}.")
        return text
    try:
        value: float | int = (
            int(text) if spec.kind == ParamKind.INTEGER else float(text)
        )
    except ValueError:
        kind = "a whole number" if spec.kind == ParamKind.INTEGER else "a number"
        raise ValueError(f"Enter {kind}.") from None
    if spec.minimum is not None and value < spec.minimum:
        raise ValueError(f"Must be at least {spec.minimum:g}.")
    if spec.maximum is not None and value > spec.maximum:
        raise ValueError(f"Must be at most {spec.maximum:g}.")
    return value
