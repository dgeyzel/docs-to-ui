import pytest
from d2u.generation.convert import (
    base_operation_id,
    docpage_to_generated,
    generated_to_docpage,
    merge_parts,
    normalize_path,
)
from d2u.schemas.docpage import ApiSurface, DocPage, Operation, Overview, Param
from d2u.schemas.generated import GeneratedOperation, GeneratedPage, GeneratedParam


def make_op(**fields: object) -> GeneratedOperation:
    defaults: dict[str, object] = {
        "kind": "http",
        "method": "get",
        "path": "/pets",
        "signature": "GET /pets",
        "group": "Pets",
        "summary": "List pets",
    }
    return GeneratedOperation.model_validate(defaults | fields)


def make_page(*ops: GeneratedOperation, title: str = "API") -> GeneratedPage:
    return GeneratedPage(title=title, overview_md="Overview.", operations=list(ops))


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"method": "get", "path": "pets/"}, "GET /pets"),
        ({"method": " Post ", "path": "//orders//{id}/"}, "POST /orders/{id}"),
        ({"kind": "method", "qualified_name": " acme.Client.get "}, "acme.Client.get"),
        ({"method": None, "path": None, "signature": "GET /fallback"}, "GET /fallback"),
        ({"kind": "function", "qualified_name": None, "signature": "f(x)"}, "f(x)"),
    ],
)
def test_ids_are_derived_from_the_llms_fields(fields: dict, expected: str) -> None:
    assert base_operation_id(make_op(**fields)) == expected


def test_normalize_path_keeps_the_root() -> None:
    assert normalize_path("/") == "/"


def test_conversion_splits_structure_from_prose() -> None:
    op = make_op(
        description_md="Lists pets.",
        params=[
            GeneratedParam(
                name="limit",
                location="query",
                type="integer",
                required=False,
                default="20",
                description="Page size.",
            ),
            GeneratedParam(name="q", location="query", type="string", required=False),
        ],
        returns="200 array[Pet]",
        source_path="api.yaml",
        source_line=3,
    )

    page, report = generated_to_docpage(
        make_page(op), language="openapi", line_counts={"api.yaml": 10}
    )

    (operation,) = page.surface.operations
    (docs,) = page.operations
    assert page.strategy == "llm"
    assert operation.id == "GET /pets"
    assert [(p.id, p.default) for p in operation.params] == [
        ("GET /pets#limit", "20"),
        ("GET /pets#q", None),
    ]
    assert operation.location is not None
    assert (operation.location.path, operation.location.line) == ("api.yaml", 3)
    assert docs.param_descriptions == {"GET /pets#limit": "Page size."}
    assert docs.description_md == "Lists pets."
    assert page.overview.groups == {"Pets": ["GET /pets"]}
    assert report.id_collisions == []


def test_colliding_ids_get_deterministic_suffixes() -> None:
    first = make_op(summary="First")
    second = make_op(summary="Second", path="/pets/")

    page, report = generated_to_docpage(
        make_page(first, second), language="openapi", line_counts={}
    )

    assert [op.id for op in page.surface.operations] == ["GET /pets", "GET /pets~2"]
    assert report.id_collisions == ["GET /pets~2"]


@pytest.mark.parametrize(
    ("path", "line"), [("missing.yaml", 1), ("api.yaml", 0), ("api.yaml", 11)]
)
def test_source_locations_outside_the_input_are_dropped(path: str, line: int) -> None:
    op = make_op(source_path=path, source_line=line)

    page, report = generated_to_docpage(
        make_page(op), language="openapi", line_counts={"api.yaml": 10}
    )

    assert page.surface.operations[0].location is None
    assert report.dropped_locations == [f"{path}:{line}"]


def test_empty_groups_fall_under_other() -> None:
    page, _ = generated_to_docpage(
        make_page(make_op(group=" ")), language="openapi", line_counts={}
    )

    assert page.overview.groups == {"Other": ["GET /pets"]}


def test_merge_parts_unions_operations_and_reports_duplicates() -> None:
    first = make_page(
        make_op(), make_op(method="POST", signature="POST /pets"), title="First"
    )
    second = make_page(
        make_op(summary="Duplicate"),
        make_op(path="/orders", signature="GET /orders"),
        title="Second",
    )

    merged, duplicates = merge_parts([first, second])

    assert merged.title == "First"
    assert [op.signature for op in merged.operations] == [
        "GET /pets",
        "POST /pets",
        "GET /orders",
    ]
    assert merged.operations[0].summary == "List pets"
    assert duplicates == ["GET /pets"]


def test_a_stored_page_converts_back_to_what_was_generated() -> None:
    generated = make_page(
        make_op(
            description_md="Lists pets.",
            params=[
                GeneratedParam(
                    name="limit",
                    location="query",
                    type="integer",
                    required=False,
                    default="20",
                    description="Page size.",
                )
            ],
            returns="200 array[Pet]",
            source_path="api.yaml",
            source_line=3,
        ),
        make_op(
            kind="method",
            method=None,
            path=None,
            qualified_name="acme.Client.get",
            signature="get(key)",
            group="Client",
            summary="Get a key",
        ),
    )
    page, _ = generated_to_docpage(
        generated, language="openapi", line_counts={"api.yaml": 10}
    )

    back = docpage_to_generated(page)

    assert back.operations[0].method == "GET"
    assert back.operations[0].path == "/pets"
    assert back.operations[0].params[0].description == "Page size."
    assert back.operations[1].qualified_name == "acme.Client.get"
    again, _ = generated_to_docpage(
        back, language="openapi", line_counts={"api.yaml": 10}
    )
    assert again == page


def test_colliding_ids_convert_back_without_their_suffix() -> None:
    page, _ = generated_to_docpage(
        make_page(make_op(), make_op(summary="Again")),
        language="openapi",
        line_counts={},
    )

    back = docpage_to_generated(page)

    assert [op.path for op in back.operations] == ["/pets", "/pets"]


def test_operations_without_docs_use_their_source_descriptions() -> None:
    page = DocPage(
        strategy="parser",
        surface=ApiSurface(
            title="API",
            language="openapi",
            operations=[
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
                            source_description="How many.",
                        )
                    ],
                    source_description="List pets.\nMore detail.",
                )
            ],
        ),
        overview=Overview(overview_md="", groups={}),
        operations=[],
    )

    (op,) = docpage_to_generated(page).operations

    assert op.summary == "List pets."
    assert op.group == "pets"
    assert op.params[0].description == "How many."
