import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

# The Tuning app's worker runs in a separate process, so allow time for it to start.
WORKER_TIMEOUT_MS = 60_000


def test_a_model_is_added_with_offered_parameters_and_tested(
    tuning_browser, tuning_worker
) -> None:
    page = tuning_browser.new_page()
    page.goto("/tuning/models")
    page.get_by_role("link", name="Add model").click()
    # HTMX loads with the page; typing before then wouldn't fetch parameters.
    page.wait_for_load_state()

    page.get_by_label("Name").fill("Claude E2E")
    page.get_by_label("LiteLLM model").fill("anthropic/claude-sonnet-4-5")
    expect(page.get_by_label("Temperature")).to_be_visible()
    page.get_by_label("LiteLLM model").fill("gemini/gemini-3.8-flash")
    expect(page.get_by_label("Reasoning effort")).to_be_visible()
    expect(page.get_by_label("Temperature")).to_have_count(0)
    page.get_by_label("Reasoning effort").select_option("low")
    page.get_by_label("API key variable").fill("GEMINI_API_KEY")
    page.get_by_role("button", name="Add model").click()

    expect(page.get_by_role("heading", name="Claude E2E")).to_be_visible()
    expect(page.get_by_label("Reasoning effort")).to_have_value("low")
    page.get_by_role("button", name="Test connection").click()
    expect(
        page.get_by_role("alert").filter(has_text="GEMINI_API_KEY is not set")
    ).to_be_visible(timeout=WORKER_TIMEOUT_MS)


def test_the_fake_model_passes_its_connection_test(
    tuning_browser, tuning_worker
) -> None:
    page = tuning_browser.new_page()
    page.goto("/tuning/models")
    page.get_by_role("link", name="Fake").click()

    page.get_by_role("button", name="Test connection").click()

    expect(page.get_by_text("Answered in")).to_be_visible(timeout=WORKER_TIMEOUT_MS)
