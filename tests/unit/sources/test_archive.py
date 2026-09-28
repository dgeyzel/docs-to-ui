import io
import zipfile

import pytest

from app.sources.archive import (
    ArchiveLimits,
    normalize_member_path,
    read_zip,
    strip_common_root,
)
from app.sources.exceptions import ArchiveLimitError, InputError
from tests.helpers import make_zip

LIMITS = ArchiveLimits(
    max_uncompressed_bytes=50 * 1024 * 1024,
    max_file_bytes=5 * 1024 * 1024,
    max_entries=5000,
)


def paths(contents) -> list[str]:
    return [file.path for file in contents.files]


def skipped(contents) -> list[tuple[str, str]]:
    return [(entry.path, entry.reason) for entry in contents.skipped]


def test_read_zip_returns_text_files_sorted_by_path() -> None:
    data = make_zip({"b.py": "x = 1\n", "a/c.yaml": "a: 1\n", "a/": b""})

    contents = read_zip(data, limits=LIMITS)

    assert paths(contents) == ["a/c.yaml", "b.py"]
    assert contents.files[1].text == "x = 1\n"
    assert contents.skipped == []


def test_read_zip_strips_a_single_top_level_folder() -> None:
    data = make_zip({"repo-main/src/a.py": "a", "repo-main/README.md": "r"})

    assert paths(read_zip(data, limits=LIMITS)) == ["README.md", "src/a.py"]


def test_read_zip_keeps_paths_when_there_are_several_top_levels() -> None:
    data = make_zip({"one/a.py": "a", "two/b.py": "b"})

    assert paths(read_zip(data, limits=LIMITS)) == ["one/a.py", "two/b.py"]


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("../evil.py", "must not contain '..'"),
        ("safe/../../evil.py", "must not contain '..'"),
        ("/etc/passwd", "absolute paths"),
        ("C:/Windows/evil.py", "absolute paths"),
        ("C:\\Windows\\evil.py", "absolute paths"),
        ("..\\evil.py", "must not contain '..'"),
    ],
)
def test_read_zip_rejects_unsafe_paths(name: str, message: str) -> None:
    data = make_zip({"ok.py": "x", name: "evil"})

    with pytest.raises(InputError, match=message):
        read_zip(data, limits=LIMITS)


def test_read_zip_rejects_symlinks() -> None:
    data = make_zip({"link.py": "/etc/passwd"}, symlinks=("link.py",))

    with pytest.raises(InputError, match="must not contain symlinks") as excinfo:
        read_zip(data, limits=LIMITS)

    assert excinfo.value.path == "link.py"


def test_read_zip_stops_zip_bombs_while_reading() -> None:
    zeros = b"\x00" * (6 * 1024 * 1024)
    data = make_zip({f"part{i}.txt": zeros for i in range(10)}, level=9)
    assert len(data) < 1024 * 1024
    limits = ArchiveLimits(
        max_uncompressed_bytes=20 * 1024 * 1024,
        max_file_bytes=10 * 1024 * 1024,
        max_entries=5000,
    )

    with pytest.raises(ArchiveLimitError, match="expands to more than"):
        read_zip(data, limits=limits)


def test_read_zip_enforces_the_per_file_limit() -> None:
    data = make_zip({"big.py": "x" * 2000})
    limits = ArchiveLimits(
        max_uncompressed_bytes=10_000, max_file_bytes=1000, max_entries=10
    )

    with pytest.raises(
        ArchiveLimitError, match="larger than the 1000-byte limit"
    ) as excinfo:
        read_zip(data, limits=limits)

    assert excinfo.value.path == "big.py"


def lie_about_size(data: bytes, size: int) -> bytes:
    """Rewrite the central directory's uncompressed size of the only member."""
    edited = bytearray(data)
    header = edited.rfind(b"PK\x01\x02")
    edited[header + 24 : header + 28] = size.to_bytes(4, "little")
    return bytes(edited)


