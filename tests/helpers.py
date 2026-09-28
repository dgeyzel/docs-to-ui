import io
import stat
import zipfile
from pathlib import Path

from d2u.sources.bundle import SourceBundle, SourceFile

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def read_fixture(relative_path: str) -> str:
    return (FIXTURES_DIR / relative_path).read_text(encoding="utf-8")


def bundle_of(path: str, text: str) -> SourceBundle:
    return SourceBundle(files=[SourceFile(path=path, text=text)], origin="file")


def make_zip(
    entries: dict[str, bytes | str], *, symlinks: tuple[str, ...] = (), level: int = 6
) -> bytes:
    """Build a zip in memory. Names are written exactly as given."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=level
    ) as archive:
        for name, content in entries.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if name in symlinks:
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def bundle_from_dir(directory: Path, *, origin: str = "zip") -> SourceBundle:
    """A bundle of every file under a fixtures directory, with relative paths."""
    files = [
        SourceFile(
            path=path.relative_to(directory).as_posix(),
            text=path.read_text(encoding="utf-8"),
        )
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    ]
    return SourceBundle(files=files, origin=origin)  # ty: ignore[invalid-argument-type]


def zip_dir(directory: Path, *, prefix: str = "") -> bytes:
    """Zip a fixtures directory, optionally under a top-level folder."""
    return make_zip(
        {
            f"{prefix}{path.relative_to(directory).as_posix()}": path.read_bytes()
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        }
    )
