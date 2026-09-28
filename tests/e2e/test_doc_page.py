import time
from pathlib import Path

import pytest
from playwright.sync_api import Locator, Page, expect

from app.generations.models import Feedback, Generation
from app.llm.docpage import build_unenriched_docpage
from app.llm.schemas import DocPage, Example, OperationDocs
from app.sources.adapters.openapi import OpenApiAdapter
from tests.helpers import FIXTURES_DIR, bundle_of, read_fixture, zip_dir

pytestmark = pytest.mark.e2e

PETSTORE = read_fixture("openapi/petstore-3.0.yaml")
# Generations run in a separate worker process, so allow time for it to start.
WORKER_TIMEOUT_MS = 60_000


def create_enriched_generation() -> Generation:
    """A succeeded generation whose first operation has LLM docs with examples."""
    adapter = OpenApiAdapter()
    surface = adapter.extract(bundle_of("petstore.yaml", PETSTORE))
    page = build_unenriched_docpage(
        surface=surface, group_of=adapter.group_key, display_name="OpenAPI"
    )
    page = DocPage(
        surface=page.surface,
        overview=page.overview,
        operations=[
            OperationDocs(
                operation_id="GET /pets",
                summary="List available pets",
                description_md="Returns pets.",
                param_descriptions={},
                examples=[
                    Example(title="Shell", language="curl", code="curl /pets"),
                    Example(
                        title="Script", language="python", code="client.list_pets()"
                    ),
                ],
            )
        ],
    )
    generation = Generation(
        language="openapi",
        input_origin="file",
        input_filename="petstore.yaml",
        input_blob=PETSTORE.encode(),
        input_sha256="0" * 64,
        input_bytes=len(PETSTORE),
        input_manifest={"included": ["petstore.yaml"], "skipped": []},
        status="succeeded",
        doc_json=page.model_dump(mode="json"),
    )
    generation.create()
    return generation


def reload_until_visible(page: Page, locator: Locator) -> None:
    """Reload until the locator shows up; spans from other processes arrive in batches."""
    deadline = time.monotonic() + WORKER_TIMEOUT_MS / 1000
    while locator.count() == 0:
        assert time.monotonic() < deadline, "timed out waiting for spans"
        page.wait_for_timeout(1000)
        page.reload()
    expect(locator.first).to_be_visible()


def submit_paste(page: Page, text: str) -> None:
    page.goto("/")
    page.get_by_role("tab", name="Paste").click()
    page.get_by_label("Source text").fill(text)
    page.get_by_role("button", name="Generate documentation").click()


def test_paste_generates_a_navigable_doc_page(testbrowser, worker) -> None:
    page = testbrowser.new_page()
    submit_paste(page, PETSTORE)

    expect(page.get_by_text("Generation in progress")).to_be_visible()
    expect(page.get_by_role("heading", name="Petstore Plus API")).to_be_visible(
        timeout=WORKER_TIMEOUT_MS
    )
    expect(page.get_by_text("Files read (1 included, 0 skipped)")).to_be_visible()
    card = page.locator("#op-get-pets")
    expect(card.get_by_text("List available pets")).to_be_visible()
    expect(card.get_by_text("Not enriched")).to_have_count(0)

    card_toggle = card.get_by_role("button", name="get /pets", exact=False)
    card_toggle.click()
    expect(card_toggle).to_have_attribute("aria-expanded", "false")
    expect(card.locator(".op-card-body")).to_be_hidden()

    page.get_by_role("link", name="get /pets", exact=False).first.click()
    expect(card_toggle).to_have_attribute("aria-expanded", "true")
    expect(card.locator(".op-card-body")).to_be_visible()

    nav_toggle = page.get_by_role("button", name="Pets", exact=True)
    nav_toggle.click()
    expect(nav_toggle).to_have_attribute("aria-expanded", "false")


def test_failed_generation_shows_the_error_and_can_retry(testbrowser, worker) -> None:
    page = testbrowser.new_page()
    submit_paste(page, "openapi: 3.0.0\npaths:\n  /a: [\n")

    expect(page.get_by_text("Input error")).to_be_visible(timeout=WORKER_TIMEOUT_MS)
    expect(page.get_by_text("input.yaml:4")).to_be_visible()
    first_url = page.url

    page.get_by_role("button", name="Retry").click()

    expect(page).not_to_have_url(first_url)
    expect(page.get_by_text("Input error")).to_be_visible(timeout=WORKER_TIMEOUT_MS)


def test_trace_viewer_shows_the_waterfall_and_llm_calls(testbrowser, worker) -> None:
    page = testbrowser.new_page()
    submit_paste(page, PETSTORE)
    expect(page.get_by_role("heading", name="Petstore Plus API")).to_be_visible(
        timeout=WORKER_TIMEOUT_MS
    )

    page.get_by_role("link", name="View trace").click()

    waterfall = page.get_by_role("list", name="Span timeline")
    reload_until_visible(page, waterfall.get_by_text("generate", exact=True))
    expect(waterfall.locator(".span-request").first).to_be_visible()
    waterfall.locator("[data-span-type=llm]").first.click()
    detail = page.locator("#span-detail")
    expect(detail.get_by_role("heading", name="LLM call")).to_be_visible()
    expect(detail.get_by_text("Input messages")).to_be_visible()


