"""Creating, curating and hashing gold examples (SPEC §9.2)."""

import hashlib
import json
import logging
import time

import psycopg
from d2u.generation.client import FakeResponses
from d2u.generation.runner import generate_for_bundle
from d2u.generation.strategies import GenerationConfig
from d2u.generations.fakes import fake_responses
from d2u.generations.inputs import available_adapters, prepare_raw_input
from d2u.generations.models import Feedback, Generation, GenerationStatus, InputOrigin
from d2u.registry.lookups import require_active_prompt
from d2u.registry.models import ModelConfig
from d2u.schemas.docpage import ApiSurface, DocPage, Overview
from d2u.schemas.gold import GoldInput, GoldSetFile
from d2u.sources.adapters.base import LanguageAdapter
from d2u.sources.bundle import SourceBundle, SourceFile
from d2u.sources.exceptions import InputError
from d2u.sources.intake import RawInput
from d2u.sources.registry import get_adapter
from plain.postgres import transaction
from plain.runtime import settings

from app.goldsets.exceptions import GoldSetError
from app.goldsets.models import (
    ExampleStatus,
    GoldExample,
    GoldExampleRevision,
    GoldSet,
    SeedStatus,
)

logger = logging.getLogger(__name__)
MAX_ERROR_CHARS = 500


def describe_input_error(exc: InputError) -> str:
    """An input error with its file and line, e.g. `api.yaml:3: bad indentation`."""
    if exc.path and exc.line:
        return f"{exc.path}:{exc.line}: {exc.message}"
    if exc.path:
        return f"{exc.path}: {exc.message}"
    return exc.message


def adapter_for(language: str) -> LanguageAdapter:
    """The enabled adapter for a gold set's language.

    Raises:
        GoldSetError: The language isn't enabled.
    """
    try:
        return get_adapter(name=language, adapters=available_adapters())
    except InputError as exc:
        raise GoldSetError(f"The {language!r} language isn't enabled.") from exc


def bundle_of(gold_input: GoldInput) -> SourceBundle:
    """The example's files as a bundle, in path order."""
    return SourceBundle(
        files=[
            SourceFile(path=path, text=text)
            for path, text in sorted(gold_input.files.items())
        ],
        origin=gold_input.origin,
        entry=gold_input.entry,
    )


def line_counts(gold_input: GoldInput) -> dict[str, int]:
    """Each file's line count, for dropping source locations that don't exist."""
    return {path: text.count("\n") + 1 for path, text in gold_input.files.items()}


def gold_input_from_raw(raw: RawInput) -> GoldInput:
    """Bundle submitted input exactly as the Docs app would.

    Raises:
        InputError: The input can't be read as the requested language.
    """
    prepared = prepare_raw_input(raw)
    return GoldInput(
        origin=raw.origin,
        files={file.path: file.text for file in prepared.bundle.files},
        entry=raw.entry or None,
    )


def empty_page(language: str, gold_input: GoldInput) -> DocPage:
    """An expected page with no operations yet, to fill in by hand."""
    return DocPage(
        strategy="llm",
        surface=ApiSurface(
            title=gold_input.entry or min(gold_input.files),
            language=language,
            operations=[],
        ),
        overview=Overview(overview_md="", groups={}),
        operations=[],
    )


def parser_page(language: str, gold_input: GoldInput) -> DocPage:
    """The `parser` strategy's page for an input: structure and source descriptions.

    Raises:
        InputError: The input doesn't parse.
        GoldSetError: The language isn't enabled.
    """
    result = generate_for_bundle(
        strategy="parser",
        bundle=bundle_of(gold_input),
        adapter=adapter_for(language),
        config=GenerationConfig(),
    )
    return result.page


def record_revision(example: GoldExample, change: str) -> None:
    """Snapshot the example after a change."""
    GoldExampleRevision(
        example=example,
        change=change,
        expected=example.expected,
        split=example.split,
        status=example.status,
        notes=example.notes,
    ).create()


def create_example(
    gold_set: GoldSet,
    *,
    gold_input: GoldInput,
    expected: DocPage,
    source: str,
    notes: str = "",
    split: str = "train",
    status: str = ExampleStatus.DRAFT.value,
    change: str = "Created",
) -> GoldExample:
    """Add an example to a set and record its first revision."""
    with transaction.atomic():
        example = GoldExample(
            gold_set=gold_set,
            input=gold_input.model_dump(mode="json"),
            expected=expected.model_dump(mode="json"),
            source=source,
            notes=notes,
            split=split,
            status=status,
        )
        example.create()
        record_revision(example, change)
    return example


