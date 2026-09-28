import json
from io import BytesIO

import pytest
from d2u.generations.models import Generation
from d2u.registry.models import ModelConfig
from d2u.schemas.docpage import DocPage
from plain.jobs.models import JobRequest
from plain.test import Client

from app.goldsets import jobs
from app.goldsets.models import GoldExample, GoldExampleRevision, GoldSet
from app.goldsets.services import content_hash
from tests.helpers import FIXTURES_DIR, read_fixture, zip_dir

pytestmark = pytest.mark.usefixtures("db")

PETSTORE = read_fixture("openapi/petstore-3.0.yaml")


def make_set(name: str = "Pets", language: str = "openapi") -> GoldSet:
    Client().post(
        "/tuning/goldsets", data={"form": "create", "name": name, "language": language}
    )
    return GoldSet.query.get(name=name)


def add_example(
    gold_set: GoldSet, *, fill: str = "parser", text: str = PETSTORE, **extra: str
):
    data = {"text": text, "entry": "", "fill": fill, "model": "", "notes": ""} | extra
    return Client().post(f"/tuning/goldsets/{gold_set.id}/examples/new", data=data)


def only_example(gold_set: GoldSet) -> GoldExample:
    return GoldExample.query.get(gold_set=gold_set)


def example_url(example: GoldExample) -> str:
    return f"/tuning/goldsets/{example.gold_set.id}/examples/{example.id}"


def editor_form(example: GoldExample, **overrides: str) -> dict[str, str]:
    """The editor's form data for an example's current page."""
    from app.goldsets import editor

    state = editor.state_from_page(example.expected_page())
    data = {
        "form": "editor",
        "action": "save",
        "title": state["title"],
        "overview_md": state["overview_md"],
        "op-count": str(len(state["operations"])),
    }
    for i, op in enumerate(state["operations"]):
        data |= {f"op-{i}-{name}": op[name] for name in editor.OPERATION_FIELDS}
        data[f"op-{i}-param-count"] = str(len(op["params"]))
        data[f"op-{i}-example-count"] = str(len(op["examples"]))
        for j, param in enumerate(op["params"]):
            data |= {
                f"op-{i}-param-{j}-{name}": param[name] for name in editor.PARAM_FIELDS
            }
            if param["required"]:
                data[f"op-{i}-param-{j}-required"] = "true"
        for k, code_example in enumerate(op["examples"]):
            data |= {
                f"op-{i}-example-{k}-{name}": code_example[name]
                for name in editor.EXAMPLE_FIELDS
            }
    return data | overrides


def run_queued_seed() -> None:
    request = JobRequest.query.get(job_class="app.goldsets.jobs.SeedGoldExampleJob")
    assert request.parameters is not None
    jobs.SeedGoldExampleJob(
        *request.parameters["args"], **request.parameters["kwargs"]
    ).run()


def test_creating_a_gold_set_opens_it() -> None:
    response = Client().post(
        "/tuning/goldsets",
        data={"form": "create", "name": "Pets", "language": "openapi"},
    )

    gold_set = GoldSet.query.get(name="Pets")
    assert response.headers["Location"] == f"/tuning/goldsets/{gold_set.id}"
    assert "Pets" in Client().get("/tuning/goldsets").content.decode()


def test_gold_set_names_are_unique() -> None:
    make_set()

    response = Client().post(
        "/tuning/goldsets",
        data={"form": "create", "name": "Pets", "language": "python"},
    )

    assert response.status_code == 422
    assert "already exists" in response.content.decode()


def test_pasted_source_seeded_from_the_parser_becomes_a_draft_example() -> None:
    gold_set = make_set()

    response = add_example(gold_set, notes="From the fixture.")

    example = only_example(gold_set)
    assert response.headers["Location"] == f"{example_url(example)}?message=created"
    assert (example.status, example.split, example.source) == (
        "draft",
        "train",
        "parser_seed",
    )
    assert example.gold_input().files == {"input.yaml": PETSTORE}
    assert "GET /pets" in {op.id for op in example.expected_page().surface.operations}
    assert example.notes == "From the fixture."
    assert (
        GoldExampleRevision.query.get(example=example).change
        == "Seeded from the parser"
    )


