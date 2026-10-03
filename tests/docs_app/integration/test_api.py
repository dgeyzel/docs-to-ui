import json
from io import BytesIO

import pytest
from d2u.generations.models import Feedback, Generation
from d2u.schemas.api import ApiError, GenerationList, GenerationResource
from d2u.schemas.docpage import DocPage
from plain.test import Client

from app.generate.jobs import GenerateDocJob
from tests.helpers import FIXTURES_DIR, make_zip, read_fixture, zip_dir

PETSTORE = read_fixture("openapi/petstore-3.0.yaml")
BROKEN = "openapi: 3.0.0\ninfo:\n  title: Broken\npaths:\n  /a: [\n"
API = "/api/v1"

pytestmark = pytest.mark.usefixtures("db")


def upload(name: str, content: str | bytes) -> BytesIO:
    data = content.encode("utf-8") if isinstance(content, str) else content
    file = BytesIO(data)
    file.name = name
    return file


def submit_file(name: str, content: str | bytes, **fields: str):
    data = {"file": upload(name, content), "language": "", "entry": ""} | fields
    return Client().post(f"{API}/generations", data=data)


def run_job(generation_id: int) -> None:
    GenerateDocJob(generation_id).run()


def created(response) -> GenerationResource:
    assert response.status_code == 202, response.content
    return GenerationResource.model_validate_json(response.content)


def api_error(response) -> ApiError:
    assert response.headers["Content-Type"] == "application/json"
    return ApiError.model_validate_json(response.content)


def succeeded_generation() -> GenerationResource:
    resource = created(submit_file("petstore.yaml", PETSTORE))
    run_job(resource.id)
    return resource


def test_uploaded_file_creates_a_pending_generation() -> None:
    response = submit_file("petstore.yaml", PETSTORE)

    resource = created(response)
    assert response.headers["Location"] == f"{API}/generations/{resource.id}"
    assert resource.status == "pending"
    assert resource.input.origin == "file"
    assert resource.input.filename == "petstore.yaml"
    assert resource.input.bytes == len(PETSTORE.encode("utf-8"))
    assert resource.links.page == f"{API}/generations/{resource.id}/page"
    assert resource.links.ui == f"/generations/{resource.id}"
    assert "input_blob" not in response.content.decode()


def test_a_file_alone_is_enough_like_curl_dash_f() -> None:
    response = Client().post(
        f"{API}/generations", data={"file": upload("petstore.yaml", PETSTORE)}
    )

    resource = created(response)
    run_job(resource.id)
    assert Client().get(f"{API}/generations/{resource.id}/page").status_code == 200


def test_json_text_submission_is_documented() -> None:
    response = Client().post(
        f"{API}/generations",
        data={"text": PETSTORE, "language": "openapi"},
        content_type="application/json",
    )
    resource = created(response)
    run_job(resource.id)

    page = Client().get(f"{API}/generations/{resource.id}/page")

    assert resource.input.origin == "paste"
    assert page.status_code == 200
    doc = DocPage.model_validate_json(page.content)
    assert doc.surface.title == "Petstore Plus API"
    assert len(doc.surface.operations) == 5


def test_zip_upload_uses_the_entry_file() -> None:
    spec = (
        "openapi: 3.0.0\ninfo: {title: X, version: '1'}\npaths:\n  /a:\n    get: {}\n"
    )
    data = make_zip(
        {"v1/openapi.yaml": spec, "v2/openapi.yaml": spec.replace("/a", "/b")}
    )

    resource = created(submit_file("api.zip", data, entry="v2/openapi.yaml"))
    run_job(resource.id)
    finished = Client().get(f"{API}/generations/{resource.id}")

    body = GenerationResource.model_validate_json(finished.content)
    assert body.input.origin == "zip"
    assert body.input.entry == "v2/openapi.yaml"
    assert body.status == "succeeded"
    assert body.manifest is not None
    assert "v2/openapi.yaml" in body.manifest.included


