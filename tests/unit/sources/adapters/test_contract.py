"""The contract every language adapter must meet (SPEC §7).

Each registered adapter needs `tests/fixtures/<name>/contract.json` naming a
fixture bundle and the expected IDs, groups, file filtering and error
location. Adding an adapter without one fails this suite.
"""

import json
from typing import Any

import pytest

from app.sources.adapters.base import LanguageAdapter
from app.sources.bundle import SourceBundle, SourceFile
from app.sources.exceptions import InputError
from app.sources.registry import ADAPTERS, excluded_by, select_files
from tests.helpers import FIXTURES_DIR, bundle_from_dir

ADAPTER_NAMES = sorted(ADAPTERS)


def load_contract(name: str) -> dict[str, Any]:
    path = FIXTURES_DIR / name / "contract.json"
    assert path.is_file(), f"adapter {name!r} has no contract fixture at {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def contract_bundle(name: str, adapter: LanguageAdapter) -> SourceBundle:
    contract = load_contract(name)
    bundle, _ = select_files(
        bundle_from_dir(FIXTURES_DIR / name / contract["bundle"]), adapter
    )
    return bundle


@pytest.fixture(params=ADAPTER_NAMES)
def name(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def adapter(name: str) -> LanguageAdapter:
    return ADAPTERS[name]


def test_adapter_declares_its_metadata(name: str, adapter: LanguageAdapter) -> None:
    assert adapter.name == name
    assert adapter.display_name
    assert adapter.file_extensions
    assert all(extension.startswith(".") for extension in adapter.file_extensions)
    assert adapter.example_languages


def test_extracts_the_expected_ids(name: str, adapter: LanguageAdapter) -> None:
    surface = adapter.extract(contract_bundle(name, adapter))

    assert [op.id for op in surface.operations] == load_contract(name)["expected_ids"]
    assert surface.language == name


def test_ids_are_stable_and_independent_of_file_order(
    name: str, adapter: LanguageAdapter
) -> None:
    bundle = contract_bundle(name, adapter)
    reversed_bundle = SourceBundle(
        files=list(reversed(bundle.files)), origin=bundle.origin, entry=bundle.entry
    )

    first = adapter.extract(bundle)
    again = adapter.extract(bundle)
    shuffled = adapter.extract(reversed_bundle)

    assert first == again
    assert sorted(op.id for op in shuffled.operations) == sorted(
        op.id for op in first.operations
    )


def test_ids_are_unique_and_params_are_scoped_to_their_operation(
    name: str, adapter: LanguageAdapter
) -> None:
    surface = adapter.extract(contract_bundle(name, adapter))

    op_ids = [op.id for op in surface.operations]
    assert len(op_ids) == len(set(op_ids))
    for op in surface.operations:
        param_ids = [param.id for param in op.params]
        assert len(param_ids) == len(set(param_ids))
        assert all(param_id.startswith(f"{op.id}#") for param_id in param_ids)


def test_every_operation_has_a_source_location_in_the_bundle(
    name: str, adapter: LanguageAdapter
) -> None:
    bundle = contract_bundle(name, adapter)
    paths = {file.path for file in bundle.files}

    for op in adapter.extract(bundle).operations:
        assert op.location is not None
        assert op.location.path in paths
        assert op.location.line >= 1


def test_groups_operations_as_expected(name: str, adapter: LanguageAdapter) -> None:
    ops = {
        op.id: op for op in adapter.extract(contract_bundle(name, adapter)).operations
    }

    for op_id, group in load_contract(name)["expected_groups"].items():
        assert adapter.group_key(ops[op_id]) == group


def test_filters_files(name: str, adapter: LanguageAdapter) -> None:
    for path, included in load_contract(name)["includes"].items():
        assert adapter.includes(path) is included, path


def test_selected_files_are_never_excluded(name: str, adapter: LanguageAdapter) -> None:
    for file in contract_bundle(name, adapter).files:
        assert adapter.includes(file.path)
        assert excluded_by(adapter, file.path) is None


def test_recognizes_its_own_bundle(name: str, adapter: LanguageAdapter) -> None:
    assert adapter.sniff(contract_bundle(name, adapter)) > 0.5


def test_reports_errors_with_path_and_line(name: str, adapter: LanguageAdapter) -> None:
    error = load_contract(name)["error"]
    bundle = SourceBundle(
        files=[
            SourceFile(path=path, text=text) for path, text in error["files"].items()
        ],
        origin="zip",
    )

    with pytest.raises(InputError) as excinfo:
        adapter.extract(bundle)

    assert (excinfo.value.path, excinfo.value.line) == (error["path"], error["line"])
