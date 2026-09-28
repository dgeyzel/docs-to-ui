"""The Docs app never uses DSPy (SPEC D12, AGENTS.md §3)."""

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DSPY_IMPORT = re.compile(r"^\s*(import dspy|from dspy)\b", re.MULTILINE)


def test_shared_library_and_docs_app_never_import_dspy() -> None:
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for root in ("shared/src", "docs_app/app")
        for path in (REPO_ROOT / root).rglob("*.py")
        if DSPY_IMPORT.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []


def test_booting_the_docs_app_loads_no_dspy() -> None:
    code = (
        "import plain.runtime, sys; plain.runtime.setup(); "
        "import app.urls, app.generate.pipeline, app.generate.jobs; "
        "print('dspy' in sys.modules)"
    )
    env = os.environ | {"PLAIN_POSTGRES_URL": "none", "PLAIN_TELEMETRY_BACKENDS": "[]"}

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT / "docs_app",
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip().splitlines()[-1] == "False"
