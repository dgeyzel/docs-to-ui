from typing import Any

from d2u.generation.client import FAKE_MODEL
from d2u.generation.params import offered_params
from d2u.registry.models import ModelConfig, PromptVersion
from plain import forms

from app.goldsets.models import GoldSet
from app.optimization.optimizers import (
    LABELS,
    Optimizer,
    coerce_params,
    mipro_available,
)


def prompt_choices() -> list[tuple[str, str]]:
    return [
        (str(prompt.id), f"{prompt} ({prompt.status})")
        for prompt in PromptVersion.query.filter(strategy="llm").order_by(
            "language", "version"
        )
    ]


def gold_set_choices() -> list[tuple[str, str]]:
    return [
        (str(gold_set.id), f"{gold_set.name} ({gold_set.language})")
        for gold_set in GoldSet.query.order_by("name")
    ]


def task_model_choices() -> list[tuple[str, str]]:
    return [
        (str(model.id), model.name)
        for model in ModelConfig.query.filter(enabled_for_generation=True).order_by(
            "name"
        )
    ]


def judge_choices() -> list[tuple[str, str]]:
    return [
        (str(model.id), model.name)
        for model in ModelConfig.query.filter(enabled_for_judging=True).order_by("name")
    ]


def param_input_name(optimizer: Optimizer, name: str) -> str:
    """The form input for one optimizer's parameter."""
    return f"{optimizer.value}__{name}"


class OptimizationForm(forms.Form):
    """Configure an optimization run (SPEC §9.4).

    Parameters are read from `<optimizer>__<param>` inputs for the chosen
    optimizer only; empty ones take their defaults.
    """

    base_prompt = forms.ChoiceField(choices=prompt_choices)
    gold_set = forms.ChoiceField(choices=gold_set_choices)
    task_model = forms.ChoiceField(choices=task_model_choices)
    judge = forms.ChoiceField(choices=judge_choices)
    optimizer = forms.ChoiceField(choices=[(o.value, LABELS[o]) for o in Optimizer])

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if self.errors:
            return cleaned
        optimizer = Optimizer(cleaned["optimizer"])
        raw = {
            name.split("__", 1)[1]: str(self.data.get(name, ""))
            for name in self.data
            if name.startswith(f"{optimizer.value}__")
        }
        try:
            cleaned["params"] = coerce_params(optimizer, raw)
        except ValueError as exc:
            self.add_error("optimizer", forms.ValidationError(str(exc)))
            return cleaned
        task = ModelConfig.query.get(int(cleaned["task_model"]))
        if optimizer == Optimizer.MIPRO and not mipro_available():
            self.add_error(
                "optimizer",
                forms.ValidationError(
                    "MIPROv2 needs optuna: run uv sync --all-packages --group optimize."
                ),
            )
        accepts_temperature = task.litellm_model == FAKE_MODEL or "temperature" in {
            spec.name for spec in offered_params(task.litellm_model)
        }
        if optimizer == Optimizer.COPRO and not accepts_temperature:
            self.add_error(
                "optimizer",
                forms.ValidationError(
                    f"COPRO varies the temperature, which {task.name} doesn't accept."
                ),
            )
        cleaned["task_obj"] = task
        cleaned["judge_obj"] = ModelConfig.query.get(int(cleaned["judge"]))
        cleaned["prompt_obj"] = PromptVersion.query.get(int(cleaned["base_prompt"]))
        cleaned["gold_set_obj"] = GoldSet.query.get(int(cleaned["gold_set"]))
        return cleaned
