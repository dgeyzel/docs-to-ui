import pytest

from app.sources.adapters.openapi import OpenApiAdapter
from app.sources.bundle import SourceBundle, SourceFile
from app.sources.exceptions import InputError
from app.sources.registry import select_files
from tests.helpers import FIXTURES_DIR, bundle_from_dir

MULTI = FIXTURES_DIR / "openapi" / "multi"


@pytest.fixture
def adapter() -> OpenApiAdapter:
    return OpenApiAdapter()


def zip_bundle(files: dict[str, str], *, entry: str | None = None) -> SourceBundle:
    return SourceBundle(
        files=[SourceFile(path=path, text=text) for path, text in files.items()],
        origin="zip",
        entry=entry,
    )


def test_relative_refs_resolve_across_bundle_files(adapter: OpenApiAdapter) -> None:
    bundle, skipped = select_files(bundle_from_dir(MULTI), adapter)

    surface = adapter.extract(bundle)

    ops = {op.id: op for op in surface.operations}
    assert surface.title == "Multi API"
    assert list(ops) == ["GET /pets", "GET /status"]
    pets = ops["GET /pets"]
    assert [(p.name, p.type, p.source_description) for p in pets.params] == [
        ("limit", "integer", "Page size.")
    ]
    assert pets.returns == "200 array[pet]"
    assert pets.group_hint == "Pets"
    assert ops["GET /status"].returns == "200 Status"
    assert [(entry.path, entry.reason) for entry in skipped] == [
        ("README.md", "not an OpenAPI file")
    ]


def test_operations_from_referenced_files_point_to_those_files(
    adapter: OpenApiAdapter,
) -> None:
    bundle, _ = select_files(bundle_from_dir(MULTI), adapter)

    ops = {op.id: op for op in adapter.extract(bundle).operations}

    assert ops["GET /pets"].location is not None
    assert ops["GET /pets"].location.path == "api/paths/pets.yaml"
    assert ops["GET /pets"].location.line == 1
    assert ops["GET /status"].location is not None
    assert ops["GET /status"].location.path == "api/openapi.yaml"


def test_errors_in_referenced_files_name_that_file(adapter: OpenApiAdapter) -> None:
    bundle = zip_bundle(
        {
            "openapi.yaml": "openapi: 3.0.0\ninfo: {title: X, version: '1'}\npaths:\n  /a:\n    $ref: 'paths.yaml'\n",
            "paths.yaml": "get:\n  parameters:\n    - in: query\n",
        }
    )

    with pytest.raises(InputError, match="string `name`") as excinfo:
        adapter.extract(bundle)

    assert (excinfo.value.path, excinfo.value.line) == ("paths.yaml", 3)


def test_remote_refs_in_referenced_files_are_rejected(adapter: OpenApiAdapter) -> None:
    bundle = zip_bundle(
        {
            "openapi.yaml": "openapi: 3.0.0\ninfo: {title: X, version: '1'}\npaths:\n  /a:\n    $ref: 'paths.yaml'\n",
            "paths.yaml": "get:\n  responses:\n    '200':\n      $ref: 'https://evil.example/r.yaml'\n",
        }
    )

    with pytest.raises(InputError, match="Remote \\$refs") as excinfo:
        adapter.extract(bundle)

    assert excinfo.value.path == "paths.yaml"


def test_several_entry_files_require_a_choice(adapter: OpenApiAdapter) -> None:
    spec = (
        "openapi: 3.0.0\ninfo: {title: X, version: '1'}\npaths:\n  /a:\n    get: {}\n"
    )
    files = {"v1/openapi.yaml": spec, "v2/openapi.yaml": spec.replace("/a", "/b")}

    with pytest.raises(InputError, match="Choose one in the Entry file field"):
        adapter.extract(zip_bundle(files))

    chosen = adapter.extract(zip_bundle(files, entry="v2/openapi.yaml"))
    assert [op.id for op in chosen.operations] == ["GET /b"]


def test_a_chosen_entry_must_exist(adapter: OpenApiAdapter) -> None:
    bundle = zip_bundle({"openapi.yaml": "openapi: 3.0.0\n"}, entry="missing.yaml")

    with pytest.raises(InputError, match="chosen entry file") as excinfo:
        adapter.extract(bundle)

    assert excinfo.value.path == "missing.yaml"
