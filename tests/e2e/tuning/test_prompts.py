import pytest
from playwright.sync_api import expect

from tests.helpers import read_fixture

pytestmark = pytest.mark.e2e

PETSTORE = read_fixture("openapi/petstore-3.0.yaml")
# Generations run in a separate worker process, so allow time for it to start.
WORKER_TIMEOUT_MS = 60_000


def test_a_promoted_prompt_is_used_by_the_docs_app_and_rolled_back(
    tuning_browser, docs_browser, worker
) -> None:
    tuning = tuning_browser.new_page()
    tuning.goto("/tuning/prompts")
    tuning.get_by_label("Copy from").select_option(
        label="openapi/llm/baseline (active)"
    )
    tuning.get_by_label("New label").fill("v2")
    tuning.get_by_role("button", name="Create draft").click()
    expect(tuning.get_by_role("status")).to_have_text("Draft created.")

    tuning.get_by_label("Instructions (the system prompt)").fill(
        "Document the API precisely."
    )
    tuning.get_by_role("button", name="Save draft").click()
    expect(tuning.get_by_role("status")).to_have_text("Draft saved.")
    tuning.get_by_role("button", name="Promote v2").click()
    expect(tuning.get_by_role("status")).to_contain_text("Version promoted.")

    docs = docs_browser.new_page()
    docs.goto("/")
    expect(docs.get_by_text("openapi/llm/v2")).to_be_visible()
    docs.get_by_role("tab", name="Paste").click()
    docs.get_by_label("Source text").fill(PETSTORE)
    docs.get_by_role("button", name="Generate documentation").click()
    expect(docs.get_by_text("openapi/llm/v2")).to_be_visible(timeout=WORKER_TIMEOUT_MS)

    tuning.goto("/tuning/prompts")
    tuning.get_by_role("button", name="Roll back to baseline").click()
    expect(tuning.get_by_role("status")).to_contain_text("Rolled back.")
    docs.goto("/")
    expect(docs.get_by_text("openapi/llm/baseline")).to_be_visible()
