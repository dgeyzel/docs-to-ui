from datetime import UTC, datetime, timedelta

import pytest
from d2u.generations.models import Generation

from app.generate.presentation import build_status_view, wall_time_label


def make_generation(**fields: object) -> Generation:
    defaults: dict[str, object] = {
        "input_origin": "paste",
        "input_blob": b"",
        "input_sha256": "0" * 64,
        "input_bytes": 0,
    }
    return Generation(**(defaults | fields))  # ty: ignore[invalid-argument-type]


def test_pending_generation_waits_for_a_worker() -> None:
    view = build_status_view(make_generation(status="pending"))

    assert [step.state for step in view.steps] == ["upcoming"] * 5
    assert view.progress_label == "Waiting for a worker…"
    assert view.percent == 0


def test_running_generation_marks_earlier_stages_completed() -> None:
    generation = make_generation(
        status="running",
        stage="enrich",
        progress={"batches_done": 7, "batches_total": 18},
    )

    view = build_status_view(generation)

    assert [(step.label, step.state) for step in view.steps] == [
        ("Bundle", "completed"),
        ("Extract", "completed"),
        ("Enrich", "active"),
        ("Overview", "upcoming"),
        ("Merge", "upcoming"),
    ]
    assert view.percent == 39
    assert view.progress_label == "Enriched 7 of 18 batches"


@pytest.mark.parametrize(
    ("seconds", "label"), [(5, "5s"), (65, "1m 05s"), (600, "10m 00s")]
)
def test_wall_time_label(seconds: int, label: str) -> None:
    started = datetime(2026, 9, 27, tzinfo=UTC)
    generation = make_generation(
        started_at=started, finished_at=started + timedelta(seconds=seconds)
    )

    assert wall_time_label(generation) == label


def test_wall_time_is_empty_until_finished() -> None:
    assert wall_time_label(make_generation()) == ""
