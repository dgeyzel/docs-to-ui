"""Pure helpers that turn stored spans into what the trace viewer renders."""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

STAGE_NAMES = ("generate", "bundle", "extract", "overview", "merge")
_BATCH_SPAN = re.compile(r"^(enrich\.batch|generate\.part)\[\d+\]$")
_MESSAGE_KEY = re.compile(
    r"^llm\.(input|output)_messages\.(\d+)\.message\.(role|content)$"
)
TOKEN_KEYS = {
    "prompt": "llm.token_count.prompt",
    "completion": "llm.token_count.completion",
    "total": "llm.token_count.total",
}


class SpanLike(Protocol):
    """What the viewer needs from a span (satisfied by `TraceSpan`)."""

    @property
    def trace_id(self) -> str: ...

    @property
    def span_id(self) -> str: ...

    @property
    def parent_span_id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def kind(self) -> str: ...

    @property
    def start_time(self) -> datetime: ...

    @property
    def end_time(self) -> datetime: ...

    @property
    def duration_ms(self) -> float: ...

    @property
    def status_code(self) -> str: ...

    @property
    def attributes(self) -> dict: ...

    @property
    def is_llm(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class WaterfallRow:
    span_id: str
    name: str
    depth: int
    span_type: str
    offset_percent: float
    width_percent: float
    duration_ms: float
    is_error: bool


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class LLMCall:
    model: str
    input_messages: list[Message]
    output_messages: list[Message]
    tokens: dict[str, int | None]


@dataclass(frozen=True, slots=True)
class AttributeRow:
    key: str
    value: str


@dataclass(frozen=True, slots=True)
class TraceTotals:
    llm_calls: int
    total_tokens: int
    span_count: int = 0
    errors: int = 0


def span_type(span: SpanLike) -> str:
    """Which `--d2u-span-*` color a span gets."""
    if span.status_code == "ERROR":
        return "error"
    if span.is_llm:
        return "llm"
    if span.kind == "SERVER":
        return "request"
    if span.kind in ("CONSUMER", "PRODUCER"):
        return "job"
    if "db.system" in span.attributes or "db.system.name" in span.attributes:
        return "db"
    if span.name in STAGE_NAMES or _BATCH_SPAN.match(span.name):
        return "stage"
    return "other"


def build_waterfall(spans: Sequence[SpanLike]) -> list[WaterfallRow]:
    """Order spans depth-first under their parents and lay them on a timeline.

    Spans whose parent isn't in the trace are treated as roots. Children are
    sorted by start time.
    """
    if not spans:
        return []
    by_id = {span.span_id: span for span in spans}
    children: dict[str, list[SpanLike]] = {}
    roots: list[SpanLike] = []
    for span in spans:
        if span.parent_span_id and span.parent_span_id in by_id:
            children.setdefault(span.parent_span_id, []).append(span)
        else:
            roots.append(span)

    start = min(span.start_time for span in spans)
    end = max(span.end_time for span in spans)
    total_ms = max((end - start).total_seconds() * 1000, 0.001)

    rows: list[WaterfallRow] = []
    stack = [(root, 0) for root in sorted(roots, key=_start, reverse=True)]
    while stack:
        span, depth = stack.pop()
        offset = (span.start_time - start).total_seconds() * 1000
        rows.append(
            WaterfallRow(
                span_id=span.span_id,
                name=span.name,
                depth=depth,
                span_type=span_type(span),
                offset_percent=round(100 * offset / total_ms, 3),
                width_percent=round(max(100 * span.duration_ms / total_ms, 0.5), 3),
                duration_ms=span.duration_ms,
                is_error=span.status_code == "ERROR",
            )
        )
        for child in sorted(children.get(span.span_id, []), key=_start, reverse=True):
            stack.append((child, depth + 1))
    return rows


def _start(span: SpanLike) -> datetime:
    return span.start_time


def token_count(attributes: dict[str, Any], kind: str) -> int | None:
    """A token count from OpenInference attributes, if recorded."""
    value = attributes.get(TOKEN_KEYS[kind])
    return value if isinstance(value, int) else None


def build_llm_call(attributes: dict[str, Any]) -> LLMCall:
    """Collect model, messages and token counts from an LLM span."""
    messages: dict[str, dict[int, dict[str, str]]] = {"input": {}, "output": {}}
    for key, value in attributes.items():
        match = _MESSAGE_KEY.match(key)
        if match:
            direction, index, part = match.groups()
            messages[direction].setdefault(int(index), {})[part] = str(value)

    def ordered(direction: str) -> list[Message]:
        return [
            Message(role=parts.get("role", ""), content=parts.get("content", ""))
            for _, parts in sorted(messages[direction].items())
        ]

    return LLMCall(
        model=str(attributes.get("llm.model_name", "")),
        input_messages=ordered("input"),
        output_messages=ordered("output"),
        tokens={kind: token_count(attributes, kind) for kind in TOKEN_KEYS},
    )


def attribute_rows(attributes: dict[str, Any]) -> list[AttributeRow]:
    """Attributes sorted by key, with non-string values as JSON."""
    return [
        AttributeRow(
            key=key,
            value=value if isinstance(value, str) else json.dumps(value, default=str),
        )
        for key, value in sorted(attributes.items())
    ]


def trace_totals(spans: Sequence[SpanLike]) -> TraceTotals:
    """LLM call count and total tokens across a trace."""
    llm_spans = [span for span in spans if span.is_llm]
    tokens = sum(token_count(span.attributes, "total") or 0 for span in llm_spans)
    return TraceTotals(
        llm_calls=len(llm_spans),
        total_tokens=tokens,
        span_count=len(spans),
        errors=sum(1 for span in spans if span.status_code == "ERROR"),
    )
