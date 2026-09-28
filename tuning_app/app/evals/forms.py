from typing import Any

from d2u.registry.lookups import active_prompt
from d2u.registry.models import ModelConfig, PromptVersion
from d2u.schemas.gold import GOLD_SPLITS
from plain import forms
from plain.runtime import settings

from app.evals.metrics.components import COMPONENT_WEIGHTS
from app.evals.metrics.scoring import METRIC_WEIGHTS
from app.goldsets.models import GoldSet

STRATEGY_CHOICES = [
    ("llm", "llm: the model writes the whole page"),
    ("hybrid", "hybrid: parsed structure, model-written prose"),
    ("parser", "parser: no model (structural baseline)"),
]


def gold_set_choices() -> list[tuple[str, str]]:
    return [
        (str(gold_set.id), f"{gold_set.name} ({gold_set.language})")
        for gold_set in GoldSet.query.order_by("name")
    ]


def generation_model_choices() -> list[tuple[str, str]]:
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


def prompt_choices() -> list[tuple[str, str]]:
    return [
        (str(prompt.id), f"{prompt}{' (active)' if prompt.status == 'active' else ''}")
        for prompt in PromptVersion.query.order_by("language", "strategy", "version")
    ]


class EvalRunForm(forms.Form):
    """Configure an eval run (SPEC §9.3).

    An empty prompt version means the active one for the set's language and
    the chosen strategy.
    """

    gold_set = forms.ChoiceField(choices=gold_set_choices)
    split = forms.ChoiceField(choices=[(split, split) for split in GOLD_SPLITS])
    strategy = forms.ChoiceField(choices=STRATEGY_CHOICES)
    model = forms.ChoiceField(choices=generation_model_choices, required=False)
    prompt_version = forms.ChoiceField(choices=prompt_choices, required=False)
    judge = forms.ChoiceField(choices=judge_choices)
    concurrency = forms.IntegerField(min_value=1)

    def clean_concurrency(self) -> int:
        value = self.cleaned_data["concurrency"]
        limit = settings.TUNING_MAX_EVAL_CONCURRENCY
        if value > limit:
            raise forms.ValidationError(
                f"At most {limit} (PLAIN_TUNING_MAX_EVAL_CONCURRENCY)."
            )
        return value

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if self.errors:
            return cleaned
        gold_set = GoldSet.query.get(int(cleaned["gold_set"]))
        strategy = cleaned["strategy"]
        cleaned["gold_set_obj"] = gold_set
        cleaned["model_obj"] = None
        cleaned["prompt_obj"] = None
        if strategy == "parser":
            return cleaned
        if not cleaned.get("model"):
            self.add_error(
                "model",
                forms.ValidationError(f"The {strategy} strategy needs a model."),
            )
            return cleaned
        cleaned["model_obj"] = ModelConfig.query.get(int(cleaned["model"]))
        if cleaned.get("prompt_version"):
            prompt = PromptVersion.query.get(int(cleaned["prompt_version"]))
            if (prompt.language, prompt.strategy) != (gold_set.language, strategy):
                self.add_error(
                    "prompt_version",
                    forms.ValidationError(
                        f"Choose a {gold_set.language}/{strategy} prompt version."
                    ),
                )
                return cleaned
        else:
            prompt = active_prompt(language=gold_set.language, strategy=strategy)
            if prompt is None:
                self.add_error(
                    "prompt_version",
                    forms.ValidationError(
                        f"No {gold_set.language}/{strategy} prompt is active."
                    ),
                )
                return cleaned
        cleaned["prompt_obj"] = prompt
        return cleaned

    def chosen_judge(self) -> ModelConfig:
        """The judge model. Only call after `is_valid()` returned True."""
        return ModelConfig.query.get(int(self.cleaned_data["judge"]))


def _weight_field() -> forms.FloatField:
    return forms.FloatField(min_value=0, max_value=100)


class MetricWeightsForm(forms.Form):
    """New metric and component weights; saving creates a metric version."""

    notes = forms.TextField(required=False, max_length=500)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        for name in METRIC_WEIGHTS:
            self.fields[f"metric_{name}"] = _weight_field()
        for name in COMPONENT_WEIGHTS:
            self.fields[f"component_{name}"] = _weight_field()

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if self.errors:
            return cleaned
        metrics = {name: cleaned[f"metric_{name}"] for name in METRIC_WEIGHTS}
        components = {name: cleaned[f"component_{name}"] for name in COMPONENT_WEIGHTS}
        if sum(metrics.values()) <= 0:
            raise forms.ValidationError(
                "At least one metric weight must be above zero."
            )
        if sum(components.values()) <= 0:
            raise forms.ValidationError(
                "At least one component weight must be above zero."
            )
        cleaned["metrics"] = metrics
        cleaned["components"] = components
        return cleaned
