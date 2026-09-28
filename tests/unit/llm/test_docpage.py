from app.llm.docpage import build_unenriched_docpage
from app.llm.schemas import ApiSurface, Operation


def make_op(op_id: str, group: str) -> Operation:
    return Operation(
        id=op_id, kind="http", signature=op_id, group_hint=group, params=[]
    )


def test_unenriched_docpage_groups_operations_in_first_seen_order() -> None:
    surface = ApiSurface(
        title="API",
        language="openapi",
        operations=[
            make_op("GET /b", "beta"),
            make_op("GET /a", "alpha"),
            make_op("POST /b", "beta"),
        ],
    )

    page = build_unenriched_docpage(
        surface=surface, group_of=lambda op: op.group_hint, display_name="OpenAPI"
    )

    assert page.overview.groups == {
        "beta": ["GET /b", "POST /b"],
        "alpha": ["GET /a"],
    }
    assert page.operations == []
    assert page.surface == surface
    assert "3 operations" in page.overview.overview_md
    assert "OpenAPI" in page.overview.overview_md


def test_unenriched_docpage_uses_singular_for_one_operation() -> None:
    surface = ApiSurface(
        title="API", language="openapi", operations=[make_op("GET /a", "a")]
    )

    page = build_unenriched_docpage(
        surface=surface, group_of=lambda op: op.group_hint, display_name="OpenAPI"
    )

    assert "1 operation " in page.overview.overview_md
