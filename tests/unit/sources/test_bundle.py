import pytest

from app.sources.bundle import (
    FileManifest,
    decode_text,
    manifest_for,
    normalize_filename,
    single_file_bundle,
)
from app.sources.exceptions import InputError


def test_decode_text_rejects_non_utf8_bytes() -> None:
    with pytest.raises(InputError, match="not valid UTF-8") as excinfo:
        decode_text(path="api.yaml", data=b"openapi: \xff\xfe")

    assert excinfo.value.path == "api.yaml"
    assert excinfo.value.line is None


def test_decode_text_drops_a_leading_bom() -> None:
    assert decode_text(path="api.yaml", data=b"\xef\xbb\xbfopenapi: 3.1.0") == (
        "openapi: 3.1.0"
    )


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("api.yaml", "api.yaml"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\api.json", "api.json"),
        ("  spaced.yaml  ", "spaced.yaml"),
        ("dir/", "input"),
        ("", "input"),
    ],
)
def test_normalize_filename_keeps_only_the_base_name(
    filename: str, expected: str
) -> None:
    assert normalize_filename(filename) == expected


def test_single_file_bundle_records_origin_and_normalized_path() -> None:
    bundle = single_file_bundle(filename="specs/api.yaml", data=b"a: 1", origin="file")

    assert bundle.origin == "file"
    assert [(f.path, f.text) for f in bundle.files] == [("api.yaml", "a: 1")]


def test_manifest_for_lists_every_file_as_included() -> None:
    bundle = single_file_bundle(filename="api.yaml", data=b"a: 1", origin="file")

    assert manifest_for(bundle) == FileManifest(included=["api.yaml"], skipped=[])


def test_input_error_message_includes_location() -> None:
    error = InputError(path="api.yaml", line=4, message="Bad thing.")

    assert str(error) == "api.yaml:4: Bad thing."
