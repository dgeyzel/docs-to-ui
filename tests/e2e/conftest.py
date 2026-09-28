import os
import subprocess
import sys
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def native_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    """E2E servers and workers record traces natively, like a real install."""
    monkeypatch.setenv("PLAIN_TELEMETRY_BACKENDS", '["native"]')


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
