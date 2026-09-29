import dspy
import pytest

from app.optimization.optimizers import (
    Optimizer,
    build_optimizer,
    coerce_params,
    compile_kwargs,
    default_params,
)


def metric(example: object, prediction: object, trace: object = None) -> float:
    return 1.0


def test_the_spec_defaults_are_offered() -> None:
    assert default_params(Optimizer.BOOTSTRAP) == {
        "max_bootstrapped_demos": 4,
        "max_labeled_demos": 4,
        "max_rounds": 1,
        "metric_threshold": 0.7,
    }
    assert default_params(Optimizer.RANDOM_SEARCH)["num_candidate_programs"] == 8
    assert default_params(Optimizer.COPRO) == {
        "breadth": 10,
        "depth": 3,
        "init_temperature": 1.4,
    }
    assert default_params(Optimizer.MIPRO)["auto"] == "light"


def test_submitted_values_are_typed_and_empty_ones_take_defaults() -> None:
    params = coerce_params(
        Optimizer.BOOTSTRAP, {"max_rounds": "3", "metric_threshold": ""}
    )

    assert params["max_rounds"] == 3
    assert params["metric_threshold"] == 0.7


@pytest.mark.parametrize(
    ("optimizer", "raw", "message"),
    [
        (
            Optimizer.BOOTSTRAP,
            {"max_rounds": "0"},
            "Max rounds: must be between 1 and 10.",
        ),
        (Optimizer.BOOTSTRAP, {"max_rounds": "many"}, "Max rounds: enter a number."),
        (Optimizer.MIPRO, {"auto": "extreme"}, "Auto level: choose one of"),
    ],
)
def test_invalid_values_are_rejected(
    optimizer: Optimizer, raw: dict[str, str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        coerce_params(optimizer, raw)


@pytest.mark.parametrize(
    ("optimizer", "kind"),
    [
        (Optimizer.BOOTSTRAP, dspy.BootstrapFewShot),
        (Optimizer.RANDOM_SEARCH, dspy.BootstrapFewShotWithRandomSearch),
        (Optimizer.COPRO, dspy.COPRO),
    ],
)
def test_each_optimizer_is_built_with_its_parameters(
    optimizer: Optimizer, kind: type
) -> None:
    built = build_optimizer(
        optimizer,
        default_params(optimizer),
        metric=metric,
        prompt_model=dspy.LM("openai/x"),
    )

    assert isinstance(built, kind)


def test_mipro_uses_trials_only_when_auto_is_off() -> None:
    params = default_params(Optimizer.MIPRO) | {"auto": "off", "num_trials": 5}

    kwargs = compile_kwargs(Optimizer.MIPRO, params, trainset=[1, 2], valset=[])

    assert kwargs["num_trials"] == 5
    assert kwargs["minibatch"] is False
    assert "num_trials" not in compile_kwargs(
        Optimizer.MIPRO, default_params(Optimizer.MIPRO), trainset=[1], valset=[]
    )