def test_python_zip_is_documented() -> None:
    data = zip_dir(FIXTURES_DIR / "python" / "acme", prefix="acme-main/")

    resource = created(submit_file("acme.zip", data))
    run_job(resource.id)

    page = Client().get(f"{API}/generations/{resource.id}/page")
    assert page.status_code == 200
    assert DocPage.model_validate_json(page.content).surface.operations


def test_empty_json_submission_is_refused() -> None:
    response = Client().post(
        f"{API}/generations", data={"text": ""}, content_type="application/json"
    )

    assert response.status_code == 400
    error = api_error(response).error
    assert error.code == "invalid_input"
    assert error.message == "Upload a file or paste some text."
    assert Generation.query.count() == 0


def test_file_and_text_together_are_refused() -> None:
    response = submit_file("a.yaml", PETSTORE, text=PETSTORE)

    assert response.status_code == 400
    error = api_error(response).error
    assert error.code == "invalid_input"
    assert error.message == "Upload a file or paste text, not both."
    assert Generation.query.count() == 0


def test_unknown_languages_are_reported_by_field() -> None:
    response = Client().post(
        f"{API}/generations",
        data={"text": PETSTORE, "language": "cobol"},
        content_type="application/json",
    )

    error = api_error(response).error
    assert response.status_code == 400
    assert error.fields is not None
    assert "language" in error.fields


def test_the_input_size_limit_applies(settings) -> None:
    settings.GENERATIONS_MAX_INPUT_BYTES = 100

    response = submit_file("big.yaml", "openapi: 3.0.0\n" + "#" * 200)

    error = api_error(response).error
    assert response.status_code == 400
    assert error.fields is not None
    assert "exceeds" in error.fields["file"][0]


def test_malformed_json_is_answered_in_the_error_envelope() -> None:
    response = Client().post(
        f"{API}/generations", data="{not json", content_type="application/json"
    )

    assert response.status_code == 400
    assert api_error(response).error.code == "bad_request"


def test_unknown_generations_are_not_found_as_json() -> None:
    for path in ("", "/page", "/page.html"):
        response = Client().get(f"{API}/generations/999999{path}")

        assert response.status_code == 404
        assert api_error(response).error.code == "not_found"


def test_page_is_not_ready_while_pending() -> None:
    resource = created(submit_file("petstore.yaml", PETSTORE))

    response = Client().get(f"{API}/generations/{resource.id}/page")

    assert response.status_code == 409
    error = api_error(response).error
    assert error.code == "not_ready"
    assert error.generation is not None
    assert error.generation.status == "pending"


def test_failed_generation_page_reports_the_input_error() -> None:
    resource = created(submit_file("broken.yaml", BROKEN))
    run_job(resource.id)

    response = Client().get(f"{API}/generations/{resource.id}/page")

    assert response.status_code == 422
    error = api_error(response).error
    assert error.code == "generation_failed"
    assert error.generation is not None
    assert error.generation.error is not None
    assert error.generation.error.code == "input_error"
    assert error.generation.error.path == "broken.yaml"
    assert error.generation.error.line == 6


def test_wait_returns_at_once_when_the_generation_has_finished() -> None:
    resource = succeeded_generation()

    response = Client().get(f"{API}/generations/{resource.id}?wait=30")

    assert response.status_code == 200
    body = GenerationResource.model_validate_json(response.content)
    assert body.status == "succeeded"
    assert body.finished_at is not None


def test_wait_is_capped_by_the_setting(settings) -> None:
    settings.API_MAX_WAIT_S = 0
    resource = created(submit_file("petstore.yaml", PETSTORE))

    response = Client().get(f"{API}/generations/{resource.id}/page?wait=600")

    assert response.status_code == 409


@pytest.mark.parametrize("wait", ["soon", "-1"])
def test_bad_wait_values_are_refused(wait: str) -> None:
    resource = created(submit_file("petstore.yaml", PETSTORE))

    response = Client().get(f"{API}/generations/{resource.id}?wait={wait}")

    assert response.status_code == 400
    assert "wait" in api_error(response).error.message


