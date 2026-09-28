import time

import pytest
from d2u.traces.models import TraceSpan
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

# Spans are exported in batches every few seconds.
EXPORT_TIMEOUT_S = 60
BEFORE_PATH = "/generations/990001"


@pytest.fixture
def initial_trace_backends() -> list[str]:
    """Start with no backend, so the servers never cache an earlier choice."""
    return []


def request_spans(path: str) -> list[TraceSpan]:
    return [
        span
        for span in TraceSpan.query.all()
        if (span.attributes or {}).get("url.path") == path
    ]


def visit_until_traced(page: Page) -> None:
    """Visit new paths until one of their request spans is stored."""
    deadline = time.monotonic() + EXPORT_TIMEOUT_S
    visited: list[str] = []
    while not any(request_spans(path) for path in visited):
        assert time.monotonic() < deadline, "no request span was exported"
        visited.append(f"/generations/{990100 + len(visited)}")
        page.goto(visited[-1])
        page.wait_for_timeout(1000)


def test_trace_backends_are_switched_in_the_tuning_app_without_a_restart(
    docs_browser, tuning_browser
) -> None:
    docs = docs_browser.new_page()
    tuning = tuning_browser.new_page()

    docs.goto(BEFORE_PATH)
    tuning.goto("/tuning/settings")
    native = tuning.get_by_label("Native")
    langfuse = tuning.get_by_label("Langfuse")
    expect(native).not_to_be_checked()
    expect(langfuse).to_be_disabled()
    expect(tuning.get_by_text("Set LANGFUSE_BASE_URL")).to_be_visible()

    native.check()
    tuning.get_by_role("button", name="Save settings").click()

    expect(tuning.get_by_role("status")).to_contain_text("Saved.")
    expect(tuning.get_by_label("Native")).to_be_checked()
    docs.goto("/")
    expect(docs.get_by_text("Traces: Native")).to_be_visible()
    visit_until_traced(docs)
    # That request ended while no backend was chosen, so it was never routed;
    # the spans stored since show that export itself works.
    assert request_spans(BEFORE_PATH) == []
