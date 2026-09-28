"""Seed the registry: two models, the settings row and the baseline prompts (SPEC §7, §8)."""

from typing import Any

from plain.postgres import migrations

from d2u.generation.prompts import LANGUAGES, PROMPT_STRATEGIES, baseline_instructions


def seed(models: Any, schema_editor: Any) -> None:
    model_config = models.get_model("registry", "ModelConfig")
    prompt_version = models.get_model("registry", "PromptVersion")
    runtime_settings = models.get_model("registry", "RuntimeSettings")

    gemini = model_config.query.create(
        name="Gemini 3.8 Flash",
        litellm_model="gemini/gemini-3.8-flash",
        api_key_env="GEMINI_API_KEY",
        params={"reasoning_effort": "medium"},
        max_input_tokens=1048576,
        enabled_for_generation=True,
        enabled_for_judging=False,
        notes="Seeded default generation model.",
    )
    claude = model_config.query.create(
        name="Claude Sonnet 4.5",
        litellm_model="anthropic/claude-sonnet-4-5",
        api_key_env="ANTHROPIC_API_KEY",
        params={"max_tokens": 32000},
        max_input_tokens=200000,
        enabled_for_generation=True,
        enabled_for_judging=True,
        notes="Seeded default judge: a different provider from the generation model.",
    )
    runtime_settings.query.create(
        key="default",
        active_model=gemini,
        default_judge_model=claude,
        trace_backends=["native"],
    )
    for language in LANGUAGES:
        for strategy in PROMPT_STRATEGIES:
            prompt_version.query.create(
                language=language,
                strategy=strategy,
                version="baseline",
                instructions=baseline_instructions(language, strategy),
                examples=[],
                status="active",
                source="seed",
            )


class Migration(migrations.Migration):
    dependencies = (("registry", "0001_initial"),)

    operations = (migrations.RunPython(seed),)