def save_expected(example: GoldExample, page: DocPage, *, change: str) -> None:
    """Store a new expected page and record the revision."""
    with transaction.atomic():
        example.expected = page.model_dump(mode="json")
        example.update(fields=["expected", "updated_at"])
        record_revision(example, change)


def save_review(example: GoldExample, *, split: str, notes: str) -> None:
    """Store the split and reviewer notes, recording a revision if they changed."""
    if (example.split, example.notes) == (split, notes):
        return
    with transaction.atomic():
        example.split = split
        example.notes = notes
        example.update(fields=["split", "notes", "updated_at"])
        record_revision(example, "Review details changed")


def set_status(example: GoldExample, status: ExampleStatus) -> None:
    """Approve an example or return it to draft.

    Raises:
        GoldSetError: Approving an example that is still being seeded or has
            no operations.
    """
    if status == ExampleStatus.APPROVED:
        if example.seeding:
            raise GoldSetError("Wait for the model to finish filling in the page.")
        if not example.expected_page().surface.operations:
            raise GoldSetError(
                "An example needs at least one operation to be approved."
            )
    if example.status == status:
        return
    with transaction.atomic():
        example.status = status.value
        example.update(fields=["status", "updated_at"])
        record_revision(
            example,
            "Approved" if status == ExampleStatus.APPROVED else "Returned to draft",
        )


def assign_split(gold_set: GoldSet, example_ids: list[int], split: str) -> int:
    """Move examples of a set to a split; returns how many changed."""
    changed = 0
    with transaction.atomic():
        for example in GoldExample.query.filter(gold_set=gold_set, id__in=example_ids):
            if example.split == split:
                continue
            example.split = split
            example.update(fields=["split", "updated_at"])
            record_revision(example, f"Moved to {split}")
            changed += 1
    return changed


