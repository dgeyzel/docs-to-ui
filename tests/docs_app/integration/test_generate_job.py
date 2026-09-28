from types import SimpleNamespace

import psycopg
import pytest
from d2u.generations.models import Generation
from d2u.registry.models import PromptVersion, RuntimeSettings
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


def test_job_generates_the_page_with_one_direct_llm_call() -> None:
    generation = run_job(submit())

    assert generation.status == "succeeded"
    assert generation.stage == "merge"
    assert generation.strategy == "llm"
    assert generation.progress == {"done": 1, "total": 1}
    assert generation.model == "Fake"
    assert generation.llm_model is not None
    assert generation.prompt_label == "openapi/llm/baseline"
    assert generation.prompt_version is not None
    assert generation.error_code == ""
    assert generation.input_tokens > 0
    assert generation.output_tokens > 0
    page = DocPage.model_validate(generation.doc_json)
    assert page.strategy == "llm"
    assert [op.id for op in page.surface.operations] == [
        "GET /pets",
        "POST /pets",
        "GET /pets/{petId}",
        "DELETE /pets/{petId}",
        "PATCH /orders/{orderId}",
    ]
    docs = {entry.operation_id: entry for entry in page.operations}
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


def test_source_locations_outside_the_input_are_dropped() -> None:
    generation = run_job(submit())

    page = DocPage.model_validate(generation.doc_json)
    locations = {op.id: op.location for op in page.surface.operations}
    assert locations["GET /pets"] is not None
    assert (locations["GET /pets"].path, locations["GET /pets"].line) == (
        "input.yaml",
        8,
    )
    assert locations["PATCH /orders/{orderId}"] is None


def test_hybrid_strategy_documents_the_parsed_structure() -> None:
    generation = submit()
    Generation.query.filter(id=generation.id).update(strategy="hybrid")

    generation = run_job(generation)

    assert generation.status == "succeeded"
    assert generation.prompt_label == "openapi/hybrid/baseline"
    page = DocPage.model_validate(generation.doc_json)
    assert page.strategy == "hybrid"
    docs = {entry.operation_id: entry for entry in page.operations}
    assert "GET /invented" not in docs
    assert docs["GET /pets"].param_descriptions == {
        "GET /pets#limit": "Maximum number of pets to return (default 20).",
        "GET /pets#X-Request-Id": "Optional ID for tracing a request.",
    }
    assert page.overview.overview_md.startswith("The **Petstore Plus API**")


def test_parser_strategy_needs_no_model() -> None:
    generation = submit()
    Generation.query.filter(id=generation.id).update(strategy="parser")
    RuntimeSettings.query.update(active_model=None)

    generation = run_job(generation)

    assert generation.status == "succeeded"
    assert generation.input_tokens == 0
    assert DocPage.model_validate(generation.doc_json).operations == []


def test_running_the_job_twice_is_safe() -> None:
    generation = run_job(submit())
    first = generation.doc_json

    again = run_job(generation)

    assert again.status == "succeeded"
    assert again.doc_json == first
    assert again.finished_at == generation.finished_at


def test_invalid_input_fails_before_any_llm_call() -> None:
    generation = run_job(submit("openapi: 3.0.0\npaths:\n  /a: [\n"))

    assert generation.status == "failed"
    assert generation.error_code == "input_error"
    assert generation.error_detail["path"] == "input.yaml"
    assert generation.error_detail["line"] == 4
    assert generation.input_tokens == 0


def test_invalid_llm_output_fails_with_validation_error(settings) -> None:
    settings.GENERATIONS_FAKE_RESPONSES = str(FIXTURES_DIR / "llm" / "invalid.json")

    generation = run_job(submit())

    assert generation.status == "failed"
    assert generation.error_code == "validation_error"
    assert "did not match GeneratedPage" in generation.error_detail["message"]


def test_passing_the_soft_timeout_fails_with_timeout(settings) -> None:
    settings.GENERATIONS_TIMEOUT_S = -1

    generation = run_job(submit())

    assert generation.status == "failed"
    assert generation.error_code == "timeout"


def test_no_active_model_fails_with_a_clear_message() -> None:
    RuntimeSettings.query.update(active_model=None)

    generation = run_job(submit())

    assert generation.status == "failed"
    assert generation.error_code == "provider_error"
    assert "No active model" in generation.error_detail["message"]


def test_no_active_prompt_fails_with_a_clear_message() -> None:
    PromptVersion.query.filter(language="openapi", strategy="llm").update(
        status="draft"
    )

    generation = run_job(submit())

    assert generation.status == "failed"
    assert generation.error_code == "provider_error"
    assert "No active llm prompt for openapi" in generation.error_detail["message"]


def test_unexpected_errors_are_recorded_as_internal_errors(monkeypatch) -> None:
    from app.generate import jobs

    def explode(generation: Generation) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(jobs, "run_claimed_generation", explode)

    generation = run_job(submit())

    assert generation.status == "failed"
    assert generation.error_code == "internal_error"


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
