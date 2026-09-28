import pytest

from app.sources.bundle import SourceBundle, SourceFile
from app.sources.exceptions import InputError
from app.sources.registry import (
    ADAPTERS,
    detect,
    display_name,
    enabled_adapters,
    get_adapter,
    select_files,
)
from tests.helpers import bundle_of


def test_enabled_adapters_follows_setting_order_and_skips_unknown_names() -> None:
    adapters = enabled_adapters(["nonexistent", "openapi"])

    assert [adapter.name for adapter in adapters] == ["openapi"]


def test_detect_picks_the_adapter_that_recognizes_the_bundle() -> None:
    adapters = enabled_adapters(["openapi"])

    adapter = detect(
        bundle=bundle_of("api.yaml", "openapi: 3.1.0\n"), adapters=adapters
    )

    assert adapter.name == "openapi"


def test_detect_fails_when_no_adapter_recognizes_the_bundle() -> None:
    adapters = enabled_adapters(["openapi"])

    with pytest.raises(InputError, match="Could not detect"):
        detect(bundle=bundle_of("notes.txt", "hello"), adapters=adapters)


def test_get_adapter_rejects_disabled_languages() -> None:
    with pytest.raises(InputError, match="Unsupported language 'cobol'"):
        get_adapter(name="cobol", adapters=enabled_adapters(["openapi"]))


@pytest.mark.parametrize(
    ("name", "expected"), [("openapi", "OpenAPI"), ("unknown", "unknown")]
)
def test_display_name_maps_adapter_names(name: str, expected: str) -> None:
    assert display_name(name) == expected


def test_select_files_keeps_the_chosen_entry() -> None:

    bundle = SourceBundle(
        files=[SourceFile(path="a.yaml", text=""), SourceFile(path="b.md", text="")],
        origin="zip",
        entry="a.yaml",
    )

    selected, skipped = select_files(bundle, ADAPTERS["openapi"])

    assert selected.entry == "a.yaml"
    assert [file.path for file in selected.files] == ["a.yaml"]
    assert [entry.path for entry in skipped] == ["b.md"]


def test_select_files_leaves_single_file_bundles_alone() -> None:

    bundle = bundle_of("notes.txt", "hello")

    selected, skipped = select_files(bundle, ADAPTERS["openapi"])

    assert selected == bundle
    assert skipped == []
