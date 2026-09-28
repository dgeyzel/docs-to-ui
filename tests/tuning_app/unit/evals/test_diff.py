from app.evals.metrics.diff import Presence, page_diff
from tests.tuning_app.unit.evals.pages import http_op, page, param

GOLD = page(
    http_op("GET", "/pets", param("limit", default="20"), returns="200 array"),
    http_op("POST", "/pets"),
)


def test_identical_pages_have_no_differences() -> None:
    diff = page_diff(GOLD, GOLD)

    assert [op.presence for op in diff.operations] == [
        Presence.MATCHED,
        Presence.MATCHED,
    ]
    assert not any(op.differs for op in diff.operations)
    assert diff.wrong_fields == 0


def test_missing_invented_and_wrong_fields_are_reported() -> None:
    generated = page(
        http_op(
            "GET",
            "/pets",
            param("limit", type="string", default="20"),
            param("q"),
            returns="200 object",
        ),
        http_op("DELETE", "/pets"),
    )

    diff = page_diff(generated, GOLD)

    get, post, delete = diff.operations
    assert (get.presence, post.presence, delete.presence) == (
        "matched",
        "missing",
        "invented",
    )
    assert [(f.field, f.expected, f.generated) for f in get.fields] == [
        ("returns", "200 array", "200 object")
    ]
    limit, q = get.params
    assert [(f.field, f.expected, f.generated) for f in limit.fields] == [
        ("type", "integer", "string")
    ]
    assert q.presence == Presence.INVENTED
    assert diff.count(Presence.MISSING) == 1
    assert diff.wrong_fields == 2
    assert get.differs


def test_loose_differences_in_case_quotes_and_spacing_are_ignored() -> None:
    generated = page(
        http_op("GET", "/pets", param("limit", default="'20'"), returns="200  ARRAY"),
        http_op("POST", "/pets", group="pets"),
    )

    assert page_diff(generated, GOLD).wrong_fields == 0
