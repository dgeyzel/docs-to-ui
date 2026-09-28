import pytest
from playwright.sync_api import expect

from tests.helpers import read_fixture

pytestmark = pytest.mark.e2e

PETSTORE = read_fixture("openapi/petstore-3.0.yaml")
# The Tuning app's worker runs in a separate process, so allow time for it to start.
WORKER_TIMEOUT_MS = 60_000


def test_a_gold_example_is_created_edited_and_approved(tuning_browser) -> None:
    page = tuning_browser.new_page()
    page.goto("/tuning/goldsets")
    page.get_by_label("Name").fill("Pets")
    page.get_by_role("button", name="Create gold set").click()

    page.get_by_role("link", name="Add example").click()
    page.get_by_label("Or paste source").fill(PETSTORE)
    page.get_by_label("Seed from the parser").check()
    page.get_by_role("button", name="Create example").click()
    expect(page.get_by_role("status")).to_have_text("Example created.")

    page.get_by_label("Summary (up to 200 characters)").first.fill("Lists every pet.")
    page.get_by_role("button", name="Add parameter").first.click()
    page.get_by_label("Parameter 1 name").first.fill("zzz")
    page.get_by_role("button", name="Remove").last.click()
    page.get_by_role("button", name="Save expected page").click()
    expect(page.get_by_role("status")).to_have_text("Expected page saved.")
    expect(page.get_by_label("Summary (up to 200 characters)").first).to_have_value(
        "Lists every pet."
    )

    page.get_by_role("button", name="Approve").click()
    expect(page.get_by_role("status")).to_have_text("Example approved.")
    expect(page.locator(".history-list")).to_contain_text("Approved")
    page.get_by_role("link", name="Pets").click()
    expect(page.get_by_text("approved: 1 train")).to_be_visible()


def test_an_example_is_seeded_from_the_fake_model(
    tuning_browser, tuning_worker
) -> None:
    page = tuning_browser.new_page()
    page.goto("/tuning/goldsets")
    page.get_by_label("Name").fill("Seeded")
    page.get_by_role("button", name="Create gold set").click()
    page.get_by_role("link", name="Add example").click()
    page.get_by_label("Or paste source").fill(PETSTORE)
    page.get_by_label("Seed from a model").check()
    page.get_by_label("Model", exact=False).last.select_option(label="Fake")
    page.get_by_role("button", name="Create example").click()

    expect(page.locator(".history-list")).to_contain_text(
        "Filled in by Fake", timeout=WORKER_TIMEOUT_MS
    )
