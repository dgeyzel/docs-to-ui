from pathlib import Path

import pytest
from d2u.schemas.docpage import DocPage

from scripts.d2u_client import EXIT_FAILED, EXIT_OK, main
from tests.helpers import FIXTURES_DIR

pytestmark = pytest.mark.e2e

# Generations run in a separate worker process, so allow time for it to start.
CLIENT_TIMEOUT_S = "60"


def test_client_generates_and_saves_a_page(testbrowser, worker, tmp_path: Path) -> None:
    out, html = tmp_path / "page.json", tmp_path / "page.html"

    code = main(
        [
            "generate",
            str(FIXTURES_DIR / "openapi" / "petstore-3.0.yaml"),
            "--out",
            str(out),
            "--html",
            str(html),
            "--base-url",
            testbrowser.base_url,
            "--timeout",
            CLIENT_TIMEOUT_S,
            "--insecure",
        ]
    )

    assert code == EXIT_OK
    page = DocPage.model_validate_json(out.read_bytes())
    assert page.surface.title == "Petstore Plus API"
    assert "Petstore Plus API" in html.read_text(encoding="utf-8")


def test_client_reports_a_failed_generation(
    testbrowser, worker, tmp_path: Path, capsys
) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("openapi: 3.0.0\ninfo:\n  title: Broken\npaths:\n  /a: [\n")

    code = main(
        [
            "generate",
            str(broken),
            "--out",
            str(tmp_path / "page.json"),
            "--base-url",
            testbrowser.base_url,
            "--timeout",
            CLIENT_TIMEOUT_S,
            "--insecure",
        ]
    )

    assert code == EXIT_FAILED
    assert "input_error (broken.yaml:6)" in capsys.readouterr().err
