from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from d2u.traces.presentation import (
    attribute_rows,
    build_llm_call,
    build_waterfall,
    span_type,
    trace_totals,
)

T0 = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


@dataclass
class FakeSpan:
    span_id: str
    name: str
    start_ms: int
    end_ms: int
    parent_span_id: str = ""
    kind: str = "INTERNAL"
    status_code: str = "UNSET"
    attributes: dict = field(default_factory=dict)
    is_llm: bool = False
    trace_id: str = "t" * 32

    @property
    def start_time(self) -> datetime:
        return T0 + timedelta(milliseconds=self.start_ms)

    @property
    def end_time(self) -> datetime:
        return T0 + timedelta(milliseconds=self.end_ms)

    @property
    def duration_ms(self) -> float:
        return float(self.end_ms - self.start_ms)


def test_waterfall_orders_spans_depth_first_by_start_time() -> None:
    spans = [
        FakeSpan("c2", "second child", 60, 90, parent_span_id="root"),
        FakeSpan("root", "request", 0, 100, kind="SERVER"),
        FakeSpan("c1", "first child", 10, 50, parent_span_id="root"),
        FakeSpan("g1", "grandchild", 20, 30, parent_span_id="c1"),
        FakeSpan("orphan", "orphan", 95, 100, parent_span_id="missing"),
    ]

    rows = build_waterfall(spans)

    assert [(row.name, row.depth) for row in rows] == [
        ("request", 0),
        ("first child", 1),
        ("grandchild", 2),
        ("second child", 1),
        ("orphan", 0),
    ]
    assert rows[0].offset_percent == 0
    assert rows[0].width_percent == 100
    assert rows[1].offset_percent == 10
    assert rows[1].width_percent == 40


def test_waterfall_of_no_spans_is_empty() -> None:
    assert build_waterfall([]) == []


@pytest.mark.parametrize(
    ("span", "expected"),
    [
        (FakeSpan("a", "GET /", 0, 1, kind="SERVER"), "request"),
        (FakeSpan("a", "process default", 0, 1, kind="CONSUMER"), "job"),
        (FakeSpan("a", "DummyLM.__call__", 0, 1, is_llm=True), "llm"),
        (
            FakeSpan(
                "a",
                "SELECT",
                0,
                1,
                kind="CLIENT",
                attributes={"db.system.name": "postgresql"},
            ),
            "db",
        ),
        (FakeSpan("a", "enrich.batch[3]", 0, 1), "stage"),
        (FakeSpan("a", "extract", 0, 1), "stage"),
        (FakeSpan("a", "something", 0, 1), "other"),
        (FakeSpan("a", "GET /", 0, 1, kind="SERVER", status_code="ERROR"), "error"),
    ],
)
def test_span_type_picks_the_waterfall_color(span: FakeSpan, expected: str) -> None:
    assert span_type(span) == expected


def test_build_llm_call_collects_messages_in_order_and_tokens() -> None:
    attributes = {
        "llm.model_name": "gemini/gemini-3.8-flash",
        "llm.input_messages.1.message.role": "user",
        "llm.input_messages.1.message.content": "Document this.",
        "llm.input_messages.0.message.role": "system",
        "llm.input_messages.0.message.content": "You write docs.",
        "llm.output_messages.0.message.role": "assistant",
        "llm.output_messages.0.message.content": "Done.",
        "llm.token_count.prompt": 120,
        "llm.token_count.completion": 30,
        "llm.token_count.total": 150,
    }

    call = build_llm_call(attributes)

    assert call.model == "gemini/gemini-3.8-flash"
    assert [(m.role, m.content) for m in call.input_messages] == [
        ("system", "You write docs."),
        ("user", "Document this."),
    ]
    assert [(m.role, m.content) for m in call.output_messages] == [
        ("assistant", "Done.")
    ]
    assert call.tokens == {"prompt": 120, "completion": 30, "total": 150}


def test_build_llm_call_without_token_counts() -> None:
    assert build_llm_call({}).tokens == {
        "prompt": None,
        "completion": None,
        "total": None,
    }


def test_trace_totals_counts_llm_calls_tokens_and_errors() -> None:
    spans = [
        FakeSpan(
            "a", "llm", 0, 1, is_llm=True, attributes={"llm.token_count.total": 100}
        ),
        FakeSpan("b", "llm", 0, 1, is_llm=True),
        FakeSpan("c", "other", 0, 1, status_code="ERROR"),
    ]

    totals = trace_totals(spans)

    assert (
        totals.llm_calls,
        totals.total_tokens,
        totals.span_count,
        totals.errors,
    ) == (
        2,
        100,
        3,
        1,
    )


def test_attribute_rows_are_sorted_with_json_for_non_strings() -> None:
    rows = attribute_rows({"b": 2, "a": "text", "c": ["x"]})

    assert [(row.key, row.value) for row in rows] == [
        ("a", "text"),
        ("b", "2"),
        ("c", '["x"]'),
    ]
