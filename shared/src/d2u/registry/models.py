from datetime import datetime
from enum import StrEnum

from plain import postgres
from plain.postgres import Field, types

from d2u.generation.client import ModelSpec
from d2u.generation.prompts import (
    PROMPT_STRATEGIES,
    DocsExample,
    PageExample,
    PromptSpec,
)


class PromptStatus(StrEnum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    ACTIVE = "active"


def _choices(values: tuple[str, ...]) -> list[tuple[str, str]]:
    return [(value, value) for value in values]


@postgres.register_model
class ModelConfig(postgres.Model):
    """A model that can generate pages or judge evals (SPEC §7).

    `api_key_env` names the environment variable holding the key; the key
    itself is never stored.
    """

    name: Field[str] = types.TextField(max_length=100)
    litellm_model: Field[str] = types.TextField(max_length=200)
    api_key_env: Field[str] = types.TextField(
        max_length=100, required=False, default=""
    )
    api_base: Field[str] = types.TextField(max_length=500, required=False, default="")
    params: Field[dict] = types.JSONField(required=False, default={})
    max_input_tokens: Field[int] = types.IntegerField(default=128000)
    enabled_for_generation: Field[bool] = types.BooleanField(default=True)
    enabled_for_judging: Field[bool] = types.BooleanField(default=False)
    notes: Field[str] = types.TextField(required=False, default="")
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    updated_at: Field[datetime] = types.DateTimeField(create_now=True, update_now=True)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["name"], name="registry_modelconfig_name_unique"
            ),
        ],
    )

    def __str__(self) -> str:
        return self.name

    def to_spec(self) -> ModelSpec:
        """What the LLM client needs from this model."""
        return ModelSpec(
            name=self.name,
            litellm_model=self.litellm_model,
            api_key_env=self.api_key_env,
            api_base=self.api_base,
            params=dict(self.params),
            max_input_tokens=self.max_input_tokens,
        )


@postgres.register_model
class PromptVersion(postgres.Model):
    """Instructions and few-shot examples for one language and strategy (SPEC §8).

    Exactly one version per language and strategy is active.
    """

    language: Field[str] = types.TextField(max_length=32)
    strategy: Field[str] = types.TextField(
        max_length=16, choices=_choices(PROMPT_STRATEGIES)
    )
    version: Field[str] = types.TextField(max_length=64)
    instructions: Field[str] = types.TextField()
    examples: Field[list] = types.JSONField(required=False, default=[])
    status: Field[str] = types.TextField(
        max_length=16,
        choices=_choices(tuple(status.value for status in PromptStatus)),
        default=PromptStatus.DRAFT.value,
    )
    source: Field[str] = types.TextField(
        max_length=100, required=False, default="manual"
    )
    scores: Field[dict] = types.JSONField(required=False, default={})
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    promoted_at: Field[datetime | None] = types.DateTimeField(
        allow_null=True, required=False, default=None
    )

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["language", "strategy", "version"],
                name="registry_promptversion_language_strategy_version_unique",
            ),
            postgres.UniqueConstraint(
                fields=["language", "strategy"],
                condition=postgres.Q(status=PromptStatus.ACTIVE.value),
                name="registry_promptversion_one_active_unique",
            ),
        ],
    )

    def __str__(self) -> str:
        return f"{self.language}/{self.strategy}/{self.version}"

    def to_spec(self) -> PromptSpec:
        """The prompt as the generation code uses it, with validated examples."""
        page_examples: list[PageExample] = []
        docs_examples: list[DocsExample] = []
        if self.strategy == "llm":
            page_examples = [PageExample.model_validate(item) for item in self.examples]
        else:
            docs_examples = [DocsExample.model_validate(item) for item in self.examples]
        return PromptSpec(
            language=self.language,
            strategy="llm" if self.strategy == "llm" else "hybrid",
            version=self.version,
            instructions=self.instructions,
            page_examples=page_examples,
            docs_examples=docs_examples,
        )


@postgres.register_model
class RuntimeSettings(postgres.Model):
    """Runtime choices shared by both apps. There is one row.

    Edited only in the Tuning app (SPEC §19).
    """

    key: Field[str] = types.TextField(max_length=16, default="default")
    active_model: Field[ModelConfig | None] = types.ForeignKeyField(
        ModelConfig,
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
        related_query_name="settings_as_active_model",
    )
    default_judge_model: Field[ModelConfig | None] = types.ForeignKeyField(
        ModelConfig,
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
        related_query_name="settings_as_default_judge",
    )
    trace_backends: Field[list] = types.JSONField(required=False, default=["native"])
    updated_at: Field[datetime] = types.DateTimeField(create_now=True, update_now=True)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["key"], name="registry_runtimesettings_key_unique"
            ),
        ],
        indexes=[
            postgres.Index(
                fields=["active_model"],
                name="registry_runtimesettings_active_model_idx",
            ),
            postgres.Index(
                fields=["default_judge_model"],
                name="registry_runtimesettings_default_judge_model_idx",
            ),
        ],
    )

    def __str__(self) -> str:
        return "Runtime settings"

    @classmethod
    def load(cls) -> RuntimeSettings:
        """The settings row, created with defaults if it doesn't exist."""
        settings, _ = cls.query.get_or_create(key="default")
        return settings


class PromotionKind(StrEnum):
    PROMOTE = "promote"
    ROLLBACK = "rollback"


@postgres.register_model
class PromptPromotion(postgres.Model):
    """A record of a prompt version becoming active (SPEC §8).

    `previous` is the version it replaced, so a promotion can be rolled back.
    """

    language: Field[str] = types.TextField(max_length=32)
    strategy: Field[str] = types.TextField(max_length=16)
    prompt_version: Field[PromptVersion] = types.ForeignKeyField(
        PromptVersion, on_delete=postgres.RESTRICT, related_query_name="promotions"
    )
    previous: Field[PromptVersion | None] = types.ForeignKeyField(
        PromptVersion,
        on_delete=postgres.RESTRICT,
        allow_null=True,
        required=False,
        default=None,
        related_query_name="replaced_by",
    )
    kind: Field[str] = types.TextField(
        max_length=16,
        choices=_choices(tuple(kind.value for kind in PromotionKind)),
        default=PromotionKind.PROMOTE.value,
    )
    scores: Field[dict] = types.JSONField(required=False, default={})
    note: Field[str] = types.TextField(required=False, default="")
    created_at: Field[datetime] = types.DateTimeField(create_now=True)

    model_options = postgres.Options(
        indexes=[
            postgres.Index(
                fields=["language", "strategy", "created_at"],
                name="registry_promptpromotion_language_strategy_created_idx",
            ),
            postgres.Index(
                fields=["prompt_version"],
                name="registry_promptpromotion_prompt_version_idx",
            ),
            postgres.Index(
                fields=["previous"], name="registry_promptpromotion_previous_idx"
            ),
        ],
    )

    def __str__(self) -> str:
        return f"{self.kind} {self.prompt_version}"
