from types import SimpleNamespace

import psycopg
import pytest
from d2u.generations.models import Generation
from d2u.schemas.docpage import DocPage
from plain.test import Client

from app.generate.jobs import GenerateDocJob
from tests.helpers import FIXTURES_DIR, read_fixture

PETSTORE = read_fixture("openapi/petstore-3.0.yaml")

pytestmark = pytest.mark.usefixtures("db")


def latest_generation() -> Generation:
    generation = Generation.query.order_by("-id").first()
    assert generation is not None
    return generation


def submit(text: str = PETSTORE) -> Generation:
    """Post the form and return the new (still pending) generation."""
    response = Client().post("/generations", data={"text": text, "language": ""})
    assert response.status_code == 302
    return latest_generation()


def run_job(generation: Generation) -> Generation:
    GenerateDocJob(generation.id).run()
    return Generation.query.get(generation.id)


def test_submitting_queues_a_pending_generation() -> None:
    generation = submit()

    assert generation.status == "pending"
    assert generation.stage == ""
    assert generation.doc_json is None


def test_job_runs_a_generation_to_success_with_enrichment() -> None:
    generation = run_job(submit())

    assert generation.status == "succeeded"
    assert generation.stage == "merge"
    assert generation.progress == {"batches_done": 1, "batches_total": 1}
    assert generation.program_version == "baseline"
    assert generation.model == "fake"
    assert generation.error_code == ""
    page = DocPage.model_validate(generation.doc_json)
    docs = {entry.operation_id: entry for entry in page.operations}
    assert "GET /invented" not in docs
    assert set(docs) == {op.id for op in page.surface.operations}
    assert docs["GET /pets"].param_descriptions == {
        "GET /pets#limit": "Maximum number of pets to return (default 20).",
        "GET /pets#X-Request-Id": "Optional ID for tracing a request.",
    }
    assert page.overview.groups == {
        "Pets": [
            "GET /pets",
            "POST /pets",
            "GET /pets/{petId}",
            "DELETE /pets/{petId}",
        ],
        "Orders": ["PATCH /orders/{orderId}"],
    }


def test_running_the_job_twice_is_safe() -> None:
    generation = run_job(submit())
    first = generation.doc_json

    again = run_job(generation)

    assert again.status == "succeeded"
    assert again.doc_json == first
    assert again.finished_at == generation.finished_at


def test_invalid_input_fails_the_job_with_input_error() -> None:
    generation = run_job(submit("openapi: 3.0.0\npaths:\n  /a: [\n"))

    assert generation.status == "failed"
    assert generation.error_code == "input_error"
    assert generation.error_detail["path"] == "input.yaml"
    assert generation.error_detail["line"] == 4


def test_invalid_llm_output_fails_with_validation_error(settings) -> None:
    settings.LLM_FAKE_RESPONSES = str(FIXTURES_DIR / "llm" / "invalid.json")

    generation = run_job(submit())

    assert generation.status == "failed"
    assert generation.error_code == "validation_error"
    assert generation.error_detail["message"] == "1 of 1 batches failed."


def test_passing_the_soft_timeout_fails_with_timeout(settings) -> None:
    settings.GENERATIONS_TIMEOUT_S = -1

    generation = run_job(submit())

    assert generation.status == "failed"
    assert generation.error_code == "timeout"


def test_missing_program_artifact_fails_the_generation(settings) -> None:
    settings.LLM_PROGRAM_VERSION = "does-not-exist"

    generation = run_job(submit())

    assert generation.status == "failed"
    assert generation.error_code == "provider_error"
    assert "No artifact" in generation.error_detail["message"]


def test_lost_worker_marks_the_generation_failed() -> None:
    generation = submit()
    Generation.query.filter(id=generation.id).update(status="running")

    GenerateDocJob(generation.id).on_aborted(SimpleNamespace())  # ty: ignore[invalid-argument-type]

    generation = Generation.query.get(generation.id)
    assert generation.status == "failed"
    assert generation.error_code == "worker_lost"


def test_lost_worker_does_not_touch_finished_generations() -> None:
    generation = run_job(submit())

    GenerateDocJob(generation.id).on_aborted(SimpleNamespace())  # ty: ignore[invalid-argument-type]

    assert Generation.query.get(generation.id).status == "succeeded"


def test_enqueue_failure_marks_the_generation_failed(monkeypatch) -> None:
    def broken_enqueue(self: GenerateDocJob, **kwargs: object) -> None:
        raise psycopg.OperationalError("queue unavailable")

    monkeypatch.setattr(GenerateDocJob, "run_in_worker", broken_enqueue)

    generation = submit()

    assert generation.status == "failed"
    assert generation.error_code == "enqueue_error"


def test_status_fragment_polls_while_pending() -> None:
    generation = submit()

    response = Client().get(f"/generations/{generation.id}/status")

    html = response.content.decode()
    assert response.status_code == 200
    assert 'hx-trigger="every 2s"' in html
    assert "Waiting for a worker" in html
    assert "Bundle" in html


def test_status_fragment_redirects_when_done() -> None:
    generation = run_job(submit())

    response = Client().get(f"/generations/{generation.id}/status")

    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == f"/generations/{generation.id}"


def test_status_fragment_stops_polling_with_retry_on_failure() -> None:
    generation = run_job(submit("not: [valid"))

    response = Client().get(f"/generations/{generation.id}/status")

    html = response.content.decode()
    assert response.status_code == 286
    assert "Input error" in html
    assert f'action="/generations/{generation.id}/regenerate"' in html
    assert "Retry" in html


def test_detail_page_shows_the_status_panel_while_running() -> None:
    generation = submit()

    html = Client().get(f"/generations/{generation.id}").content.decode()

    assert "Generation in progress" in html
    assert f'hx-get="/generations/{generation.id}/status"' in html
    assert "htmx" in html


def test_regenerate_creates_a_new_generation_from_the_stored_input() -> None:
    original = run_job(submit())

    response = Client().post(f"/generations/{original.id}/regenerate")

    copy = latest_generation()
    assert copy.id != original.id
    assert response.headers["Location"] == f"/generations/{copy.id}"
    assert copy.status == "pending"
    assert bytes(copy.input_blob) == bytes(original.input_blob)
    assert copy.input_origin == original.input_origin
    assert run_job(copy).status == "succeeded"
