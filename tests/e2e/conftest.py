import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from plain.pytest.browser import TestBrowser

from tests.helpers import activate_fake_model

REPO_ROOT = Path(__file__).resolve().parents[2]
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


@pytest.fixture
def worker(testbrowser) -> Iterator[None]:
    """A job worker using the same isolated database as the test server."""
    env = os.environ.copy()
    env["DATABASE_URL"] = testbrowser.database_url
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "plain",
            "jobs",
            "worker",
            "--max-processes",
            "1",
            "--stats-every",
            "0",
        ],
        env=env,
    )
    try:
        yield
    finally:
        process.terminate()
        process.wait(timeout=30)


@pytest.fixture
def tuning_browser(browser, testbrowser) -> Iterator[TestBrowser]:
    """A Tuning app server on the Docs app server's isolated database."""
    tuning = TestBrowser(browser=browser, database_url=testbrowser.database_url)
    # The server runs the app in its working directory.
    previous = Path.cwd()
    os.chdir(REPO_ROOT / "tuning_app")
    try:
        tuning.run_server()
    finally:
        os.chdir(previous)
    try:
        yield tuning
    finally:
        tuning.cleanup_server()
