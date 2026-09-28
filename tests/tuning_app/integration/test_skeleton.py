from datetime import UTC, datetime, timedelta

import pytest
from d2u.traces.models import TraceSpan
from d2u.traces.templates import generation_url
from plain.test import Client

pytestmark = pytest.mark.usefixtures("db")


def test_root_redirects_to_the_dashboard_under_tuning() -> None:
    response = Client().get("/")

    assert response.status_code == 302
    assert response.headers["Location"] == "/tuning"


def test_dashboard_renders_with_the_shared_design_system() -> None:
    response = Client().get("/tuning")

    html = response.content.decode()
    assert response.status_code == 200
    assert "Docs-to-UI Tuning" in html
    assert "/assets/css/tokens.css" in html
    assert 'href="/tuning/traces"' in html


def test_trace_viewer_is_mounted_under_tuning() -> None:
    assert Client().get("/tuning/traces").status_code == 200


def test_trace_list_shows_generations_without_linking_to_missing_pages() -> None:
    now = datetime.now(UTC)
    TraceSpan(
        trace_id="a" * 32,
        span_id="b" * 16,
        name="generate",
        kind="INTERNAL",
        start_time=now,
        end_time=now + timedelta(milliseconds=5),
        duration_ms=5.0,
        status_code="UNSET",
        generation_id=7,
    ).create()

    html = Client().get("/tuning/traces").content.decode()

    assert "#7" in html
    assert "/generations/7" not in html
    assert generation_url(7) == ""
