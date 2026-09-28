"""Seed metrics v1 with the default weights from SPEC §9.5."""

from typing import Any

from plain.postgres import migrations

# Copied here so later changes to the defaults don't rewrite history.
WEIGHTS = {
    "faithfulness": 0.30,
    "component_accuracy": 0.30,
    "coverage": 0.10,
    "example_validity": 0.10,
    "prose_quality": 0.20,
}
COMPONENT_WEIGHTS = {
    "operations": 0.30,
    "param_names": 0.15,
    "param_locations": 0.10,
    "param_types": 0.10,
    "param_required": 0.10,
    "param_defaults": 0.05,
    "returns": 0.05,
    "signatures": 0.10,
    "groups": 0.05,
}


def seed(models: Any, schema_editor: Any) -> None:
    models.get_model("evals", "MetricVersion").query.create(
        version=1,
        weights=WEIGHTS,
        component_weights=COMPONENT_WEIGHTS,
        notes="Default weights (SPEC §9.5).",
    )


class Migration(migrations.Migration):
    dependencies = (("evals", "0001_initial"),)

    operations = (migrations.RunPython(seed),)
