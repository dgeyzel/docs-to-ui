from itertools import pairwise

import pytest

from app.llm.schemas import Operation
from app.sources.adapters.openapi import OpenApiAdapter
from app.sources.bundle import SourceBundle, SourceFile
from app.sources.exceptions import InputError
from tests.helpers import bundle_of, read_fixture

PETSTORE = "petstore-3.0.yaml"
NOTES = "notes-3.1.json"


@pytest.fixture
def adapter() -> OpenApiAdapter:
    return OpenApiAdapter()


def extract_fixture(adapter: OpenApiAdapter, name: str) -> dict[str, Operation]:
    surface = adapter.extract(bundle_of(name, read_fixture(f"openapi/{name}")))
    return {op.id: op for op in surface.operations}


def test_extract_lists_operations_in_document_order(adapter: OpenApiAdapter) -> None:
    surface = adapter.extract(bundle_of(PETSTORE, read_fixture(f"openapi/{PETSTORE}")))

    assert surface.title == "Petstore Plus API"
    assert surface.language == "openapi"
    assert [op.id for op in surface.operations] == [
        "GET /pets",
        "POST /pets",
        "GET /pets/{petId}",
        "DELETE /pets/{petId}",
        "PATCH /orders/{orderId}",
    ]


def test_extract_ids_are_stable_across_runs(adapter: OpenApiAdapter) -> None:
    first = adapter.extract(bundle_of(PETSTORE, read_fixture(f"openapi/{PETSTORE}")))
    second = adapter.extract(bundle_of(PETSTORE, read_fixture(f"openapi/{PETSTORE}")))

    assert first == second


def test_extract_resolves_parameter_refs_and_skips_cookies(
    adapter: OpenApiAdapter,
) -> None:
    op = extract_fixture(adapter, PETSTORE)["GET /pets"]

    assert [(p.id, p.location, p.type) for p in op.params] == [
        ("GET /pets#limit", "query", "integer(int32)"),
        ("GET /pets#X-Request-Id", "header", "string(uuid)"),
    ]
    assert op.params[0].default == "20"
    assert op.params[0].required is False
    assert op.params[0].source_description == "Maximum number of pets to return."


def test_extract_inherits_path_level_parameters_as_required(
    adapter: OpenApiAdapter,
) -> None:
    op = extract_fixture(adapter, PETSTORE)["DELETE /pets/{petId}"]

    assert [(p.id, p.location, p.required) for p in op.params] == [
        ("DELETE /pets/{petId}#petId", "path", True),
    ]


def test_extract_request_body_becomes_a_body_param(adapter: OpenApiAdapter) -> None:
    op = extract_fixture(adapter, PETSTORE)["POST /pets"]

    body = op.params[-1]
    assert body.id == "POST /pets#body"
    assert body.location == "body"
    assert body.type == "NewPet"
    assert body.required is True
    assert body.source_description == "The pet to create."


def test_extract_describes_operation_from_summary_and_description(
    adapter: OpenApiAdapter,
) -> None:
    op = extract_fixture(adapter, PETSTORE)["GET /pets"]

    assert op.kind == "http"
    assert op.signature == "GET /pets"
    assert op.source_description == (
        "List available pets\n\nReturns a paginated list of pets."
    )
    assert op.returns == "200 array[Pet]"


def test_extract_records_the_source_location_of_each_operation(
    adapter: OpenApiAdapter,
) -> None:
    ops = extract_fixture(adapter, PETSTORE)

    assert ops["GET /pets"].location is not None
    assert ops["GET /pets"].location.path == PETSTORE
    assert ops["GET /pets"].location.line == 8
    assert ops["PATCH /orders/{orderId}"].location is not None
    assert ops["PATCH /orders/{orderId}"].location.line == 72


@pytest.mark.parametrize(
    ("op_id", "expected"),
    [
        ("GET /pets/{petId}", "200 Pet"),
        ("DELETE /pets/{petId}", "204 Deleted."),
        ("PATCH /orders/{orderId}", "default The updated order."),
    ],
)
def test_extract_summarizes_the_success_response(
    adapter: OpenApiAdapter, op_id: str, expected: str
) -> None:
    assert extract_fixture(adapter, PETSTORE)[op_id].returns == expected


