import json
from io import BytesIO

import pytest
from d2u.generations.models import Generation
from d2u.schemas.docpage import DocPage
from plain.test import Client

from app.generate.jobs import GenerateDocJob
from tests.helpers import read_fixture

PETSTORE = read_fixture("openapi/petstore-3.0.yaml")
NOTES_JSON = read_fixture("openapi/notes-3.1.json")

pytestmark = pytest.mark.usefixtures("db")


def upload(name: str, content: str) -> BytesIO:
    file = BytesIO(content.encode("utf-8"))
    file.name = name
    return file


def only_generation() -> Generation:
    """The single generation, after running its queued job like the worker would."""
    generations = list(Generation.query.all())
    assert len(generations) == 1
    GenerateDocJob(generations[0].id).run()
    return Generation.query.get(generations[0].id)


def test_home_page_shows_form_and_empty_history() -> None:
    response = Client().get("/")

    assert response.status_code == 200
    assert "Generate documentation" in response.content.decode()
    assert "No generations yet." in response.content.decode()


def test_pasted_openapi_is_detected_and_rendered() -> None:
    response = Client().post("/generations", data={"text": PETSTORE, "language": ""})

    generation = only_generation()
    assert response.status_code == 302
    assert response.headers["Location"] == f"/generations/{generation.id}"
    assert generation.status == "succeeded"
    assert generation.language == "openapi"
    assert generation.input_origin == "paste"
    assert generation.input_filename == ""
    assert generation.input_bytes == len(PETSTORE.encode("utf-8"))
    assert generation.input_manifest == {"included": ["input.yaml"], "skipped": []}
    assert generation.started_at is not None
    assert generation.finished_at is not None
    page = DocPage.model_validate(generation.doc_json)
    assert page.surface.title == "Petstore Plus API"
    assert len(page.surface.operations) == 5
    assert [docs.operation_id for docs in page.operations] == [
        op.id for op in page.surface.operations
    ]


def test_paste_just_under_the_1_mb_limit_is_accepted() -> None:
    padding = "\n# " + "x" * (1024 * 1024 - len(PETSTORE) - 100)
    text = PETSTORE + padding

    response = Client().post("/generations", data={"text": text, "language": ""})

    assert response.status_code == 302
    assert only_generation().status == "succeeded"


def test_pasted_json_is_detected_without_a_language() -> None:
    Client().post("/generations", data={"text": NOTES_JSON, "language": ""})

    generation = only_generation()
    assert generation.status == "succeeded"
    assert generation.language == "openapi"


def test_pasted_json_with_escaped_emoji_is_documented() -> None:
    document = json.loads(NOTES_JSON)
    document["info"]["description"] = "Notes with reactions 👍"
    text = json.dumps(document, indent=2)
    assert "\\ud83d\\udc4d" in text

    Client().post("/generations", data={"text": text, "language": ""})

    generation = only_generation()
    assert generation.status == "succeeded", generation.error_detail
    assert generation.language == "openapi"


def test_uploaded_file_keeps_its_filename() -> None:
    Client().post(
        "/generations",
        data={
            "file": upload("specs/notes.json", NOTES_JSON),
            "text": "",
            "language": "openapi",
        },
    )

    generation = only_generation()
    assert generation.status == "succeeded"
    assert generation.input_origin == "file"
    assert generation.input_filename == "notes.json"
    assert generation.input_manifest == {"included": ["notes.json"], "skipped": []}
    assert bytes(generation.input_blob) == NOTES_JSON.encode("utf-8")


def test_invalid_input_fails_with_input_error_and_location() -> None:
    broken = "openapi: 3.0.0\ninfo:\n  title: Broken\npaths:\n  /a: [\n"

    response = Client().post(
        "/generations",
        data={"file": upload("broken.yaml", broken), "text": "", "language": ""},
    )

    generation = only_generation()
    assert response.status_code == 302
    assert generation.status == "failed"
    assert generation.error_code == "input_error"
    assert generation.error_detail["path"] == "broken.yaml"
    assert generation.error_detail["line"] == 6
    assert generation.doc_json is None

    detail = Client().get(f"/generations/{generation.id}").content.decode()
    assert "Input error" in detail
    assert "broken.yaml:6" in detail


