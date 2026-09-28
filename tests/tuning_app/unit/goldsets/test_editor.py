import pytest
from d2u.generation.convert import generated_to_docpage
from d2u.schemas.generated import GeneratedOperation, GeneratedPage, GeneratedParam

from app.goldsets import editor


def page_form(**overrides: str) -> dict[str, str]:
    """Form data for one HTTP operation with one parameter and one example."""
    data = {
        "title": "Pets API",
        "overview_md": "Pets.",
        "op-count": "1",
        "op-0-kind": "http",
        "op-0-method": "get",
        "op-0-path": "/pets",
        "op-0-qualified_name": "",
        "op-0-signature": "GET /pets",
        "op-0-group": "Pets",
        "op-0-summary": "List pets",
        "op-0-description_md": "Lists pets.",
        "op-0-returns": "",
        "op-0-source_path": "",
        "op-0-source_line": "",
        "op-0-param-count": "1",
        "op-0-param-0-name": "limit",
        "op-0-param-0-location": "query",
        "op-0-param-0-type": "integer",
        "op-0-param-0-required": "true",
        "op-0-param-0-default": "",
        "op-0-param-0-description": "Page size.",
        "op-0-example-count": "1",
        "op-0-example-0-title": "Shell",
        "op-0-example-0-language": "curl",
        "op-0-example-0-code": "curl /pets",
    }
    return data | overrides


def test_form_data_becomes_a_generated_page() -> None:
    result = editor.validate(editor.state_from_form(page_form()))

    assert result.errors == {}
    assert result.page is not None
    (op,) = result.page.operations
    assert (op.method, op.path, op.returns, op.source_line) == (
        "get",
        "/pets",
        None,
        None,
    )
    assert op.params[0].required is True
    assert op.params[0].default is None
    assert op.examples[0].code == "curl /pets"


def test_unchecked_boxes_mean_not_required() -> None:
    data = page_form()
    del data["op-0-param-0-required"]

    result = editor.validate(editor.state_from_form(data))

    assert result.page is not None
    assert result.page.operations[0].params[0].required is False


@pytest.mark.parametrize(
    ("overrides", "field", "message"),
    [
        ({"op-0-summary": "x" * 201}, "op-0-summary", "at most 200 characters"),
        (
            {"op-0-param-0-location": "cookie"},
            "op-0-param-0-location",
            "Input should be",
        ),
        ({"op-0-source_line": "ten"}, "op-0-source_line", "valid integer"),
        ({"op-0-path": ""}, "op-0-path", "need a method and a path"),
        (
            {"op-0-kind": "function", "op-0-method": "", "op-0-path": ""},
            "op-0-qualified_name",
            "Enter the qualified name",
        ),
    ],
)
def test_errors_are_reported_next_to_their_input(
    overrides: dict[str, str], field: str, message: str
) -> None:
    result = editor.validate(editor.state_from_form(page_form(**overrides)))

    assert result.page is None
    assert message in result.errors[field]


def test_two_operations_with_the_same_id_are_rejected() -> None:
    data = page_form(**{"op-count": "2"})
    data |= {
        key.replace("op-0-", "op-1-"): value
        for key, value in page_form().items()
        if key.startswith("op-0-")
    }

    result = editor.validate(editor.state_from_form(data))

    assert result.errors == {
        "op-1-signature": "Operation 1 already has the ID GET /pets."
    }


def test_duplicate_parameter_names_are_rejected() -> None:
    data = page_form(**{"op-0-param-count": "2"})
    data |= {
        key.replace("param-0", "param-1"): value
        for key, value in page_form().items()
        if "param-0" in key
    }

    result = editor.validate(editor.state_from_form(data))

    assert result.errors == {"op-0-param-1-name": "Another parameter has this name."}


@pytest.mark.parametrize(
    ("action", "check"),
    [
        ("add_operation", lambda s: len(s["operations"]) == 2),
        ("remove_operation-0", lambda s: s["operations"] == []),
        ("add_param-0", lambda s: len(s["operations"][0]["params"]) == 2),
        ("remove_param-0-0", lambda s: s["operations"][0]["params"] == []),
        ("add_example-0", lambda s: len(s["operations"][0]["examples"]) == 2),
        ("remove_example-0-0", lambda s: s["operations"][0]["examples"] == []),
    ],
)
def test_structural_actions_edit_the_state(action: str, check) -> None:
    state = editor.state_from_form(page_form())

    assert editor.apply_action(state, action, language="openapi") is True
    assert check(state)


@pytest.mark.parametrize(
    "action", ["remove_operation-5", "delete_everything", "add_param-9"]
)
def test_unknown_or_out_of_range_actions_are_refused(action: str) -> None:
    assert (
        editor.apply_action(
            editor.state_from_form(page_form()), action, language="openapi"
        )
        is False
    )


def test_new_rows_default_to_the_languages_usual_kinds() -> None:
    state = editor.state_from_form(page_form(**{"op-count": "0"}))
    editor.apply_action(state, "add_operation", language="python")
    editor.apply_action(state, "add_param-0", language="python")

    assert state["operations"][0]["kind"] == "function"
    assert state["operations"][0]["params"][0]["location"] == "arg"


def test_row_counts_are_capped_and_garbage_counts_are_ignored() -> None:
    assert (
        len(editor.state_from_form({"op-count": "100000"})["operations"])
        == editor.MAX_ROWS
    )
    assert editor.state_from_form({"op-count": "-1"})["operations"] == []


def test_a_stored_page_round_trips_through_the_editor() -> None:
    generated = GeneratedPage(
        title="API",
        overview_md="Overview.",
        operations=[
            GeneratedOperation(
                kind="http",
                method="GET",
                path="/pets",
                signature="GET /pets",
                group="Pets",
                summary="List pets",
                params=[
                    GeneratedParam(
                        name="limit",
                        location="query",
                        type="integer",
                        required=False,
                        default="20",
                    )
                ],
                source_line=None,
            )
        ],
    )
    page, _ = generated_to_docpage(generated, language="openapi", line_counts={})
    state = editor.state_from_page(page)
    form = {
        "title": state["title"],
        "overview_md": state["overview_md"],
        "op-count": "1",
    }
    op = state["operations"][0]
    form |= {f"op-0-{name}": op[name] for name in editor.OPERATION_FIELDS}
    form |= {"op-0-param-count": "1", "op-0-example-count": "0"}
    form |= {
        f"op-0-param-0-{name}": op["params"][0][name] for name in editor.PARAM_FIELDS
    }

    result = editor.validate(editor.state_from_form(form))

    assert result.page is not None
    again, _ = generated_to_docpage(result.page, language="openapi", line_counts={})
    assert again == page


def test_the_editor_shows_the_id_an_operation_will_get() -> None:
    state = editor.state_from_form(page_form())

    assert editor.operation_id(state["operations"][0]) == "GET /pets"
    assert editor.operation_id({**state["operations"][0], "summary": "x" * 300}) == ""