def test_read_zip_does_not_trust_a_header_that_understates_the_size() -> None:
    data = lie_about_size(make_zip({"big.py": "x" * 2000}), 10)
    limits = ArchiveLimits(
        max_uncompressed_bytes=10_000, max_file_bytes=1000, max_entries=10
    )

    contents = read_zip(data, limits=limits)

    assert contents.files == []
    assert skipped(contents) == [("big.py", "unreadable")]


def test_read_zip_does_not_trust_a_header_that_overstates_the_size() -> None:
    data = lie_about_size(make_zip({"small.py": "x = 1"}), 10_000_000)
    limits = ArchiveLimits(
        max_uncompressed_bytes=10_000, max_file_bytes=1000, max_entries=10
    )

    contents = read_zip(data, limits=limits)

    # Limits apply to the bytes actually read, not the 10 MB the header claims.
    assert [(file.path, file.text) for file in contents.files] == [
        ("small.py", "x = 1")
    ]


def test_read_zip_enforces_the_entry_limit() -> None:
    data = make_zip({f"f{i}.py": "" for i in range(11)})
    limits = ArchiveLimits(
        max_uncompressed_bytes=10_000, max_file_bytes=1000, max_entries=10
    )

    with pytest.raises(ArchiveLimitError, match="more than 10 entries"):
        read_zip(data, limits=limits)


def test_read_zip_skips_unreadable_members_with_reasons() -> None:
    data = make_zip(
        {
            "ok.py": "x = 1",
            "latin1.py": "caf\xe9".encode("latin-1"),
            "image.png": b"\x89PNG\r\n\x1a\n\x00\x00",
            "vendor/nested.zip": make_zip({"a.py": "a"}),
            "dist/pkg.whl": b"PK",
        }
    )

    contents = read_zip(data, limits=LIMITS)

    assert paths(contents) == ["ok.py"]
    assert skipped(contents) == [
        ("dist/pkg.whl", "nested archive"),
        ("image.png", "binary file"),
        ("latin1.py", "not UTF-8"),
        ("vendor/nested.zip", "nested archive"),
    ]


def test_read_zip_skips_encrypted_members() -> None:
    data = bytearray(make_zip({"secret.py": "x"}))
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        position = data.find(signature)
        data[position + flag_offset] |= 0x1

    contents = read_zip(bytes(data), limits=LIMITS)

    assert skipped(contents) == [("secret.py", "encrypted")]


def test_read_zip_rejects_data_that_is_not_a_zip() -> None:
    with pytest.raises(InputError, match="Not a valid zip archive"):
        read_zip(b"not a zip", limits=LIMITS)


def test_read_zip_never_writes_to_disk(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    def no_extract(*args: object, **kwargs: object) -> None:
        raise AssertionError("archives must not be extracted")

    monkeypatch.setattr(zipfile.ZipFile, "extract", no_extract)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", no_extract)

    read_zip(make_zip({"a/b.py": "x"}), limits=LIMITS)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("name", "expected"),
    [("a/./b//c.py", "a/b/c.py"), ("a\\b.py", "a/b.py"), ("plain.py", "plain.py")],
)
def test_normalize_member_path(name: str, expected: str) -> None:
    assert normalize_member_path(name) == expected


@pytest.mark.parametrize(
    ("paths_in", "root"),
    [
        (["repo/a.py", "repo/b/c.py"], "repo/"),
        (["repo/a.py", "other/b.py"], ""),
        (["a.py"], ""),
        ([], ""),
    ],
)
def test_strip_common_root(paths_in: list[str], root: str) -> None:
    assert strip_common_root(paths_in) == root


def test_make_zip_helper_writes_symlink_mode() -> None:
    data = make_zip({"link": "target"}, symlinks=("link",))

    info = zipfile.ZipFile(io.BytesIO(data)).getinfo("link")
    assert (info.external_attr >> 16) & 0o170000 == 0o120000
