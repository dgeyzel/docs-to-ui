import time
from typing import Any

import pytest
from d2u.generation.client import FakeResponses, ModelSpec
from d2u.generation.exceptions import (
    GenerationFailedError,
    GenerationTimeoutError,
    OutputValidationError,
)
from d2u.generation.prompts import OPERATIONS_MARKER, OVERVIEW_MARKER, PromptSpec
from d2u.generation.strategies import (
    GenerationConfig,
    generate_hybrid,
    generate_llm,
    generate_parser,
)
from d2u.schemas.docpage import ApiSurface, Operation

FAKE = ModelSpec(name="Fake", litellm_model="fake", max_input_tokens=1_000_000)
LLM_PROMPT = PromptSpec(
    language="openapi", strategy="llm", version="v1", instructions="Write docs."
)
HYBRID_PROMPT = PromptSpec(
    language="openapi", strategy="hybrid", version="v1", instructions="Describe."
)


def page_answer(*paths: str, title: str = "API") -> dict[str, Any]:
    return {
        "title": title,
        "overview_md": f"{title} overview.",
        "operations": [
            {
                "kind": "http",
                "method": "GET",
                "path": path,
                "signature": f"GET {path}",
                "group": "g",
                "summary": f"Get {path}",
            }
            for path in paths
        ],
    }


def test_llm_strategy_generates_the_page_in_one_call() -> None:
    fake = FakeResponses({"a.yaml": page_answer("/a", "/b")})
    progress: list[tuple[int, int]] = []
    stages: list[str] = []

    result = generate_llm(
        source_files={"a.yaml": "openapi: 3.1.0"},
        language="openapi",
        model=FAKE,
        prompt=LLM_PROMPT,
        config=GenerationConfig(fake=fake),
        on_progress=lambda done, total: progress.append((done, total)),
        on_stage=stages.append,
    )

    assert [op.id for op in result.page.surface.operations] == ["GET /a", "GET /b"]
    assert result.page.overview.overview_md == "API overview."
    assert result.usage.calls == 1
    assert result.parts_total == 1
    assert progress == [(0, 1), (1, 1)]
    assert stages == ["generate", "merge"]


def test_llm_strategy_splits_large_inputs_and_writes_one_overview() -> None:
    fake = FakeResponses(
        {
            OVERVIEW_MARKER: {"title": "Whole API", "overview_md": "Everything."},
            'path="a/one.yaml"': page_answer("/a", "/shared", title="Part A"),
            'path="b/two.yaml"': page_answer("/b", "/shared", title="Part B"),
        }
    )
    small = ModelSpec(name="Small", litellm_model="fake", max_input_tokens=300)
    stages: list[str] = []

    result = generate_llm(
        source_files={"a/one.yaml": "a" * 1000, "b/two.yaml": "b" * 1000},
        language="openapi",
        model=small,
        prompt=LLM_PROMPT,
        config=GenerationConfig(fake=fake),
        on_stage=stages.append,
    )

    assert result.parts_total == 2
    assert result.usage.calls == 3
    assert result.page.surface.title == "Whole API"
    assert result.page.overview.overview_md == "Everything."
    assert [op.id for op in result.page.surface.operations] == [
        "GET /a",
        "GET /shared",
        "GET /b",
    ]
    assert stages == ["generate", "overview", "merge"]


def test_llm_strategy_fails_when_any_part_fails() -> None:
    fake = FakeResponses({'path="a/one.yaml"': page_answer("/a")})
    small = ModelSpec(name="Small", litellm_model="fake", max_input_tokens=300)

    with pytest.raises(OutputValidationError):
        generate_llm(
            source_files={"a/one.yaml": "a" * 1000, "b/two.yaml": "b" * 1000},
            language="openapi",
            model=small,
            prompt=LLM_PROMPT,
            config=GenerationConfig(fake=fake),
        )


