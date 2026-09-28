import pytest

from app.llm.schemas import Operation
from app.sources.adapters.python import PythonAdapter, module_name, package_root
from app.sources.bundle import SourceBundle, SourceFile
from app.sources.exceptions import InputError
from app.sources.registry import select_files
from tests.helpers import FIXTURES_DIR, bundle_from_dir

ACME = FIXTURES_DIR / "python" / "acme"


@pytest.fixture
def adapter() -> PythonAdapter:
    return PythonAdapter()


def extract_acme(adapter: PythonAdapter) -> dict[str, Operation]:
    bundle, _ = select_files(bundle_from_dir(ACME), adapter)
    return {op.id: op for op in adapter.extract(bundle).operations}


def bundle_of_files(files: dict[str, str]) -> SourceBundle:
    return SourceBundle(
        files=[SourceFile(path=path, text=text) for path, text in files.items()],
        origin="zip",
    )


def test_extract_documents_the_public_api_in_order(adapter: PythonAdapter) -> None:
    bundle, _ = select_files(bundle_from_dir(ACME), adapter)

    surface = adapter.extract(bundle)

    assert surface.title == "acme"
    assert surface.language == "python"
    assert [op.id for op in surface.operations] == [
        "acme.Client",
        "acme.Client.get",
        "acme.Client.stream",
        "acme.Client.version",
        "acme.AcmeError",
        "acme.connect",
        "acme.helpers.internal_helper",
        "acme.plugins.loader.load",
    ]


def test_reexports_use_the_public_path_and_the_definition_location(
    adapter: PythonAdapter,
) -> None:
    ops = extract_acme(adapter)

    client = ops["acme.Client"]
    assert client.kind == "class"
    assert client.location is not None
    assert (client.location.path, client.location.line) == ("src/acme/client.py", 1)
    assert "acme.client.Client" not in ops
    assert "acme.errors.AcmeError" not in ops
    assert ops["acme.AcmeError"].signature == "class AcmeError(Exception)"


def test_reexports_not_in_all_stay_under_their_definition_path(
    adapter: PythonAdapter,
) -> None:
    ops = extract_acme(adapter)

    assert "acme.internal_helper" not in ops
    assert "acme.helpers.internal_helper" in ops
    assert "acme.helpers.not_exported" not in ops


def test_private_names_are_skipped(adapter: PythonAdapter) -> None:
    ops = extract_acme(adapter)

    assert not any("_private" in op_id or "_hidden" in op_id for op_id in ops)


def test_class_signature_includes_constructor_params(adapter: PythonAdapter) -> None:
    client = extract_acme(adapter)["acme.Client"]

    assert client.signature == "class Client: Client(url: str, timeout: float = 5.0)"
    assert [(p.id, p.name, p.type, p.required, p.default) for p in client.params] == [
        ("acme.Client#url", "url", "str", True, None),
        ("acme.Client#timeout", "timeout", "float", False, "5.0"),
    ]
    assert client.source_description == "A connection to an Acme server."


def test_methods_drop_self_and_keep_keyword_only_params(adapter: PythonAdapter) -> None:
    get = extract_acme(adapter)["acme.Client.get"]

    assert get.kind == "method"
    assert get.signature == "get(key: str, default: bytes | None = None) -> bytes"
    assert [(p.name, p.location, p.required) for p in get.params] == [
        ("key", "arg", True),
        ("default", "kwarg", False),
    ]
    assert get.returns == "bytes"
    assert get.group_hint == "acme.Client"
    assert get.location is not None
    assert get.location.line == 7


def test_async_methods_and_variadic_params(adapter: PythonAdapter) -> None:
    stream = extract_acme(adapter)["acme.Client.stream"]

    assert stream.signature.startswith("async stream(")
    assert [(p.name, p.location, p.required) for p in stream.params] == [
        ("*keys", "arg", False),
        ("**options", "kwarg", False),
    ]


def test_static_methods_keep_their_first_param(adapter: PythonAdapter) -> None:
    source = (
        "class A:\n    @staticmethod\n    def make(size: int) -> 'A':\n        pass\n"
    )

    ops = {
        op.id: op
        for op in adapter.extract(bundle_of_files({"a.py": source})).operations
    }

    assert [p.name for p in ops["a.A.make"].params] == ["size"]


