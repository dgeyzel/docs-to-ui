import json
from io import BytesIO

import pytest
from d2u.registry.lookups import require_active_prompt
from d2u.registry.models import PromptPromotion, PromptVersion
from plain.test import Client

from app.evals.models import EvalRun, MetricVersion
from app.goldsets.models import GoldSet

pytestmark = pytest.mark.usefixtures("db")

EXAMPLE = {
    "input_files": {"api.yaml": "openapi: 3.0.0"},
    "output": {"title": "API", "overview_md": "", "operations": []},
}


def baseline(language: str = "openapi", strategy: str = "llm") -> PromptVersion:
    return PromptVersion.query.get(
        language=language, strategy=strategy, version="baseline"
    )


def new_draft(version: str = "v2") -> PromptVersion:
    Client().post(
        "/tuning/prompts",
        data={"form": "new", "base": str(baseline().id), "version": version},
    )
    return PromptVersion.query.get(language="openapi", strategy="llm", version=version)


def save(
    prompt: PromptVersion, *, instructions: str = "Be brief.", examples: str = "[]"
):
    return Client().post(
        f"/tuning/prompts/{prompt.id}",
        data={"form": "save", "instructions": instructions, "examples": examples},
    )


def promote(prompt: PromptVersion, **fields: str):
    data = {"form": "promote", "eval_run": "", "note": ""} | fields
    return Client().post(f"/tuning/prompts/{prompt.id}", data=data)


def test_the_list_shows_every_language_and_strategy() -> None:
    html = Client().get("/tuning/prompts").content.decode()

    for group in (
        "openapi · llm",
        "openapi · hybrid",
        "python · llm",
        "python · hybrid",
    ):
        assert group in html


def test_a_new_draft_copies_its_base() -> None:
    draft = new_draft()

    assert draft.status == "draft"
    assert draft.source == "manual"
    assert draft.instructions == baseline().instructions


@pytest.mark.parametrize(
    ("label", "message"),
    [("V 2!", "Use lowercase letters"), ("baseline", "already exists")],
)
def test_bad_labels_are_rejected(label: str, message: str) -> None:
    response = Client().post(
        "/tuning/prompts",
        data={"form": "new", "base": str(baseline().id), "version": label},
    )

    assert response.status_code == 422
    assert message in response.content.decode()


def test_a_draft_is_saved_with_validated_examples() -> None:
    draft = new_draft()

    response = save(draft, examples=json.dumps([EXAMPLE]))

    draft = PromptVersion.query.get(draft.id)
    assert response.headers["Location"].endswith("?message=saved")
    assert draft.instructions == "Be brief."
    assert draft.to_spec().page_examples[0].input_files == {
        "api.yaml": "openapi: 3.0.0"
    }


@pytest.mark.parametrize(
    ("examples", "message"),
    [
        ("[{", "Not valid JSON"),
        (json.dumps([{"input_files": {}}]), "page_examples.0.output: Field required"),
    ],
)
def test_invalid_examples_are_shown_without_saving(examples: str, message: str) -> None:
    draft = new_draft()

    response = save(draft, examples=examples)

    assert response.status_code == 422
    assert message in response.content.decode()
    assert PromptVersion.query.get(draft.id).instructions == baseline().instructions


def test_only_drafts_can_be_edited() -> None:
    response = save(baseline())

    assert response.status_code == 422
    assert "Only drafts can be edited" in response.content.decode()


def test_promotion_makes_a_version_active_and_records_what_it_replaced() -> None:
    draft = new_draft()

    response = promote(draft, note="Shorter.")

    draft = PromptVersion.query.get(draft.id)
    assert response.headers["Location"].endswith("?message=promoted")
    assert draft.status == "active"
    assert draft.promoted_at is not None
    assert baseline().status == "candidate"
    assert require_active_prompt(language="openapi", strategy="llm").id == draft.id
    promotion = PromptPromotion.query.get(prompt_version=draft)
    assert promotion.previous is not None
    assert (promotion.kind, promotion.previous.id, promotion.note) == (
        "promote",
        baseline().id,
        "Shorter.",
    )


def test_promotion_copies_the_scores_of_the_chosen_eval_run() -> None:
    draft = new_draft()
    gold_set = GoldSet(name="Pets", language="openapi")
    gold_set.create()
    run = EvalRun(
        gold_set=gold_set,
        split="dev",
        strategy="llm",
        prompt_version=draft,
        metric_version=MetricVersion.query.get(version=1),
        status="succeeded",
        summary={
            "total": {"total": {"mean": 0.8, "low": 0.7, "high": 0.9}},
            "metrics": {"coverage": {"mean": 1.0, "low": 1.0, "high": 1.0}},
        },
    )
    run.create()

    promote(draft, eval_run=str(run.id))

    scores = PromptVersion.query.get(draft.id).scores
    assert scores["eval_run"] == run.id
    assert scores["total"] == 0.8
    assert scores["metrics"] == {"coverage": 1.0}
    assert PromptPromotion.query.get(prompt_version=draft).scores == scores


def test_an_active_version_cannot_be_promoted_again() -> None:
    response = promote(baseline())

    assert response.status_code == 422
    assert "already active" in response.content.decode()


def test_a_promotion_is_rolled_back_with_one_click() -> None:
    draft = new_draft()
    promote(draft)
    assert "Roll back to baseline" in Client().get("/tuning/prompts").content.decode()

    response = Client().post(
        "/tuning/prompts",
        data={"form": "rollback", "language": "openapi", "strategy": "llm"},
    )

    assert response.headers["Location"].endswith("?message=rolled_back")
    assert baseline().status == "active"
    assert PromptVersion.query.get(draft.id).status == "candidate"
    rollback = PromptPromotion.query.order_by("-id").first()
    assert rollback is not None
    assert (rollback.kind, rollback.note) == ("rollback", "Rolled back from v2")


def test_there_is_nothing_to_roll_back_before_any_promotion() -> None:
    response = Client().post(
        "/tuning/prompts",
        data={"form": "rollback", "language": "python", "strategy": "llm"},
    )

    assert response.status_code == 422
    assert "Nothing to roll back" in response.content.decode()


def test_two_versions_are_diffed() -> None:
    draft = new_draft()
    save(draft, instructions="Be brief.\nUse examples.")

    html = (
        Client()
        .get(f"/tuning/prompts/diff?a={baseline().id}&b={draft.id}")
        .content.decode()
    )

    assert 'class="diff-line diff-line-added">+ Be brief.' in html
    assert "diff-line-removed" in html


def test_an_exported_version_imports_as_a_draft() -> None:
    exported = json.loads(
        Client().get(f"/tuning/prompts/{baseline().id}/export").content
    )
    upload = BytesIO(json.dumps(exported | {"version": "copy"}).encode())
    upload.name = "prompt.json"

    response = Client().post("/tuning/prompts", data={"form": "import", "file": upload})

    imported = PromptVersion.query.get(
        language="openapi", strategy="llm", version="copy"
    )
    assert (
        response.headers["Location"]
        == f"/tuning/prompts/{imported.id}?message=imported"
    )
    assert (imported.status, imported.source) == ("draft", "imported")
    assert imported.instructions == baseline().instructions


def test_invalid_import_files_are_rejected() -> None:
    upload = BytesIO(b'{"language": "openapi"}')
    upload.name = "prompt.json"

    response = Client().post("/tuning/prompts", data={"form": "import", "file": upload})

    assert response.status_code == 422
    assert "Not a valid prompt version file" in response.content.decode()