def test_an_empty_example_has_no_operations() -> None:
    gold_set = make_set()

    add_example(gold_set, fill="empty")

    page = only_example(gold_set).expected_page()
    assert page.surface.operations == []
    assert page.surface.language == "openapi"


def test_a_zip_is_read_like_the_docs_app_reads_it() -> None:
    gold_set = make_set("Acme", "python")
    archive = BytesIO(zip_dir(FIXTURES_DIR / "python/acme", prefix="acme/"))
    archive.name = "acme.zip"

    Client().post(
        f"/tuning/goldsets/{gold_set.id}/examples/new",
        data={
            "file": archive,
            "text": "",
            "entry": "",
            "fill": "parser",
            "model": "",
            "notes": "",
        },
    )

    gold_input = only_example(gold_set).gold_input()
    assert gold_input.origin == "zip"
    assert "src/acme/client.py" in gold_input.files
    assert "pyproject.toml" not in gold_input.files


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"text": ""}, "Upload a file or paste some text."),
        ({"text": "openapi: 3.0.0\npaths: [broken"}, "input.yaml"),
        ({"fill": "model"}, "Choose a model."),
    ],
)
def test_bad_example_input_is_rejected(fields: dict[str, str], message: str) -> None:
    gold_set = make_set()

    response = add_example(gold_set, **fields)

    assert response.status_code in (200, 422)
    assert message in response.content.decode()
    assert not GoldExample.query.filter(gold_set=gold_set).exists()


def test_seeding_from_a_model_runs_the_llm_strategy_in_a_job() -> None:
    gold_set = make_set()
    fake = ModelConfig.query.get(name="Fake")

    response = add_example(gold_set, fill="model", model=str(fake.id))

    example = only_example(gold_set)
    assert response.headers["Location"].endswith("?message=seeding")
    assert example.seed_status == "pending"
    assert (
        JobRequest.query.get(job_class="app.goldsets.jobs.SeedGoldExampleJob").queue
        == "tuning"
    )
    polling = Client().get(example_url(example) + "/seed")
    assert 'hx-trigger="every 2s"' in polling.content.decode()
    run_queued_seed()
    example = GoldExample.query.get(example.id)
    assert example.seed_status == ""
    assert example.source == "model_seed"
    assert example.expected_page().strategy == "llm"
    assert "Filled in by Fake" in [
        r.change for r in GoldExampleRevision.query.filter(example=example)
    ]
    assert Client().get(example_url(example) + "/seed").headers[
        "HX-Redirect"
    ] == example_url(example)


