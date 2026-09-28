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

from app.generate.presentation import build_error_view, build_page_view


def make_page(*, docs: list[OperationDocs], groups: dict[str, list[str]]) -> DocPage:
    operations = [
        Operation(
            id="GET /pets",
            kind="http",
            signature="GET /pets",
            group_hint="pets",
            params=[
                Param(
                    id="GET /pets#limit",
                    name="limit",
                    location="query",
                    type="integer",
                    required=False,
                    default="20",
                    source_description="Page size.",
                )
            ],
            returns="200 array[Pet]",
            source_description="List *pets*.",
            location=SourceLocation(path="api.yaml", line=8),
        ),
        Operation(
            id="acme.Client.get",
            kind="method",
            signature="Client.get(key: str) -> bytes",
            group_hint="acme.Client",
            params=[],
        ),
    ]
    return DocPage(
        surface=ApiSurface(title="Pets", language="openapi", operations=operations),
        overview=Overview(overview_md="Overview **text**.", groups=groups),
        operations=docs,
    )


def test_page_view_marks_operations_without_docs_as_not_enriched() -> None:
    page = make_page(docs=[], groups={"pets": ["GET /pets"]})

    view = build_page_view(page=page, language_display="OpenAPI")

    op = view.groups[0].operations[0]
    assert op.enriched is False
    assert op.summary == ""
    assert op.description == "<p>List <em>pets</em>.</p>\n"
    assert op.params[0].description == "<p>Page size.</p>\n"
    assert op.examples == []
    assert op.method == "get"
    assert op.method_class == "get"
    assert op.label == "/pets"
    assert op.returns == "200 array[Pet]"
    assert op.source_location == "api.yaml:8"


def test_page_view_uses_llm_docs_when_present() -> None:
    docs = OperationDocs(
        operation_id="GET /pets",
        summary="List pets",
        description_md="Lists all pets.",
        param_descriptions={"GET /pets#limit": "How many pets to return."},
        examples=[
            Example(title="Shell", language="curl", code="curl /pets"),
            Example(title="Script", language="python", code="client.get()"),
        ],
    )
    page = make_page(docs=[docs], groups={"pets": ["GET /pets"]})

    op = build_page_view(page=page, language_display="OpenAPI").groups[0].operations[0]

    assert op.enriched is True
    assert op.summary == "List pets"
    assert op.description == "<p>Lists all pets.</p>\n"
    assert op.params[0].description == "<p>How many pets to return.</p>\n"
    assert [(tab.label, tab.code) for tab in op.examples] == [
        ("curl", "curl /pets"),
        ("Python", "client.get()"),
    ]
    assert len({tab.anchor for tab in op.examples}) == 2


def test_page_view_ignores_unknown_ids_and_appends_ungrouped_operations() -> None:
    page = make_page(docs=[], groups={"pets": ["GET /pets", "GET /missing"]})

    view = build_page_view(page=page, language_display="OpenAPI")

    assert [
        (group.name, [op.label for op in group.operations]) for group in view.groups
    ] == [
        ("pets", ["/pets"]),
        ("acme.Client", ["Client.get(key: str) -> bytes"]),
    ]


def test_page_view_shows_python_operations_without_a_method_badge() -> None:
    page = make_page(docs=[], groups={})

    view = build_page_view(page=page, language_display="Python")

    op = view.groups[1].operations[0]
    assert op.method == ""
    assert op.method_class == "other"
    assert op.source_location == ""


def test_page_view_anchors_are_unique_and_url_safe() -> None:
    page = make_page(
        docs=[], groups={"pets": ["GET /pets"], "Pets!": ["acme.Client.get"]}
    )

    view = build_page_view(page=page, language_display="OpenAPI")

    assert [group.anchor for group in view.groups] == ["group-pets", "group-pets-2"]
    anchors = [group.anchor for group in view.groups] + [
        op.anchor for group in view.groups for op in group.operations
    ]
    assert len(anchors) == len(set(anchors))
    assert all(anchor.replace("-", "").isalnum() for anchor in anchors)
    assert view.groups[0].operations[0].anchor == "op-get-pets"


def test_page_view_renders_overview_markdown() -> None:
    page = make_page(docs=[], groups={})

    view = build_page_view(page=page, language_display="OpenAPI")

    assert view.title == "Pets"
    assert view.language == "OpenAPI"
    assert view.overview == "<p>Overview <strong>text</strong>.</p>\n"


def test_error_view_is_none_without_an_error_code() -> None:
    assert build_error_view(error_code="", error_detail={}) is None


@pytest.mark.parametrize(
    ("detail", "location"),
    [
        ({"message": "Bad.", "path": "api.yaml", "line": 3}, "api.yaml:3"),
        ({"message": "Bad.", "path": "api.yaml", "line": None}, "api.yaml"),
        ({"message": "Bad.", "path": "", "line": None}, ""),
    ],
)
def test_error_view_formats_input_error_location(detail: dict, location: str) -> None:
    view = build_error_view(error_code="input_error", error_detail=detail)

    assert view is not None
    assert view.title == "Input error"
    assert view.location == location
    assert view.message == "Bad."
