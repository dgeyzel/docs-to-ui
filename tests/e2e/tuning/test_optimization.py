import pytest
from d2u.registry.models import ModelConfig
from playwright.sync_api import Page, expect

from tests.helpers import read_fixture

pytestmark = pytest.mark.e2e

PETSTORE = read_fixture("openapi/petstore-3.0.yaml")
# The Tuning app's worker runs in a separate process, so allow time for it to start.
WORKER_TIMEOUT_MS = 90_000


def add_approved_example(page: Page, split: str) -> None:
    page.get_by_role("link", name="Add example").click()
    page.get_by_label("Or paste source").fill(PETSTORE)
    page.get_by_role("button", name="Create example").click()
    page.get_by_label("Split").select_option(split)
    page.get_by_role("button", name="Save review").click()
    page.get_by_role("button", name="Approve").click()
    expect(page.get_by_role("status")).to_have_text("Example approved.")
    page.get_by_role("link", name="Pets").click()


def test_an_optimized_candidate_is_evaluated_and_promoted(
    tuning_browser, tuning_worker
) -> None:
    ModelConfig(
        name="Fake Judge", litellm_model="fake", enabled_for_judging=True
    ).create()
    page = tuning_browser.new_page()
    page.goto("/tuning/goldsets")
    page.get_by_label("Name").fill("Pets")
    page.get_by_role("button", name="Create gold set").click()
    add_approved_example(page, "train")
    add_approved_example(page, "dev")

    page.goto("/tuning/optimization/new")
    page.get_by_label("Base prompt version").select_option(
        label="openapi/llm/baseline (active)"
    )
    page.get_by_label("Gold set").select_option(label="Pets (openapi)")
    page.get_by_label("Task model").select_option(label="Fake")
    page.get_by_label("Judge model").select_option(label="Fake Judge")
    page.get_by_role("button", name="Start optimization").click()

    expect(page.get_by_role("heading", name="Trial log")).to_be_visible(
        timeout=WORKER_TIMEOUT_MS
    )
    candidate = page.get_by_role("heading", name="Candidate opt-")
    expect(candidate).to_be_visible()
    promote = page.get_by_role("button", name="Promote opt-")
    for _ in range(int(WORKER_TIMEOUT_MS / 2000)):
        if promote.count():
            break
        page.wait_for_timeout(2000)
        page.reload()
    promote.click()

    expect(page.get_by_role("status")).to_contain_text("Version promoted.")
    expect(page.get_by_text("Scores that justified promotion")).to_be_visible()
