from datetime import UTC, datetime, timedelta

import pytest
from d2u.generations.models import Generation

from app.generate.presentation import build_status_view, usage_label, wall_time_label


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

    assert [step.label for step in view.steps] == ["Bundle", "Generate", "Merge"]
    assert [step.state for step in view.steps] == ["upcoming"] * 3
    assert view.progress_label == "Waiting for a worker…"
    assert view.percent == 0


@pytest.mark.parametrize("stage", ["generate", "overview"])
def test_llm_strategy_shows_generate_while_parts_and_overview_run(stage: str) -> None:
    generation = make_generation(
        status="running", stage=stage, progress={"done": 1, "total": 3}
    )

    view = build_status_view(generation)

    assert [(step.label, step.state) for step in view.steps] == [
        ("Bundle", "completed"),
        ("Generate", "active"),
        ("Merge", "upcoming"),
    ]
    assert view.progress_label == "Generated 1 of 3 parts"


def test_hybrid_strategy_marks_earlier_stages_completed() -> None:
    generation = make_generation(
        status="running",
        strategy="hybrid",
        stage="enrich",
        progress={"done": 7, "total": 18},
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


def test_usage_label_shows_tokens_and_cost() -> None:
    generation = make_generation(input_tokens=12000, output_tokens=340, cost_usd=0.0041)

    assert usage_label(generation) == "12,340 tokens · $0.0041"
    assert usage_label(make_generation()) == ""
