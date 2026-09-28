import pydantic
import pytest
from d2u.schemas.docpage import (
    ApiSurface,
    DocPage,
    Example,
    Operation,
    OperationDocs,
    Overview,
    Param,
    SourceLocation,
)


def test_docpage_round_trips_through_json() -> None:
    page = DocPage(
        surface=ApiSurface(
            title="API",
            language="openapi",
            operations=[
                Operation(
                    id="GET /a",
                    kind="http",
                    signature="GET /a",
                    group_hint="a",
                    params=[
                        Param(
                            id="GET /a#q",
                            name="q",
                            location="query",
                            type="string",
                            required=True,
                        )
                    ],
                    location=SourceLocation(path="api.yaml", line=3),
                )
            ],
        ),
        overview=Overview(overview_md="Hi", groups={"a": ["GET /a"]}),
        operations=[
            OperationDocs(
                operation_id="GET /a",
                summary="Get a",
                description_md="Gets a.",
                param_descriptions={"GET /a#q": "Query."},
                examples=[Example(title="curl", language="curl", code="curl /a")],
            )
        ],
    )

    assert DocPage.model_validate_json(page.model_dump_json()) == page
    assert page.schema_version == 2
    assert page.strategy == "hybrid"


def test_operation_docs_summary_is_limited_to_200_characters() -> None:
    with pytest.raises(pydantic.ValidationError):
        OperationDocs(
            operation_id="x",
            summary="s" * 201,
            description_md="",
            param_descriptions={},
            examples=[],
        )


def test_param_location_must_be_a_known_value() -> None:
    with pytest.raises(pydantic.ValidationError):
        Param.model_validate(
            {
                "id": "x",
                "name": "x",
                "location": "cookie",
                "type": "s",
                "required": True,
            }
        )


def test_pages_stored_before_version_2_read_as_hybrid() -> None:
    stored = {
        "schema_version": 1,
        "surface": {"title": "API", "language": "openapi", "operations": []},
        "overview": {"overview_md": "", "groups": {}},
        "operations": [],
    }

    page = DocPage.model_validate(stored)

    assert page.strategy == "hybrid"
    assert page.schema_version == 1