def test_non_document_paste_fails_with_input_error() -> None:
    Client().post("/generations", data={"text": "just some words", "language": ""})

    generation = only_generation()
    assert generation.status == "failed"
    assert generation.error_code == "input_error"
    assert generation.error_detail["message"] == "The document must be a mapping."


def test_unrecognized_file_fails_with_input_error() -> None:
    Client().post(
        "/generations",
        data={"file": upload("notes.txt", "hello"), "text": "", "language": ""},
    )

    generation = only_generation()
    assert generation.status == "failed"
    assert generation.error_code == "input_error"
    assert "Could not detect" in generation.error_detail["message"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"text": "", "language": ""}, "Upload a file or paste some text."),
        (
            {"text": PETSTORE, "file": upload("a.yaml", PETSTORE), "language": ""},
            "Upload a file or paste text, not both.",
        ),
    ],
)
def test_form_rejects_invalid_submissions(data: dict, message: str) -> None:
    response = Client().post("/generations", data=data)

    assert response.status_code == 200
    assert message in response.content.decode()
    assert Generation.query.count() == 0


def test_form_rejects_unknown_languages() -> None:
    response = Client().post(
        "/generations", data={"text": PETSTORE, "language": "cobol"}
    )

    assert response.status_code == 200
    assert "Select a valid choice" in response.content.decode()
    assert Generation.query.count() == 0


@pytest.mark.parametrize("field", ["text", "file"])
def test_form_enforces_the_input_size_limit(settings, field: str) -> None:
    settings.GENERATIONS_MAX_INPUT_BYTES = 100
    content = "openapi: 3.0.0\n" + "#" * 200
    data = {"text": content, "language": ""}
    if field == "file":
        data = {"file": upload("big.yaml", content), "text": "", "language": ""}

    response = Client().post("/generations", data=data)

    assert response.status_code == 200
    assert "exceeds the 0.0 MB limit" in response.content.decode()
    assert Generation.query.count() == 0


def test_detail_page_renders_the_doc_page_and_manifest() -> None:
    Client().post("/generations", data={"text": PETSTORE, "language": ""})
    generation = only_generation()

    html = Client().get(f"/generations/{generation.id}").content.decode()

    assert "Petstore Plus API" in html
    assert "Files read (1 included, 0 skipped)" in html
    assert "Not enriched" not in html
    assert "List available pets" in html
    assert "curl https://api.example.com/pets?limit=10" in html
    assert 'id="op-get-pets"' in html
    assert "Source: input.yaml:8" in html
    assert "Toggle theme" in html
    assert "Export HTML" in html


def test_home_page_lists_recent_generations() -> None:
    Client().post("/generations", data={"text": PETSTORE, "language": ""})
    generation = only_generation()

    html = Client().get("/").content.decode()

    assert f'href="/generations/{generation.id}"' in html
    assert "Pasted input" in html
    assert "succeeded" in html
    assert "OpenAPI" in html


def test_detail_page_returns_404_for_unknown_generations() -> None:
    assert Client().get("/generations/999999").status_code == 404


def test_html_export_is_self_contained() -> None:
    Client().post("/generations", data={"text": PETSTORE, "language": ""})
    generation = only_generation()

    response = Client().get(f"/generations/{generation.id}/export.html")

    html = response.content.decode()
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert response.headers["Content-Disposition"] == (
        f'attachment; filename="docs-{generation.id}.html"'
    )
    assert "Petstore Plus API" in html
    assert "--d2u-method-get:" in html
    assert ".op-card" in html
    assert "initCollapsibles" in html
    for forbidden in (
        "<script src",
        "<link",
        "hx-",
        "htmx",
        "Toggle theme",
        "/generations/",
    ):
        assert forbidden not in html


def test_json_export_returns_the_doc_page() -> None:
    Client().post("/generations", data={"text": PETSTORE, "language": ""})
    generation = only_generation()

    response = Client().get(f"/generations/{generation.id}/export.json")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    page = DocPage.model_validate_json(response.content)
    assert page.model_dump(mode="json") == generation.doc_json


@pytest.mark.parametrize("suffix", ["export.html", "export.json"])
def test_exports_are_unavailable_for_failed_generations(suffix: str) -> None:
    Client().post("/generations", data={"text": "nope", "language": ""})
    generation = only_generation()

    assert Client().get(f"/generations/{generation.id}/{suffix}").status_code == 404