def content_hash(gold_set: GoldSet) -> str:
    """A hash of the set's approved examples (input, expected page and split).

    Recorded on every run that uses the set, so results can be tied to the
    exact examples they were measured on.
    """
    examples = GoldExample.query.filter(
        gold_set=gold_set, status=ExampleStatus.APPROVED.value
    ).order_by("id")
    canonical = json.dumps(
        [
            {"input": ex.input, "expected": ex.expected, "split": ex.split}
            for ex in examples
        ],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def import_generation(
    gold_set: GoldSet,
    generation: Generation,
    *,
    source: str = "",
    notes: str = "",
    change: str = "",
) -> GoldExample:
    """A draft example from a finished Docs app generation: its input and page.

    `source` and `change` default to naming the generation.

    Raises:
        GoldSetError: The generation didn't succeed or is in another language.
        InputError: The stored input can't be read again.
    """
    if generation.status != GenerationStatus.SUCCEEDED or not generation.doc_json:
        raise GoldSetError("Only finished generations can be imported.")
    if generation.language != gold_set.language:
        raise GoldSetError(
            f"Generation {generation.id} is {generation.language}, "
            f"but this gold set is {gold_set.language}."
        )
    gold_input = gold_input_from_raw(
        RawInput(
            origin=InputOrigin(generation.input_origin).value,
            data=bytes(generation.input_blob),
            filename=generation.input_filename,
            language=gold_set.language,
            entry=generation.input_entry,
        )
    )
    return create_example(
        gold_set,
        gold_input=gold_input,
        expected=DocPage.model_validate(generation.doc_json),
        source=source or f"generation:{generation.id}",
        notes=notes,
        change=change or f"Imported from generation {generation.id}",
    )


def correctable_feedback(gold_set: GoldSet, *, limit: int) -> list[Feedback]:
    """Recent 👎 feedback with a correction, on finished generations in the set's language."""
    return list(
        Feedback.query.filter(
            score=-1,
            generation__status=GenerationStatus.SUCCEEDED.value,
            generation__language=gold_set.language,
        )
        .exclude(comment="")
        .join("generation")
        .order_by("-created_at")[:limit]
    )


def feedback_note(feedback: Feedback) -> str:
    """The correction as an example note, saying what it was about."""
    subject = (
        f"operation {feedback.operation_id}" if feedback.operation_id else "the page"
    )
    return f"👎 feedback on {subject}: {feedback.comment}"


def import_feedback(gold_set: GoldSet, feedback: Feedback) -> GoldExample:
    """A draft example from 👎 feedback: the generation's input and page, the
    correction kept as a note for the reviewer (SPEC §9.2).

    Raises:
        GoldSetError: The feedback isn't a 👎 with a correction, or its
            generation can't be imported into this set.
        InputError: The generation's stored input can't be read again.
    """
    if feedback.score != -1 or not feedback.comment.strip():
        raise GoldSetError("Only 👎 feedback with a correction can be imported.")
    return import_generation(
        gold_set,
        feedback.generation,
        source=f"feedback:{feedback.id}",
        notes=feedback_note(feedback),
        change=f"Imported from feedback {feedback.id}",
    )


def import_gold_set(data: GoldSetFile) -> GoldSet:
    """Create a gold set from an import file.

    Raises:
        GoldSetError: The name is taken, the language isn't enabled, or an
            example's page is in another language.
    """
    adapter_for(data.language)
    if GoldSet.query.filter(name=data.name).exists():
        raise GoldSetError(f"A gold set named {data.name!r} already exists.")
    for index, example in enumerate(data.examples, start=1):
        if example.expected.surface.language != data.language:
            raise GoldSetError(
                f"Example {index} documents {example.expected.surface.language}, "
                f"but the set is {data.language}."
            )
    with transaction.atomic():
        gold_set = GoldSet(name=data.name, language=data.language)
        gold_set.create()
        for example in data.examples:
            create_example(
                gold_set,
                gold_input=example.input,
                expected=example.expected,
                source="imported",
                notes=example.notes,
                split=example.split,
                status=example.status,
                change="Imported",
            )
    return gold_set


def start_model_seed(example: GoldExample, model: ModelConfig) -> None:
    """Queue filling the example's expected page from a model.

    Raises:
        GoldSetError: The model isn't enabled for generation.
    """
    from app.goldsets.jobs import SeedGoldExampleJob

    if not model.enabled_for_generation:
        raise GoldSetError(f"{model.name} isn't enabled for generation.")
    GoldExample.query.filter(id=example.id).update(
        seed_status=SeedStatus.PENDING.value, seed_error=""
    )
    try:
        queued = SeedGoldExampleJob(example.id, model.id).run_in_worker()
    except psycopg.Error:
        logger.exception("Could not queue seeding for example %s", example.id)
        queued = None
    if queued is None:
        finish_seed(example.id, error="Seeding could not be queued. Try again.")


def claim_seed(example_id: int) -> GoldExample | None:
    """Move a pending seed to running; None if none is pending."""
    claimed = GoldExample.query.filter(
        id=example_id, seed_status=SeedStatus.PENDING.value
    ).update(seed_status=SeedStatus.RUNNING.value)
    if claimed == 0:
        return None
    return GoldExample.query.get(example_id)


def finish_seed(example_id: int, *, error: str = "") -> None:
    """End a pending or running seed, recording an error if it failed."""
    GoldExample.query.filter(
        id=example_id,
        seed_status__in=[SeedStatus.PENDING.value, SeedStatus.RUNNING.value],
    ).update(
        seed_status=SeedStatus.FAILED.value if error else SeedStatus.NONE.value,
        seed_error=error[:MAX_ERROR_CHARS],
    )


def run_model_seed(
    example: GoldExample, model: ModelConfig, *, fake: FakeResponses | None = None
) -> None:
    """Generate the page with the `llm` strategy and store it as the expected page.

    Uses the active `llm` prompt for the set's language, through the same
    generation code as the Docs app.

    Raises:
        InputError, LLMConfigurationError, ProviderError, OutputValidationError,
            GenerationTimeoutError: The generation failed.
    """
    language = example.gold_set.language
    prompt = require_active_prompt(language=language, strategy="llm")
    result = generate_for_bundle(
        strategy="llm",
        bundle=bundle_of(example.gold_input()),
        adapter=adapter_for(language),
        model=model.to_spec(),
        prompt=prompt.to_spec(),
        config=GenerationConfig(
            max_concurrency=settings.GENERATIONS_MAX_CONCURRENCY,
            deadline=time.monotonic() + settings.GENERATIONS_TIMEOUT_S,
            fake=fake if fake is not None else fake_responses(),
        ),
    )
    with transaction.atomic():
        example.expected = result.page.model_dump(mode="json")
        example.source = "model_seed"
        example.update(fields=["expected", "source", "updated_at"])
        record_revision(example, f"Filled in by {model.name}")
    finish_seed(example.id)
