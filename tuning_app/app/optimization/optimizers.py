"""The DSPy optimizers a run can use and their editable parameters (SPEC §9.4).

Plain-free. `build_optimizer` turns a validated choice into a DSPy
teleprompter; `compile_kwargs` gives the arguments its `compile` needs.
"""

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import dspy


class Optimizer(StrEnum):
    BOOTSTRAP = "bootstrap_few_shot"
    RANDOM_SEARCH = "bootstrap_random_search"
    MIPRO = "mipro_v2"
    COPRO = "copro"


@dataclass(frozen=True, slots=True)
class OptimizerParam:
    """One editable optimizer parameter."""

    name: str
    label: str
    default: int | float | str
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        """ "choice", "integer" or "float", from the default's type."""
        if self.choices:
            return "choice"
        return "integer" if isinstance(self.default, int) else "float"


_BOOTSTRAP = (
    OptimizerParam("max_bootstrapped_demos", "Max bootstrapped demos", 4, 0, 16),
    OptimizerParam("max_labeled_demos", "Max labeled demos", 4, 0, 16),
    OptimizerParam("max_rounds", "Max rounds", 1, 1, 10),
    OptimizerParam("metric_threshold", "Metric threshold", 0.7, 0, 1),
)
PARAMS: dict[Optimizer, tuple[OptimizerParam, ...]] = {
    Optimizer.BOOTSTRAP: _BOOTSTRAP,
    Optimizer.RANDOM_SEARCH: (
        *_BOOTSTRAP,
        OptimizerParam("num_candidate_programs", "Candidate programs", 8, 1, 64),
    ),
    Optimizer.MIPRO: (
        OptimizerParam(
            "auto", "Auto level", "light", choices=("light", "medium", "heavy", "off")
        ),
        OptimizerParam("max_bootstrapped_demos", "Max bootstrapped demos", 4, 0, 16),
        OptimizerParam("max_labeled_demos", "Max labeled demos", 4, 0, 16),
        OptimizerParam("num_trials", "Trials (when auto is off)", 10, 1, 500),
        OptimizerParam("minibatch_size", "Minibatch size", 35, 1, 500),
        OptimizerParam("seed", "Seed", 9, 0, 2**31 - 1),
    ),
    Optimizer.COPRO: (
        OptimizerParam("breadth", "Breadth", 10, 2, 50),
        OptimizerParam("depth", "Depth", 3, 1, 10),
        OptimizerParam("init_temperature", "Initial temperature", 1.4, 0, 2),
    ),
}
LABELS = {
    Optimizer.BOOTSTRAP: "BootstrapFewShot",
    Optimizer.RANDOM_SEARCH: "BootstrapFewShotWithRandomSearch",
    Optimizer.MIPRO: "MIPROv2",
    Optimizer.COPRO: "COPRO",
}
Metric = Callable[..., float | bool]


def mipro_available() -> bool:
    """MIPROv2 needs optuna, installed with the Tuning app's `optimize` group."""
    return importlib.util.find_spec("optuna") is not None


def default_params(optimizer: Optimizer) -> dict[str, Any]:
    """Every parameter of an optimizer at its default."""
    return {param.name: param.default for param in PARAMS[optimizer]}


def coerce_params(optimizer: Optimizer, raw: dict[str, str]) -> dict[str, Any]:
    """Validated parameter values; missing or empty ones take their defaults.

    Raises:
        ValueError: A value is invalid; the message names the parameter.
    """
    values: dict[str, Any] = {}
    for param in PARAMS[optimizer]:
        text = str(raw.get(param.name, "")).strip()
        if not text:
            values[param.name] = param.default
            continue
        if param.kind == "choice":
            if text not in param.choices:
                raise ValueError(
                    f"{param.label}: choose one of {', '.join(param.choices)}."
                )
            values[param.name] = text
            continue
        try:
            value: int | float = int(text) if param.kind == "integer" else float(text)
        except ValueError:
            raise ValueError(f"{param.label}: enter a number.") from None
        if (param.minimum is not None and value < param.minimum) or (
            param.maximum is not None and value > param.maximum
        ):
            raise ValueError(
                f"{param.label}: must be between {param.minimum:g} and {param.maximum:g}."
            )
        values[param.name] = value
    return values


def build_optimizer(
    optimizer: Optimizer,
    params: dict[str, Any],
    *,
    metric: Metric,
    prompt_model: dspy.BaseLM,
) -> Any:  # Any: DSPy teleprompters share no public base type.
    """A configured DSPy teleprompter."""
    if optimizer == Optimizer.BOOTSTRAP:
        return dspy.BootstrapFewShot(
            metric=metric,
            metric_threshold=params["metric_threshold"],
            max_bootstrapped_demos=params["max_bootstrapped_demos"],
            max_labeled_demos=params["max_labeled_demos"],
            max_rounds=params["max_rounds"],
        )
    if optimizer == Optimizer.RANDOM_SEARCH:
        return dspy.BootstrapFewShotWithRandomSearch(
            metric=metric,
            metric_threshold=params["metric_threshold"],
            max_bootstrapped_demos=params["max_bootstrapped_demos"],
            max_labeled_demos=params["max_labeled_demos"],
            max_rounds=params["max_rounds"],
            num_candidate_programs=params["num_candidate_programs"],
            num_threads=1,
        )
    if optimizer == Optimizer.MIPRO:
        return dspy.MIPROv2(
            metric=metric,
            prompt_model=prompt_model,
            auto=None if params["auto"] == "off" else params["auto"],
            max_bootstrapped_demos=params["max_bootstrapped_demos"],
            max_labeled_demos=params["max_labeled_demos"],
            seed=params["seed"],
            num_threads=1,
            verbose=False,
        )
    return dspy.COPRO(
        prompt_model=prompt_model,
        metric=metric,
        breadth=params["breadth"],
        depth=params["depth"],
        init_temperature=params["init_temperature"],
    )


def compile_kwargs(
    optimizer: Optimizer, params: dict[str, Any], *, trainset: list, valset: list
) -> dict[str, Any]:
    """The arguments for the teleprompter's `compile`, besides the student."""
    if optimizer == Optimizer.MIPRO:
        kwargs: dict[str, Any] = {
            "trainset": trainset,
            "valset": valset or None,
            "minibatch_size": min(
                params["minibatch_size"], max(1, len(valset or trainset))
            ),
            "minibatch": len(valset or trainset) > params["minibatch_size"],
            "requires_permission_to_run": False,
        }
        if params["auto"] == "off":
            kwargs["num_trials"] = params["num_trials"]
        return kwargs
    if optimizer == Optimizer.COPRO:
        return {
            "trainset": trainset,
            "eval_kwargs": {"num_threads": 1, "display_progress": False},
        }
    if optimizer == Optimizer.RANDOM_SEARCH:
        return {"trainset": trainset, "valset": valset or None}
    return {"trainset": trainset}