def test_functions_are_grouped_by_module(adapter: PythonAdapter) -> None:
    ops = extract_acme(adapter)

    assert adapter.group_key(ops["acme.connect"]) == "acme"
    assert adapter.group_key(ops["acme.plugins.loader.load"]) == "acme.plugins.loader"
    assert adapter.group_key(ops["acme.Client.version"]) == "acme.Client"


def test_unannotated_params_are_typed_any(adapter: PythonAdapter) -> None:
    helper = extract_acme(adapter)["acme.helpers.internal_helper"]

    assert helper.signature == "internal_helper(value)"
    assert helper.params[0].type == "Any"


def test_default_excludes_skip_tests_and_virtualenvs(adapter: PythonAdapter) -> None:
    bundle, skipped = select_files(bundle_from_dir(ACME), adapter)

    assert [file.path for file in bundle.files] == [
        "src/acme/__init__.py",
        "src/acme/client.py",
        "src/acme/errors.py",
        "src/acme/helpers.py",
        "src/acme/plugins/loader.py",
    ]
    assert [(entry.path, entry.reason) for entry in skipped] == [
        ("pyproject.toml", "not a Python file"),
        ("src/acme/tests/test_client.py", "excluded: **/tests/**"),
        ("tests/test_acme.py", "excluded: **/tests/**"),
    ]


def test_syntax_errors_report_path_and_line(adapter: PythonAdapter) -> None:
    bundle = bundle_of_files(
        {"pkg/__init__.py": "", "pkg/bad.py": "x = 1\ndef broken(:\n"}
    )

    with pytest.raises(InputError, match="Syntax error") as excinfo:
        adapter.extract(bundle)

    assert (excinfo.value.path, excinfo.value.line) == ("pkg/bad.py", 2)


def test_code_without_public_definitions_is_rejected(adapter: PythonAdapter) -> None:
    with pytest.raises(InputError, match="No public functions or classes"):
        adapter.extract(bundle_of_files({"a.py": "_x = 1\ndef _f(): pass\n"}))


@pytest.mark.parametrize(
    ("paths", "root"),
    [
        (["src/acme/__init__.py", "setup.py"], "src/"),
        (["lib/acme/__init__.py", "lib/acme/core/__init__.py"], "lib/"),
        (["acme/__init__.py", "scripts/run.py"], ""),
        (["client.py"], ""),
    ],
)
def test_package_root_detection(paths: list[str], root: str) -> None:
    assert package_root(paths) == root


@pytest.mark.parametrize(
    ("path", "root", "expected"),
    [
        ("src/acme/client.py", "src/", ("acme.client", False)),
        ("src/acme/__init__.py", "src/", ("acme", True)),
        ("src/acme/ns/mod.py", "src/", ("acme.ns.mod", False)),
        ("scripts/run.py", "lib/", ("scripts.run", False)),
    ],
)
def test_module_names_follow_the_package_root(
    path: str, root: str, expected: tuple[str, bool]
) -> None:
    assert module_name(path, root) == expected


@pytest.mark.parametrize(
    ("text", "score"),
    [
        ("def public():\n    pass\n", 0.9),
        ("x = 1\n", 0.3),
        ("this isn't python", 0.05),
    ],
)
def test_sniff_scores_python_by_what_it_defines(
    adapter: PythonAdapter, text: str, score: float
) -> None:
    assert adapter.sniff(bundle_of_files({"a.py": text})) == score


def test_sniff_ignores_non_python_files(adapter: PythonAdapter) -> None:
    assert adapter.sniff(bundle_of_files({"a.yaml": "a: 1"})) == 0.0


def test_extract_never_imports_user_code(adapter: PythonAdapter, tmp_path) -> None:
    marker = tmp_path / "imported"
    source = f"open({str(marker)!r}, 'w').write('x')\n\ndef f():\n    pass\n"

    adapter.extract(bundle_of_files({"evil.py": source}))

    assert not marker.exists()
