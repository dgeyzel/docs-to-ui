from d2u.generation.merge import merge_enrichment, merge_overview, order_docs
from d2u.schemas.docpage import ApiSurface, Operation, OperationDocs, Overview, Param


def make_op(op_id: str, param_names: tuple[str, ...] = ()) -> Operation:
    return Operation(
        id=op_id,
        kind="http",
        signature=op_id,
        group_hint="g",
        params=[
            Param(
                id=f"{op_id}#{name}",
                name=name,
                location="query",
                type="string",
                required=False,
            )
            for name in param_names
        ],
    )


def make_docs(op_id: str, params: dict[str, str] | None = None) -> OperationDocs:
    return OperationDocs(
        operation_id=op_id,
        summary=f"About {op_id}",
        description_md="",
        param_descriptions=params or {},
        examples=[],
    )


def test_merge_enrichment_drops_unknown_operations_and_params() -> None:
    ops = [make_op("GET /a", ("q",))]
    docs = [
        make_docs("GET /a", {"GET /a#q": "Query.", "GET /a#nope": "Invented."}),
        make_docs("GET /invented"),
    ]

    kept, report = merge_enrichment(ops, docs)

    assert [entry.operation_id for entry in kept] == ["GET /a"]
    assert kept[0].param_descriptions == {"GET /a#q": "Query."}
    assert report.unknown_operation_ids == ["GET /invented"]
    assert report.unknown_param_ids == ["GET /a#nope"]
    assert report.dropped is True


def test_merge_enrichment_keeps_the_first_duplicate() -> None:
    ops = [make_op("GET /a")]
    first = make_docs("GET /a")
    second = first.model_copy(update={"summary": "Second"})

    kept, report = merge_enrichment(ops, [first, second])

    assert kept == [first]
    assert report.dropped is False


def test_merge_overview_filters_groups_to_known_ids_once_each() -> None:
    surface = ApiSurface(
        title="API", language="openapi", operations=[make_op("A"), make_op("B")]
    )
    overview = Overview(
        overview_md="Hi",
        groups={"One": ["A", "X"], "Two": ["A", "B"], "Empty": ["Y"], " ": ["B"]},
    )

    merged, report = merge_overview(surface, overview)

    assert merged.groups == {"One": ["A"], "Two": ["B"]}
    assert merged.overview_md == "Hi"
    assert report.unknown_operation_ids == ["X", "Y"]


def test_order_docs_follows_surface_order() -> None:
    surface = ApiSurface(
        title="API", language="openapi", operations=[make_op("A"), make_op("B")]
    )

    ordered = order_docs(surface, [make_docs("B"), make_docs("A")])

    assert [entry.operation_id for entry in ordered] == ["A", "B"]