def test_llm_strategy_respects_the_deadline() -> None:
    with pytest.raises(GenerationTimeoutError):
        generate_llm(
            source_files={"a.yaml": "x"},
            language="openapi",
            model=FAKE,
            prompt=LLM_PROMPT,
            config=GenerationConfig(
                fake=FakeResponses({}), deadline=time.monotonic() - 1
            ),
        )


def make_surface(count: int) -> ApiSurface:
    return ApiSurface(
        title="API",
        language="openapi",
        operations=[
            Operation(
                id=f"GET /op{i}",
                kind="http",
                signature=f"GET /op{i}",
                group_hint=f"g{i}",
                params=[],
            )
            for i in range(count)
        ],
    )


class BatchAnswers(FakeResponses):
    """Answers each hybrid batch for the operations it contains, except `broken` ones."""

    def __init__(self, broken: set[str]) -> None:
        super().__init__({})
        self.broken = broken

    def answer(self, messages: list[dict[str, str]]) -> str:
        import json
        import re

        # The batch's own message, even on a validation retry.
        final = next(
            m["content"]
            for m in reversed(messages)
            if m["content"].startswith((OPERATIONS_MARKER, OVERVIEW_MARKER))
        )
        if final.startswith(OVERVIEW_MARKER):
            return json.dumps({"title": "API", "overview_md": "Written overview."})
        ids = re.findall(r'"id": "(GET /op\d+)"', final)
        if set(ids) & self.broken:
            return "{}"
        return json.dumps(
            {
                "operations": [
                    {
                        "operation_id": op_id,
                        "summary": f"About {op_id}",
                        "description_md": "",
                        "param_descriptions": {},
                        "examples": [],
                    }
                    for op_id in ids
                ]
            }
        )


def run_hybrid(count: int, broken: set[str]) -> Any:
    return generate_hybrid(
        surface=make_surface(count),
        group_of=lambda op: op.group_hint,
        display_name="OpenAPI",
        model=FAKE,
        prompt=HYBRID_PROMPT,
        config=GenerationConfig(fake=BatchAnswers(broken)),
    )


def test_hybrid_strategy_enriches_parsed_operations() -> None:
    result = run_hybrid(3, set())

    assert result.page.strategy == "hybrid"
    assert [docs.operation_id for docs in result.page.operations] == [
        "GET /op0",
        "GET /op1",
        "GET /op2",
    ]
    assert result.page.overview.overview_md == "Written overview."
    assert result.page.overview.groups == {
        "g0": ["GET /op0"],
        "g1": ["GET /op1"],
        "g2": ["GET /op2"],
    }


def test_hybrid_strategy_tolerates_one_failed_batch_in_ten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from d2u.generation import strategies

    monkeypatch.setattr(strategies, "HYBRID_BATCH_MAX_OPERATIONS", 1)

    result = run_hybrid(10, {"GET /op4"})

    assert result.parts_failed == 1
    assert "GET /op4" not in {docs.operation_id for docs in result.page.operations}


def test_hybrid_strategy_fails_when_more_than_ten_percent_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from d2u.generation import strategies

    monkeypatch.setattr(strategies, "HYBRID_BATCH_MAX_OPERATIONS", 1)

    with pytest.raises(
        GenerationFailedError, match="2 of 10 batches failed"
    ) as excinfo:
        run_hybrid(10, {"GET /op1", "GET /op2"})

    assert excinfo.value.provider is False


def test_hybrid_overview_falls_back_when_the_call_fails() -> None:
    fake = FakeResponses(
        {
            OPERATIONS_MARKER: {"operations": []},
        }
    )

    result = generate_hybrid(
        surface=make_surface(2),
        group_of=lambda op: op.group_hint,
        display_name="OpenAPI",
        model=FAKE,
        prompt=HYBRID_PROMPT,
        config=GenerationConfig(fake=fake),
    )

    assert "2 operations" in result.page.overview.overview_md


def test_parser_strategy_uses_no_llm() -> None:
    result = generate_parser(
        surface=make_surface(2),
        group_of=lambda op: op.group_hint,
        display_name="OpenAPI",
    )

    assert result.page.strategy == "parser"
    assert result.page.operations == []
    assert result.usage.calls == 0