def test_list_is_newest_first_and_filters_by_status() -> None:
    first = succeeded_generation()
    second = created(submit_file("petstore.yaml", PETSTORE))

    everything = GenerationList.model_validate_json(
        Client().get(f"{API}/generations").content
    )
    pending = GenerationList.model_validate_json(
        Client().get(f"{API}/generations?status=pending").content
    )
    limited = GenerationList.model_validate_json(
        Client().get(f"{API}/generations?limit=1").content
    )

    assert [g.id for g in everything.generations] == [second.id, first.id]
    assert [g.id for g in pending.generations] == [second.id]
    assert [g.id for g in limited.generations] == [second.id]


@pytest.mark.parametrize("query", ["status=done", "limit=0", "limit=101", "limit=x"])
def test_bad_list_parameters_are_refused(query: str) -> None:
    response = Client().get(f"{API}/generations?{query}")

    assert response.status_code == 400
    assert api_error(response).error.code == "bad_request"


def test_html_export_is_served_for_a_succeeded_generation() -> None:
    resource = succeeded_generation()

    response = Client().get(f"{API}/generations/{resource.id}/page.html")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    html = response.content.decode()
    assert "Petstore Plus API" in html
    assert "hx-" not in html


def test_page_json_matches_the_json_export() -> None:
    resource = succeeded_generation()

    api_page = Client().get(f"{API}/generations/{resource.id}/page")
    exported = Client().get(f"/generations/{resource.id}/export.json")

    assert json.loads(api_page.content) == json.loads(exported.content)


def test_regenerate_creates_a_new_generation_from_the_same_input() -> None:
    original = succeeded_generation()

    response = Client().post(f"{API}/generations/{original.id}/regenerate")

    copy = created(response)
    assert copy.id != original.id
    assert copy.status == "pending"
    assert copy.input.sha256 == original.input.sha256
    assert copy.input.filename == "petstore.yaml"


def test_feedback_is_recorded_on_the_page_and_an_operation() -> None:
    resource = succeeded_generation()
    url = f"{API}/generations/{resource.id}/feedback"

    page_response = Client().post(
        url, data={"score": 1}, content_type="application/json"
    )
    operation_response = Client().post(
        url,
        data={"operation_id": "GET /pets", "score": -1, "comment": " Wrong "},
        content_type="application/json",
    )

    assert page_response.status_code == 201
    assert operation_response.status_code == 201
    rows = sorted(
        (f.operation_id, f.score, f.comment)
        for f in Feedback.query.where(Feedback.generation.id.equals(resource.id))
    )
    assert rows == [("", 1, ""), ("GET /pets", -1, "Wrong")]


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"score": 0}, 400, "invalid_input"),
        ({"score": 1, "anchor": "page"}, 400, "invalid_input"),
        ({"score": 1, "operation_id": "GET /nowhere"}, 404, "not_found"),
    ],
)
def test_invalid_feedback_is_refused(body: dict, status: int, code: str) -> None:
    resource = succeeded_generation()

    response = Client().post(
        f"{API}/generations/{resource.id}/feedback",
        data=body,
        content_type="application/json",
    )

    assert response.status_code == status
    assert api_error(response).error.code == code
    assert Feedback.query.count() == 0


def test_feedback_needs_a_succeeded_generation() -> None:
    resource = created(submit_file("petstore.yaml", PETSTORE))

    response = Client().post(
        f"{API}/generations/{resource.id}/feedback",
        data={"score": 1},
        content_type="application/json",
    )

    assert response.status_code == 409
    assert api_error(response).error.code == "not_ready"


def test_cross_site_browser_posts_are_refused() -> None:
    response = Client().post(
        f"{API}/generations",
        data={"text": PETSTORE},
        content_type="application/json",
        headers={"Sec-Fetch-Site": "cross-site"},
    )

    # Plain answers a CSRF rejection with 400 (SuspiciousOperationError400).
    assert response.status_code == 400
    assert Generation.query.count() == 0
