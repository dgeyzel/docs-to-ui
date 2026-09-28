import os
import subprocess
import sys
from collections.abc import Iterator

import pytest

from tests.helpers import activate_fake_model

PROVIDER_KEY_VARIABLES = ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")


@pytest.fixture(autouse=True)
def e2e_environment(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prepare E2E servers and workers: native tracing, no provider keys, fake model.

    The test suites run from an app directory with tests outside it, so pytest
    applies this conftest's autouse fixtures to every test; this one acts only
    on tests marked `e2e`. Provider keys are removed from the environment the
    server and worker inherit, so no E2E run can ever reach a real model.
    """
    if request.node.get_closest_marker("e2e") is None:
        return
    monkeypatch.setenv("PLAIN_TELEMETRY_BACKENDS", '["native"]')
    for name in PROVIDER_KEY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    # Started after the environment is set, so the server inherits it.
    request.getfixturevalue("testbrowser")
    activate_fake_model()


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
