import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from plain.pytest.browser import TestBrowser
from playwright.sync_api import Browser

from tests.helpers import activate_fake_model

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_APP = "docs_app"
TUNING_APP = "tuning_app"
PROVIDER_KEY_VARIABLES = ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
LANGFUSE_VARIABLES = (
    "LANGFUSE_BASE_URL",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_PROJECT_ID",
)


@pytest.fixture
def initial_trace_backends() -> list[str] | None:
    """Trace backends chosen before the servers start; None keeps the seeded choice.

    Override in a test module to start from another choice.
    """
    return None


@pytest.fixture(autouse=True)
def e2e_environment(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prepare E2E servers and workers: tracing on, no provider keys, fake model.

    The test suites run from an app directory with tests outside it, so pytest
    applies this conftest's autouse fixtures to every test; this one acts only
    on tests marked `e2e`. Provider keys and Langfuse credentials are removed
    from the environment servers and workers inherit, so no E2E run can reach
    a real model or Langfuse.
    """
    if request.node.get_closest_marker("e2e") is None:
        return
    monkeypatch.setenv("PLAIN_TELEMETRY_EXPORT_ENABLED", "true")
    # Backend switches made during a test apply within a second.
    monkeypatch.setenv("PLAIN_TELEMETRY_SETTINGS_TTL_S", "1")
    for name in PROVIDER_KEY_VARIABLES + LANGFUSE_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    request.getfixturevalue("isolated_db")
    activate_fake_model()
    backends = request.getfixturevalue("initial_trace_backends")
    if backends is not None:
        from d2u.registry.models import RuntimeSettings

        runtime = RuntimeSettings.load()
        runtime.trace_backends = backends
        runtime.update()
    # Started after the environment and database are set, so the server
    # inherits them and never sees an earlier choice.
    request.getfixturevalue("testbrowser")


def _app_server(
    browser: Browser, testbrowser: TestBrowser, app_dir: str
) -> TestBrowser:
    """A second app server on the test server's isolated database."""
    server = TestBrowser(browser=browser, database_url=testbrowser.database_url)
    # `plain server` runs the app in its working directory.
    previous = Path.cwd()
    os.chdir(REPO_ROOT / app_dir)
    try:
        server.run_server()
    finally:
        os.chdir(previous)
    return server


def _worker(testbrowser: TestBrowser, app_dir: str, queue: str) -> Iterator[None]:
    env = os.environ.copy()
    env["DATABASE_URL"] = testbrowser.database_url
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "plain",
            "jobs",
            "worker",
            "--queue",
            queue,
            "--max-processes",
            "1",
            "--stats-every",
            "0",
        ],
        cwd=REPO_ROOT / app_dir,
        env=env,
    )
    try:
        yield
    finally:
        process.terminate()
        process.wait(timeout=30)


@pytest.fixture
def docs_browser(browser: Browser, testbrowser: TestBrowser) -> Iterator[TestBrowser]:
    """The Docs app server: the test server, or a second one beside the Tuning app."""
    if Path.cwd().name == DOCS_APP:
        yield testbrowser
        return
    server = _app_server(browser, testbrowser, DOCS_APP)
    try:
        yield server
    finally:
        server.cleanup_server()


@pytest.fixture
def tuning_browser(browser: Browser, testbrowser: TestBrowser) -> Iterator[TestBrowser]:
    """The Tuning app server: the test server, or a second one beside the Docs app.

    Tuning-only tables exist only when the suite runs from `tuning_app`, so
    journeys that need them live in `tests/e2e/tuning`.
    """
    if Path.cwd().name == TUNING_APP:
        yield testbrowser
        return
    server = _app_server(browser, testbrowser, TUNING_APP)
    try:
        yield server
    finally:
        server.cleanup_server()


@pytest.fixture
def worker(testbrowser: TestBrowser) -> Iterator[None]:
    """A Docs app job worker using the same isolated database as the test server."""
    yield from _worker(testbrowser, DOCS_APP, "docs")


@pytest.fixture
def tuning_worker(testbrowser: TestBrowser) -> Iterator[None]:
    """A Tuning app job worker using the same isolated database as the test server."""
    yield from _worker(testbrowser, TUNING_APP, "tuning")