def test_extract_marks_nullable_schemas(adapter: OpenApiAdapter) -> None:
    op = extract_fixture(adapter, PETSTORE)["PATCH /orders/{orderId}"]

    assert [(p.name, p.type) for p in op.params] == [
        ("orderId", "integer"),
        ("status", "string | null"),
    ]


def test_extract_supports_openapi_3_1_json(adapter: OpenApiAdapter) -> None:
    ops = extract_fixture(adapter, NOTES)

    assert ops["GET /notes"].params[0].type == "string | null"
    assert ops["POST /notes"].params[0].type == "Note | string"
    assert ops["POST /notes"].params[0].required is False


@pytest.mark.parametrize(
    ("op_id", "group"),
    [
        ("GET /pets", "Pets"),
        ("PATCH /orders/{orderId}", "orders"),
    ],
)
def test_group_key_uses_first_tag_or_first_path_segment(
    adapter: OpenApiAdapter, op_id: str, group: str
) -> None:
    op = extract_fixture(adapter, PETSTORE)[op_id]

    assert adapter.group_key(op) == group


@pytest.mark.parametrize(
    ("path", "included"),
    [
        ("api.yaml", True),
        ("api.YML", True),
        ("spec/api.json", True),
        ("client.py", False),
        ("README.md", False),
    ],
)
def test_includes_only_json_and_yaml_files(
    adapter: OpenApiAdapter, path: str, included: bool
) -> None:
    assert adapter.includes(path) is included


@pytest.mark.parametrize(
    ("path", "text", "score"),
    [
        ("api.yaml", "openapi: 3.1.0\n", 1.0),
        ("api.json", '{"openapi": "3.0.0"}', 1.0),
        ("config.yaml", "name: something\n", 0.1),
        ("client.py", "openapi: 3.1.0\n", 0.0),
    ],
)
def test_sniff_scores_documents_with_an_openapi_key(
    adapter: OpenApiAdapter, path: str, text: str, score: float
) -> None:
    assert adapter.sniff(bundle_of(path, text)) == score


def test_extract_reports_yaml_syntax_errors_with_line(adapter: OpenApiAdapter) -> None:
    text = "openapi: 3.0.0\ninfo:\n  title: Broken\npaths:\n  /a: [\n"

    with pytest.raises(InputError, match="Invalid YAML/JSON") as excinfo:
        adapter.extract(bundle_of("broken.yaml", text))

    assert excinfo.value.path == "broken.yaml"
    assert excinfo.value.line == 6


def test_extract_rejects_swagger_2(adapter: OpenApiAdapter) -> None:
    with pytest.raises(InputError, match="Swagger 2.0 is not supported") as excinfo:
        adapter.extract(bundle_of("old.yaml", 'swagger: "2.0"\npaths: {}\n'))

    assert excinfo.value.line == 1


def test_extract_rejects_unsupported_versions(adapter: OpenApiAdapter) -> None:
    text = "info:\n  title: X\nopenapi: 4.0.0\npaths: {}\n"

    with pytest.raises(InputError, match="Unsupported OpenAPI version") as excinfo:
        adapter.extract(bundle_of("api.yaml", text))

    assert excinfo.value.line == 3


@pytest.mark.parametrize(
    ("ref", "message"),
    [
        ("other.yaml#/components/parameters/Limit", "was not found in the input"),
        (
            "https://example.com/spec.yaml#/components/parameters/Limit",
            "Remote \\$refs are not supported",
        ),
        ("//cdn.example.com/spec.yaml", "Remote \\$refs are not supported"),
        ("../outside.yaml#/X", "points outside the input"),
        ("/etc/spec.yaml#/X", "must be relative paths"),
    ],
)
def test_extract_rejects_refs_it_cannot_follow_safely(
    adapter: OpenApiAdapter, ref: str, message: str
) -> None:
    text = (
        "openapi: 3.0.0\n"
        "info: {title: X, version: '1'}\n"
        "paths:\n"
        "  /a:\n"
        "    get:\n"
        "      parameters:\n"
        f"        - $ref: '{ref}'\n"
        "      responses: {}\n"
    )

    with pytest.raises(InputError, match=message) as excinfo:
        adapter.extract(bundle_of("api.yaml", text))

    assert excinfo.value.line == 7