def test_a_failed_seed_is_shown_on_the_example(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    gold_set = make_set()
    claude = ModelConfig.query.get(name="Claude Sonnet 4.5")
    add_example(gold_set, fill="model", model=str(claude.id))

    run_queued_seed()

    example = only_example(gold_set)
    assert example.seed_status == "failed"
    assert "ANTHROPIC_API_KEY is not set" in example.seed_error
    assert (
        "Filling in from a model failed"
        in Client().get(example_url(example)).content.decode()
    )


def test_running_a_seed_job_twice_does_nothing_the_second_time() -> None:
    gold_set = make_set()
    add_example(
        gold_set, fill="model", model=str(ModelConfig.query.get(name="Fake").id)
    )
    run_queued_seed()
    revisions = GoldExampleRevision.query.count()

    run_queued_seed()

    assert GoldExampleRevision.query.count() == revisions


def test_saving_the_editor_derives_ids_in_code_and_records_a_revision() -> None:
    gold_set = make_set()
    add_example(gold_set)
    example = only_example(gold_set)

    response = Client().post(
        example_url(example),
        data=editor_form(
            example, **{"op-0-method": "delete", "op-0-summary": "Edited."}
        ),
    )

    page = GoldExample.query.get(example.id).expected_page()
    assert response.headers["Location"].endswith("?message=saved")
    assert page.surface.operations[0].id.startswith("DELETE /")
    assert page.operations[0].summary == "Edited."
    assert GoldExampleRevision.query.filter(example=example, change="Edited").exists()


def test_invalid_editor_input_is_shown_without_saving() -> None:
    gold_set = make_set()
    add_example(gold_set)
    example = only_example(gold_set)
    before = example.expected

    response = Client().post(
        example_url(example), data=editor_form(example, **{"op-0-summary": "x" * 201})
    )

    assert response.status_code == 422
    assert "at most 200 characters" in response.content.decode()
    assert GoldExample.query.get(example.id).expected == before


def test_editor_actions_change_the_form_without_saving() -> None:
    gold_set = make_set()
    add_example(gold_set, fill="empty")
    example = only_example(gold_set)

    response = Client().post(
        example_url(example), data=editor_form(example, action="add_operation")
    )

    html = response.content.decode()
    assert response.status_code == 200
    assert 'name="op-0-signature"' in html
    assert GoldExample.query.get(example.id).expected_page().surface.operations == []


def test_approval_needs_operations_and_is_recorded() -> None:
    gold_set = make_set()
    add_example(gold_set, fill="empty")
    empty = only_example(gold_set)

    refused = Client().post(example_url(empty), data={"form": "approve"})

    assert refused.status_code == 422
    assert "at least one operation" in refused.content.decode()
    add_example(gold_set)
    seeded = GoldExample.query.filter(gold_set=gold_set).order_by("-id").first()
    assert seeded is not None
    Client().post(example_url(seeded), data={"form": "approve"})
    assert GoldExample.query.get(seeded.id).status == "approved"
    Client().post(example_url(seeded), data={"form": "draft"})
    assert GoldExample.query.get(seeded.id).status == "draft"
    changes = [
        r.change
        for r in GoldExampleRevision.query.filter(example=seeded).order_by("id")
    ]
    assert changes[-2:] == ["Approved", "Returned to draft"]


def test_review_details_are_saved() -> None:
    gold_set = make_set()
    add_example(gold_set)
    example = only_example(gold_set)

    Client().post(
        example_url(example),
        data={"form": "review", "split": "dev", "notes": "Check auth."},
    )

    example = GoldExample.query.get(example.id)
    assert (example.split, example.notes) == ("dev", "Check auth.")


def test_filling_again_from_the_parser_replaces_the_page() -> None:
    gold_set = make_set()
    add_example(gold_set, fill="empty")
    example = only_example(gold_set)

    Client().post(
        example_url(example), data={"form": "fill", "fill": "parser", "model": ""}
    )

    assert GoldExample.query.get(example.id).expected_page().surface.operations


def test_bulk_split_assignment_moves_only_the_selected_examples() -> None:
    gold_set = make_set()
    add_example(gold_set)
    add_example(gold_set)
    first, second = GoldExample.query.filter(gold_set=gold_set).order_by("id")

    Client().post(
        f"/tuning/goldsets/{gold_set.id}",
        data={"form": "split", "examples": [str(second.id)], "split": "test"},
    )

    assert GoldExample.query.get(first.id).split == "train"
    assert GoldExample.query.get(second.id).split == "test"


def test_the_content_hash_covers_only_approved_examples() -> None:
    gold_set = make_set()
    add_example(gold_set)
    example = only_example(gold_set)
    empty_hash = content_hash(gold_set)

    Client().post(
        example_url(example), data={"form": "review", "split": "dev", "notes": ""}
    )
    assert content_hash(gold_set) == empty_hash
    Client().post(example_url(example), data={"form": "approve"})
    approved_hash = content_hash(gold_set)
    Client().post(
        example_url(example), data={"form": "review", "split": "test", "notes": ""}
    )

    assert approved_hash != empty_hash
    assert content_hash(gold_set) != approved_hash


def succeeded_generation() -> Generation:
    from d2u.schemas.gold import GoldInput

    from app.goldsets.services import parser_page

    page = parser_page(
        "openapi", GoldInput(origin="paste", files={"input.yaml": PETSTORE})
    )
    generation = Generation(
        language="openapi",
        input_origin="paste",
        input_blob=PETSTORE.encode(),
        input_sha256="0" * 64,
        input_bytes=len(PETSTORE),
        status="succeeded",
        doc_json=page.model_dump(mode="json"),
        model="Fake",
    )
    generation.create()
    return generation


def test_a_docs_app_generation_is_imported_as_a_draft() -> None:
    gold_set = make_set()
    generation = succeeded_generation()

    Client().post(
        f"/tuning/goldsets/{gold_set.id}",
        data={"form": "import_generation", "generation": str(generation.id)},
    )

    example = only_example(gold_set)
    assert example.source == f"generation:{generation.id}"
    assert example.expected == generation.doc_json
    assert example.gold_input().files == {"input.yaml": PETSTORE}
    assert (
        "Imported" in Client().get(f"/tuning/goldsets/{gold_set.id}").content.decode()
    )


def test_generations_in_another_language_cannot_be_imported() -> None:
    gold_set = make_set("Py", "python")
    generation = succeeded_generation()

    response = Client().post(
        f"/tuning/goldsets/{gold_set.id}",
        data={"form": "import_generation", "generation": str(generation.id)},
    )

    assert response.status_code == 422
    assert "is openapi, but this gold set is python" in response.content.decode()


def import_file(payload: object):
    upload = BytesIO(json.dumps(payload).encode())
    upload.name = "set.json"
    return Client().post("/tuning/goldsets", data={"form": "import", "file": upload})


def test_a_gold_set_file_is_imported() -> None:
    source = make_set("Source")
    add_example(source)
    example = only_example(source)
    payload = {
        "name": "Imported pets",
        "language": "openapi",
        "examples": [
            {
                "input": example.input,
                "expected": example.expected,
                "split": "dev",
                "status": "approved",
                "notes": "n",
            }
        ],
    }

    response = import_file(payload)

    imported = GoldSet.query.get(name="Imported pets")
    copy = only_example(imported)
    assert response.headers["Location"] == f"/tuning/goldsets/{imported.id}"
    assert (copy.split, copy.status, copy.source) == ("dev", "approved", "imported")
    assert DocPage.model_validate(copy.expected) == example.expected_page()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"name": "X", "language": "openapi"},
            "Not a valid gold-set file (examples: Field required)",
        ),
        ({"name": "X", "language": "cobol", "examples": []}, "isn&#39;t enabled"),
    ],
)
def test_bad_gold_set_files_are_rejected(payload: object, message: str) -> None:
    response = import_file(payload)

    assert response.status_code == 422
    assert message in response.content.decode()
    assert not GoldSet.query.filter(name="X").exists()


def test_starter_sets_are_created_once_with_parser_seeded_drafts() -> None:
    Client().post("/tuning/goldsets", data={"form": "starter"})
    Client().post("/tuning/goldsets", data={"form": "starter"})

    starters = list(GoldSet.query.filter(name__startswith="Starter").order_by("name"))
    assert [s.name for s in starters] == ["Starter (OpenAPI)", "Starter (Python)"]
    for starter in starters:
        examples = list(GoldExample.query.filter(gold_set=starter))
        assert examples
        assert {e.split for e in examples} == {"train", "dev"}
        assert {e.status for e in examples} == {"draft"}
        assert all(e.expected_page().surface.operations for e in examples)


def test_examples_of_another_set_are_not_found() -> None:
    first = make_set("A")
    other = make_set("B")
    add_example(first)
    example = only_example(first)

    assert (
        Client().get(f"/tuning/goldsets/{other.id}/examples/{example.id}").status_code
        == 404
    )
