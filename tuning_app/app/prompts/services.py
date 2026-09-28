"""Creating, editing, promoting and rolling back prompt versions (SPEC §8)."""

import re
from datetime import UTC, datetime

from d2u.generation.prompts import PromptSpec
from d2u.registry.models import (
    PromotionKind,
    PromptPromotion,
    PromptStatus,
    PromptVersion,
)
from plain.postgres import transaction

from app.prompts.exceptions import PromptError

VERSION_LABEL = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def check_label(language: str, strategy: str, version: str) -> None:
    """Raise if a version label is malformed or taken for the language and strategy.

    Raises:
        PromptError: It is.
    """
    if not VERSION_LABEL.match(version):
        raise PromptError(
            "Use lowercase letters, digits, dots, dashes or underscores, e.g. v3."
        )
    if PromptVersion.query.filter(
        language=language, strategy=strategy, version=version
    ).exists():
        raise PromptError(f"{language}/{strategy}/{version} already exists.")


def create_draft(base: PromptVersion, *, version: str) -> PromptVersion:
    """A new draft copying another version's instructions and examples.

    Raises:
        PromptError: The label is malformed or taken.
    """
    check_label(base.language, base.strategy, version)
    draft = PromptVersion(
        language=base.language,
        strategy=base.strategy,
        version=version,
        instructions=base.instructions,
        examples=list(base.examples),
        status=PromptStatus.DRAFT.value,
        source="manual",
    )
    draft.create()
    return draft


def spec_examples(spec: PromptSpec) -> list[dict]:
    """A spec's examples in the stored form for its strategy."""
    examples = spec.page_examples if spec.strategy == "llm" else spec.docs_examples
    return [example.model_dump(mode="json") for example in examples]


def save_draft(prompt: PromptVersion, spec: PromptSpec) -> None:
    """Store edited instructions and examples on a draft.

    Raises:
        PromptError: The version isn't a draft.
    """
    if prompt.status != PromptStatus.DRAFT:
        raise PromptError(
            "Only drafts can be edited. Copy this version to a new draft."
        )
    prompt.instructions = spec.instructions
    prompt.examples = spec_examples(spec)
    prompt.update(fields=["instructions", "examples"])


def import_version(spec: PromptSpec, *, source: str = "imported") -> PromptVersion:
    """A draft from an imported (or exported) prompt version.

    Raises:
        PromptError: The label is malformed or taken.
    """
    check_label(spec.language, spec.strategy, spec.version)
    prompt = PromptVersion(
        language=spec.language,
        strategy=spec.strategy,
        version=spec.version,
        instructions=spec.instructions,
        examples=spec_examples(spec),
        status=PromptStatus.DRAFT.value,
        source=source,
    )
    prompt.create()
    return prompt


def promote(
    prompt: PromptVersion,
    *,
    scores: dict | None = None,
    note: str = "",
    kind: PromotionKind = PromotionKind.PROMOTE,
) -> PromptPromotion:
    """Make a version active for its language and strategy, and record it.

    The previously active version becomes a candidate. `scores` (for
    example, the dev-set means of the eval run that justified promotion) are
    copied onto the version and the promotion.

    Raises:
        PromptError: The version is already active.
    """
    if prompt.status == PromptStatus.ACTIVE:
        raise PromptError(f"{prompt} is already active.")
    with transaction.atomic():
        previous = PromptVersion.query.get_or_none(
            language=prompt.language,
            strategy=prompt.strategy,
            status=PromptStatus.ACTIVE.value,
        )
        if previous is not None:
            # First, so the one-active-per-pair constraint holds at every step.
            previous.status = PromptStatus.CANDIDATE.value
            previous.update(fields=["status"])
        prompt.status = PromptStatus.ACTIVE.value
        prompt.promoted_at = datetime.now(UTC)
        fields = ["status", "promoted_at"]
        if scores:
            prompt.scores = scores
            fields.append("scores")
        prompt.update(fields=fields)
        promotion = PromptPromotion(
            language=prompt.language,
            strategy=prompt.strategy,
            prompt_version=prompt,
            previous=previous,
            kind=kind.value,
            scores=scores or {},
            note=note,
        )
        promotion.create()
    return promotion


def latest_promotion(language: str, strategy: str) -> PromptPromotion | None:
    """The most recent promotion (or rollback) for a language and strategy."""
    return (
        PromptPromotion.query.filter(language=language, strategy=strategy)
        .order_by("-created_at", "-id")
        .first()
    )


def rollback_target(language: str, strategy: str) -> PromptVersion | None:
    """The version a rollback would restore: the one the latest promotion replaced."""
    promotion = latest_promotion(language, strategy)
    if promotion is None or promotion.previous is None:
        return None
    return promotion.previous


def rollback(language: str, strategy: str) -> PromptPromotion:
    """Reactivate the version the latest promotion replaced.

    Raises:
        PromptError: There is nothing to roll back to.
    """
    promotion = latest_promotion(language, strategy)
    if promotion is None or promotion.previous is None:
        raise PromptError(f"Nothing to roll back for {language}/{strategy}.")
    return promote(
        promotion.previous,
        kind=PromotionKind.ROLLBACK,
        note=f"Rolled back from {promotion.prompt_version.version}",
    )