def test_theme_toggle_switches_and_persists_the_theme(testbrowser) -> None:
    page = testbrowser.new_page()
    page.emulate_media(color_scheme="light")
    page.goto("/")

    page.get_by_role("button", name="Toggle theme").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")

    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")


def test_example_tabs_and_copy_button(testbrowser) -> None:
    generation = create_enriched_generation()
    testbrowser.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page = testbrowser.new_page()
    page.goto(f"/generations/{generation.id}")

    card = page.locator("#op-get-pets")
    expect(card.get_by_text("curl /pets")).to_be_visible()
    card.get_by_role("tab", name="Python").click()
    expect(card.get_by_role("tab", name="Python")).to_have_attribute(
        "aria-selected", "true"
    )
    expect(card.get_by_text("client.list_pets()")).to_be_visible()
    expect(card.get_by_text("curl /pets")).to_be_hidden()

    panel = card.get_by_role("tabpanel").filter(has_text="client.list_pets()")
    panel.get_by_role("button", name="Copy").click()
    expect(panel.get_by_role("button", name="Copied")).to_be_visible()
    assert page.evaluate("navigator.clipboard.readText()") == "client.list_pets()"


def test_exported_html_works_offline_from_disk(testbrowser, tmp_path: Path) -> None:
    generation = create_enriched_generation()
    page = testbrowser.new_page()
    page.goto(f"/generations/{generation.id}")

    with page.expect_download() as download_info:
        page.get_by_role("link", name="Export HTML").click()
    export_path = tmp_path / "export.html"
    download_info.value.save_as(export_path)

    offline = testbrowser.browser.new_page()
    requests: list[str] = []
    offline.on("request", lambda request: requests.append(request.url))
    offline.goto(export_path.as_uri())

    assert requests == [export_path.as_uri()]
    expect(offline.get_by_role("heading", name="Petstore Plus API")).to_be_visible()
    expect(offline.get_by_role("button", name="Toggle theme")).to_have_count(0)
    card = offline.locator("#op-get-pets")
    card.get_by_role("tab", name="Python").click()
    expect(card.get_by_text("client.list_pets()")).to_be_visible()
    toggle = card.locator("[data-collapse-toggle]")
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    offline.close()


def test_exported_html_follows_the_system_theme(testbrowser, tmp_path: Path) -> None:
    generation = create_enriched_generation()
    page = testbrowser.new_page()
    response = page.request.get(f"/generations/{generation.id}/export.html")
    export_path = tmp_path / "export.html"
    export_path.write_bytes(response.body())

    offline: Page = testbrowser.browser.new_page(color_scheme="dark")
    offline.goto(export_path.as_uri())

    background = offline.evaluate(
        "getComputedStyle(document.body).getPropertyValue('background-color')"
    )
    assert background == "rgb(20, 20, 20)"
    offline.close()


def test_zip_upload_documents_a_python_package(
    testbrowser, worker, tmp_path: Path
) -> None:
    archive = tmp_path / "acme.zip"
    archive.write_bytes(zip_dir(FIXTURES_DIR / "python" / "acme", prefix="acme-main/"))
    page = testbrowser.new_page()
    page.goto("/")

    page.get_by_label("Source file").set_input_files(archive)
    page.get_by_role("button", name="Generate documentation").click()

    expect(page.get_by_role("heading", name="acme", exact=True, level=1)).to_be_visible(
        timeout=WORKER_TIMEOUT_MS
    )
    manifest = page.get_by_text("Files read (5 included, 3 skipped)")
    expect(manifest).to_be_visible()
    manifest.click()
    expect(page.get_by_text("excluded: **/tests/**").first).to_be_visible()
    expect(
        page.locator("#op-acme-client").get_by_text("acme/client.py:1")
    ).to_be_visible()


def test_feedback_on_an_operation_is_saved(testbrowser) -> None:
    generation = create_enriched_generation()
    page = testbrowser.new_page()
    page.goto(f"/generations/{generation.id}")

    form = page.locator("#feedback-op-get-pets")
    form.get_by_text("Add a correction").click()
    form.get_by_label("Correction").fill("The limit maximum is 100.")
    form.get_by_role("button", name="No").click()

    form = page.locator("#feedback-op-get-pets")
    expect(form.get_by_role("status")).to_have_text(
        "Thanks! You rated this not helpful."
    )
    expect(form.get_by_role("button", name="No")).to_have_attribute(
        "aria-pressed", "true"
    )
    feedback = Feedback.query.get(Feedback.generation.id.equals(generation.id))
    assert (feedback.operation_id, feedback.score) == ("GET /pets", -1)
    assert feedback.comment == "The limit maximum is 100."
