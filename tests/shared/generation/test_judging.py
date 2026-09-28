import json

import pytest
from d2u.generation.client import FakeResponses, ModelSpec
from d2u.generation.exceptions import OutputValidationError
from d2u.generation.judging import documentation_for_judge, judge_page
from d2u.generation.prompts import JUDGE_MARKER
from d2u.schemas.docpage import (
    ApiSurface,
    DocPage,
    Operation,
    OperationDocs,
    Overview,
    Param,
)

FAKE = ModelSpec(name="Judge", litellm_model="fake")
PAGE = DocPage(
    strategy="llm",
    surface=ApiSurface(
        title="Pets",
        language="openapi",
        operations=[
            Operation(
                id="GET /pets",
                kind="http",
                signature="GET /pets",
                group_hint="Pets",
                params=[
                    Param(
                        id="GET /pets#limit",
                        name="limit",
                        location="query",
                        type="integer",
                        required=False,
                    ),
                    Param(
                        id="GET /pets#q",
                        name="q",
                        location="query",
                        type="string",
                        required=False,
                        source_description="Search.",
                    ),
                ],
            )
        ],
    ),
    overview=Overview(overview_md="All about pets.", groups={"Pets": ["GET /pets"]}),
    operations=[
        OperationDocs(
            operation_id="GET /pets",
            summary="List pets",
            description_md="Lists pets.",
            param_descriptions={"GET /pets#limit": "Page size."},
            examples=[],
        )
    ],
)
VERDICT = {
    "claims": [
        {"operation_id": "GET /pets", "claim": "Lists pets.", "supported": True}
    ],
    "prose_quality": 4,
}


def test_the_judge_reads_every_operations_prose() -> None:
    documentation = json.loads(documentation_for_judge(PAGE))

    assert documentation["overview"] == "All about pets."
    (op,) = documentation["operations"]
    assert op["summary"] == "List pets"
    assert op["parameters"] == {"limit": "Page size.", "q": "Search."}


def test_a_judge_verdict_is_requested_as_structured_output() -> None:
    result = judge_page(
        model=FAKE,
        source_files={"api.yaml": "openapi: 3.0.0"},
        page=PAGE,
        fake=FakeResponses({JUDGE_MARKER: VERDICT}),
    )

    assert result.value.prose_quality == 4
    assert result.value.claims[0].supported is True


def test_an_out_of_range_rating_is_rejected() -> None:
    with pytest.raises(OutputValidationError):
        judge_page(
            model=FAKE,
            source_files={"api.yaml": "openapi: 3.0.0"},
            page=PAGE,
            fake=FakeResponses({JUDGE_MARKER: VERDICT | {"prose_quality": 9}}),
        )
