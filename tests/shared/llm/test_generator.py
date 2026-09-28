import time
from collections.abc import Callable
from typing import Any

import dspy
import pytest
from d2u.llm.artifacts import Programs
from d2u.llm.exceptions import GenerationFailedError, GenerationTimeoutError
from d2u.llm.generator import GeneratorConfig, generate_docpage, surface_outline
from d2u.schemas.docpage import ApiSurface, Operation
from dspy.utils.dummies import DummyLM
from dspy.utils.exceptions import LMRateLimitError


class StubProgram(dspy.Module):
    """A program that answers from a function instead of calling an LM."""

    def __init__(self, answer: Callable[..., Any]) -> None:
        super().__init__()
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    def forward(self, **kwargs: Any) -> dspy.Prediction:
        self.calls.append(kwargs)
        return dspy.Prediction(result=self.answer(**kwargs))


def make_surface(count: int) -> ApiSurface:
    return ApiSurface(
        title="API",
        language="openapi",
        operations=[
            Operation(
                id=f"GET /op{i}",
                kind="http",
                signature=f"GET /op{i}",
                group_hint="g",
                params=[],
            )
            for i in range(count)
        ],
    )


def enrich_all(operations: list[Operation], **_: Any) -> dict[str, Any]:
    return {
        "operations": [
            {
                "operation_id": op.id,
                "summary": f"About {op.id}",
                "description_md": "Docs.",
                "param_descriptions": {},
                "examples": [],
            }
            for op in operations
        ]
    }


def overview_answer(**_: Any) -> dict[str, Any]:
    return {
        "overview_md": "An API.",
        "groups": {"Things": ["GET /op0", "GET /missing"]},
    }


def run(
    surface: ApiSurface,
    *,
    enrich: Callable[..., Any] = enrich_all,
    overview: Callable[..., Any] = overview_answer,
    max_operations: int = 1,
    deadline: float | None = None,
) -> tuple[Any, list[tuple[int, int]], list[str]]:
    progress: list[tuple[int, int]] = []
    stages: list[str] = []
    result = generate_docpage(
        surface=surface,
        group_of=lambda op: op.group_hint,
        display_name="OpenAPI",
        lm=DummyLM([]),
        programs=Programs(enrich=StubProgram(enrich), overview=StubProgram(overview)),
        config=GeneratorConfig(
            token_budget=100_000,
            max_operations=max_operations,
            max_concurrency=3,
            deadline=deadline,
        ),
        on_progress=lambda done, total: progress.append((done, total)),
        on_stage=stages.append,
    )
    return result, progress, stages


def test_generate_docpage_enriches_every_operation() -> None:
    result, progress, stages = run(make_surface(3))

    assert [docs.operation_id for docs in result.page.operations] == [
        "GET /op0",
        "GET /op1",
        "GET /op2",
    ]
    assert result.page.overview.overview_md == "An API."
    assert result.page.overview.groups == {"Things": ["GET /op0"]}
    assert result.batches_total == 3
    assert result.batches_failed == 0
    assert progress[0] == (0, 3)
    assert progress[-1] == (3, 3)
    assert stages == ["overview", "merge"]


def test_one_failed_batch_in_ten_still_renders_the_page() -> None:
    def flaky(operations: list[Operation], **kwargs: Any) -> dict[str, Any]:
        if operations[0].id == "GET /op4":
            return {"not": "valid"}
        return enrich_all(operations)

    result, _, _ = run(make_surface(10), enrich=flaky)

    enriched = {docs.operation_id for docs in result.page.operations}
    assert "GET /op4" not in enriched
    assert len(enriched) == 9
    assert result.batches_failed == 1


def test_invalid_output_is_retried_once() -> None:
    attempts: list[str] = []

    def fails_once(operations: list[Operation], **kwargs: Any) -> dict[str, Any]:
        attempts.append(operations[0].id)
        if attempts.count(operations[0].id) == 1:
            raise ValueError("unparseable")
        return enrich_all(operations)

    result, _, _ = run(make_surface(2), enrich=fails_once)

    assert result.batches_failed == 0
    assert sorted(attempts) == ["GET /op0", "GET /op0", "GET /op1", "GET /op1"]


def test_more_than_ten_percent_failed_batches_is_a_validation_failure() -> None:
    def mostly_broken(operations: list[Operation], **kwargs: Any) -> dict[str, Any]:
        if operations[0].id in ("GET /op1", "GET /op2"):
            raise ValueError("unparseable")
        return enrich_all(operations)

    with pytest.raises(
        GenerationFailedError, match="2 of 10 batches failed"
    ) as excinfo:
        run(make_surface(10), enrich=mostly_broken)

    assert excinfo.value.provider is False


def test_provider_errors_are_reported_as_provider_failures() -> None:
    def rate_limited(**kwargs: Any) -> dict[str, Any]:
        raise LMRateLimitError("slow down")

    with pytest.raises(GenerationFailedError) as excinfo:
        run(make_surface(2), enrich=rate_limited)

    assert excinfo.value.provider is True


def test_overview_failure_falls_back_to_a_deterministic_overview() -> None:
    def broken_overview(**kwargs: Any) -> dict[str, Any]:
        return {"groups": "not a dict"}

    result, _, _ = run(make_surface(2), overview=broken_overview)

    assert result.page.overview.groups == {"g": ["GET /op0", "GET /op1"]}
    assert "2 operations" in result.page.overview.overview_md


def test_a_passed_deadline_stops_new_batches() -> None:
    with pytest.raises(GenerationTimeoutError):
        run(make_surface(3), deadline=time.monotonic() - 1)


def test_surface_outline_lists_every_operation_with_its_group() -> None:
    outline = surface_outline(make_surface(2), lambda op: op.group_hint)

    assert outline == "API\n\n- GET /op0 (group: g)\n- GET /op1 (group: g)"
