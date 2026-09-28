import pytest
from d2u.registry.models import ModelConfig
from playwright.sync_api import Page, expect

from tests.helpers import read_fixture

pytestmark = pytest.mark.e2e

PETSTORE = read_fixture("openapi/petstore-3.0.yaml")
# The Tuning app's worker runs in a separate process, so allow time for it to start.
WORKER_TIMEOUT_MS = 60_000


def create_approved_gold_set(page: Page) -> None:
    """A gold set with one approved dev example, made through the UI."""
    page.goto("/tuning/goldsets")
    page.get_by_label("Name").fill("Pets")
    page.get_by_role("button", name="Create gold set").click()
    page.get_by_role("link", name="Add example").click()
    page.get_by_label("Or paste source").fill(PETSTORE)
    page.get_by_role("button", name="Create example").click()
    page.get_by_label("Split").select_option("dev")
    page.get_by_role("button", name="Save review").click()
    page.get_by_role("button", name="Approve").click()
    expect(page.get_by_role("status")).to_have_text("Example approved.")


def test_an_eval_run_is_started_scored_and_traced(
    tuning_browser, tuning_worker
) -> None:
    ModelConfig(
        name="Fake Judge", litellm_model="fake", enabled_for_judging=True
    ).create()
    page = tuning_browser.new_page()
    create_approved_gold_set(page)

    page.goto("/tuning/evals")
    page.get_by_role("link", name="New eval run").click()
    page.get_by_label("Gold set").select_option(label="Pets (openapi)")
    page.get_by_label("Generation model").select_option(label="Fake")
    page.get_by_label("Judge model").select_option(label="Fake Judge")
    page.get_by_role("button", name="Start eval run").click()

    expect(page.get_by_role("heading", name="Summary")).to_be_visible(
        timeout=WORKER_TIMEOUT_MS
    )
    expect(page.get_by_role("cell", name="Faithfulness")).to_be_visible()
    expect(page.get_by_text("1 of 1 examples")).to_be_visible()
    page.get_by_role("link", name="Traces").last.click()
    expect(page.get_by_label("Eval run")).not_to_have_value("")


def test_two_runs_are_compared_and_an_example_is_inspected(
    tuning_browser, tuning_worker
) -> None:
    ModelConfig(
        name="Fake Judge", litellm_model="fake", enabled_for_judging=True
    ).create()
    page = tuning_browser.new_page()
    create_approved_gold_set(page)
    for strategy, model in (("parser", ""), ("llm", "Fake")):
        page.goto("/tuning/evals/new")
        page.get_by_label("Gold set").select_option(label="Pets (openapi)")
        page.get_by_label("Strategy").select_option(strategy)
        if model:
            page.get_by_label("Generation model").select_option(label=model)
        else:
            page.get_by_label("Generation model").select_option("")
        page.get_by_label("Judge model").select_option(label="Fake Judge")
        page.get_by_role("button", name="Start eval run").click()
        expect(page.get_by_role("heading", name="Summary")).to_be_visible(
            timeout=WORKER_TIMEOUT_MS
        )

    page.get_by_role("link", name="input.yaml").click()
    expect(page.get_by_role("heading", name="Expected and generated")).to_be_visible()
    expect(page.get_by_text("Prose quality 4/5")).to_be_visible()

    page.goto("/tuning/evals")
    for checkbox in page.get_by_role("checkbox").all():
        checkbox.check()
    page.get_by_role("button", name="Compare selected").click()
    expect(page.get_by_role("heading", name="Compare runs")).to_be_visible()
    expect(page.get_by_text("(baseline)").first).to_be_visible()
    expect(page.get_by_role("heading", name="Examples")).to_be_visible()

    page.goto("/tuning")
    expect(
        page.get_by_role("heading", name="Latest scores by language")
    ).to_be_visible()
    expect(page.get_by_role("cell", name="openapi")).to_be_visible()
