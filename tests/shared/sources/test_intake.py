import pytest
from d2u.sources.adapters.base import LanguageAdapter
from d2u.sources.adapters.openapi import OpenApiAdapter
from d2u.sources.adapters.python import PythonAdapter
from d2u.sources.archive import ArchiveLimits
from d2u.sources.exceptions import InputError
from d2u.sources.intake import PreparedInput, RawInput, prepare_input

from tests.helpers import FIXTURES_DIR, read_fixture, zip_dir

ADAPTERS: list[LanguageAdapter] = [OpenApiAdapter(), PythonAdapter()]
LIMITS = ArchiveLimits(
    max_uncompressed_bytes=50_000_000, max_file_bytes=5_000_000, max_entries=5000
)


def prepare(raw: RawInput) -> PreparedInput:
    return prepare_input(raw, adapters=ADAPTERS, limits=LIMITS)


def test_pasted_text_is_detected_by_sniffing() -> None:
    prepared = prepare(
        RawInput(
            origin="paste", data=read_fixture("openapi/petstore-3.0.yaml").encode()
        )
    )

    assert prepared.adapter.name == "openapi"
    assert [file.path for file in prepared.bundle.files] == ["input.yaml"]


def test_an_unknown_requested_language_is_an_input_error() -> None:
    with pytest.raises(InputError):
        prepare(RawInput(origin="paste", data=b"x = 1\n", language="cobol"))


def test_a_requested_language_is_used_for_a_paste() -> None:
    prepared = prepare(RawInput(origin="paste", data=b"x = 1\n", language="python"))

    assert prepared.adapter.name == "python"
    assert prepared.bundle.files[0].path == "input.py"


def test_zips_are_filtered_to_the_adapters_files() -> None:
    data = zip_dir(FIXTURES_DIR / "python/acme", prefix="acme/")

    prepared = prepare(RawInput(origin="zip", data=data, filename="acme.zip"))

    paths = [file.path for file in prepared.bundle.files]
    assert prepared.adapter.name == "python"
    assert "src/acme/client.py" in paths
    assert "pyproject.toml" not in paths
    assert any(
        skipped.path == "pyproject.toml" for skipped in prepared.manifest.skipped
    )