def test_extract_reports_unresolvable_refs(adapter: OpenApiAdapter) -> None:
    text = (
        "openapi: 3.0.0\n"
        "info: {title: X, version: '1'}\n"
        "paths:\n"
        "  /a:\n"
        "    get:\n"
        "      parameters:\n"
        "        - $ref: '#/components/parameters/Missing'\n"
    )

    with pytest.raises(InputError, match="does not resolve") as excinfo:
        adapter.extract(bundle_of("api.yaml", text))

    assert excinfo.value.line == 7


def test_extract_detects_circular_refs(adapter: OpenApiAdapter) -> None:
    text = (
        "openapi: 3.0.0\n"
        "info: {title: X, version: '1'}\n"
        "paths:\n"
        "  /a:\n"
        "    get:\n"
        "      parameters:\n"
        "        - $ref: '#/components/parameters/A'\n"
        "components:\n"
        "  parameters:\n"
        "    A: {$ref: '#/components/parameters/B'}\n"
        "    B: {$ref: '#/components/parameters/A'}\n"
    )

    with pytest.raises(InputError, match="cycle"):
        adapter.extract(bundle_of("api.yaml", text))


def test_extract_rejects_malformed_parameters(adapter: OpenApiAdapter) -> None:
    text = (
        "openapi: 3.0.0\n"
        "info: {title: X, version: '1'}\n"
        "paths:\n"
        "  /a:\n"
        "    get:\n"
        "      parameters:\n"
        "        - in: query\n"
    )

    with pytest.raises(InputError, match="string `name`") as excinfo:
        adapter.extract(bundle_of("api.yaml", text))

    assert excinfo.value.line == 7


def test_extract_rejects_documents_without_operations(adapter: OpenApiAdapter) -> None:
    text = "openapi: 3.1.0\ninfo: {title: X, version: '1'}\npaths: {}\n"

    with pytest.raises(InputError, match="defines no operations"):
        adapter.extract(bundle_of("api.yaml", text))


def test_extract_rejects_a_non_mapping_document(adapter: OpenApiAdapter) -> None:
    with pytest.raises(InputError, match="must be a mapping"):
        adapter.extract(bundle_of("api.yaml", "- just\n- a list\n"))


def test_extract_survives_yaml_alias_bombs(adapter: OpenApiAdapter) -> None:
    # Each level repeats the previous one ten times: 10**9 leaves if walked naively.
    names = "abcdefghi"
    lines = ["  a: &a [x, x, x, x, x, x, x, x, x, x]"]
    for previous, name in pairwise(names):
        items = ", ".join([f"*{previous}"] * 10)
        lines.append(f"  {name}: &{name} [{items}]")
    text = (
        "openapi: 3.0.0\n"
        "info: {title: X, version: '1'}\n"
        "x-bomb:\n" + "\n".join(lines) + "\n"
        "paths:\n"
        "  /a:\n"
        "    get:\n"
        "      responses: {}\n"
    )

    surface = adapter.extract(bundle_of("api.yaml", text))

    assert [op.id for op in surface.operations] == ["GET /a"]


def test_extract_rejects_several_entry_files(adapter: OpenApiAdapter) -> None:
    bundle = SourceBundle(
        files=[
            SourceFile(path="a.yaml", text="openapi: 3.0.0\n"),
            SourceFile(path="b.yaml", text="openapi: 3.0.0\n"),
        ],
        origin="zip",
    )

    with pytest.raises(InputError, match="Several files look like OpenAPI"):
        adapter.extract(bundle)


def test_extract_requires_an_openapi_file(adapter: OpenApiAdapter) -> None:
    with pytest.raises(InputError, match="No OpenAPI file"):
        adapter.extract(bundle_of("client.py", "def f(): pass\n"))
