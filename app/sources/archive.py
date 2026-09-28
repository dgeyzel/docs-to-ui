"""Reading `.zip` archives safely, in memory only.

Nothing is ever extracted to disk. Sizes are counted while reading rather
than trusted from headers, so zip bombs are stopped by the limits. Unsafe
paths and symlinks reject the whole archive; unreadable members are skipped
and listed in the manifest with the reason.
"""

import io
import re
import stat
import zipfile
from dataclasses import dataclass

from app.sources.bundle import SkippedFile, SourceFile
from app.sources.exceptions import ArchiveLimitError, InputError

READ_CHUNK_BYTES = 64 * 1024
BINARY_SNIFF_BYTES = 8192
NESTED_ARCHIVE_SUFFIXES = (
    ".zip",
    ".tar",
    ".tgz",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".jar",
    ".whl",
    ".egg",
)
_DRIVE_LETTER = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """Limits enforced while reading an archive (from `SOURCES_ZIP_*`)."""

    max_uncompressed_bytes: int
    max_file_bytes: int
    max_entries: int


@dataclass(frozen=True, slots=True)
class ArchiveContents:
    """Text files read from an archive, and the members that were skipped."""

    files: list[SourceFile]
    skipped: list[SkippedFile]


def normalize_member_path(name: str) -> str:
    """Return a safe relative, "/"-separated path for an archive member.

    Raises:
        InputError: The path is absolute, has a drive letter or a `..` segment,
            or contains a NUL byte.
    """
    if "\x00" in name:
        raise InputError(
            path="", line=None, message="Archive entry name has a NUL byte."
        )
    unified = name.replace("\\", "/")
    if unified.startswith("/") or _DRIVE_LETTER.match(unified):
        raise InputError(
            path=unified,
            line=None,
            message="Archive entries must not use absolute paths.",
        )
    parts = [part for part in unified.split("/") if part not in ("", ".")]
    if ".." in parts:
        raise InputError(
            path=unified, line=None, message="Archive entries must not contain '..'."
        )
    return "/".join(parts)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _read_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    path: str,
    limits: ArchiveLimits,
    used: int,
) -> bytes:
    """Read one member, counting bytes as they arrive."""
    chunks: list[bytes] = []
    size = 0
    with archive.open(info) as member:
        while chunk := member.read(READ_CHUNK_BYTES):
            size += len(chunk)
            if size > limits.max_file_bytes:
                raise ArchiveLimitError(
                    path=path,
                    line=None,
                    message=f"File is larger than the {limits.max_file_bytes}-byte limit.",
                )
            if used + size > limits.max_uncompressed_bytes:
                raise ArchiveLimitError(
                    path=path,
                    line=None,
                    message=(
                        "Archive expands to more than the "
                        f"{limits.max_uncompressed_bytes}-byte limit."
                    ),
                )
            chunks.append(chunk)
    return b"".join(chunks)


def strip_common_root(paths: list[str]) -> str:
    """The single top-level folder shared by every path, or "" if none."""
    if not paths:
        return ""
    tops = {path.split("/", 1)[0] for path in paths}
    if len(tops) != 1 or any("/" not in path for path in paths):
        return ""
    return tops.pop() + "/"


def read_zip(data: bytes, *, limits: ArchiveLimits) -> ArchiveContents:
    """Read every text member of a zip archive held in memory.

    A single top-level folder shared by all members is stripped.

    Raises:
        InputError: Not a zip, or an unsafe member path or symlink.
        ArchiveLimitError: Too many entries, or too many bytes.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise InputError(
            path="", line=None, message="Not a valid zip archive."
        ) from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > limits.max_entries:
            raise ArchiveLimitError(
                path="",
                line=None,
                message=f"Archive has more than {limits.max_entries} entries.",
            )

        members: list[tuple[str, zipfile.ZipInfo]] = []
        for info in infos:
            path = normalize_member_path(info.filename)
            if _is_symlink(info):
                raise InputError(
                    path=path, line=None, message="Archives must not contain symlinks."
                )
            if info.is_dir() or not path:
                continue
            members.append((path, info))

        root = strip_common_root([path for path, _ in members])
        files: list[SourceFile] = []
        skipped: list[SkippedFile] = []
        used = 0
        for raw_path, info in members:
            path = raw_path[len(root) :]
            if path.lower().endswith(NESTED_ARCHIVE_SUFFIXES):
                skipped.append(SkippedFile(path=path, reason="nested archive"))
                continue
            if info.flag_bits & 0x1:
                skipped.append(SkippedFile(path=path, reason="encrypted"))
                continue
            try:
                content = _read_member(
                    archive, info, path=path, limits=limits, used=used
                )
            except zipfile.BadZipFile, NotImplementedError:
                # Corrupt data or an unsupported compression method.
                skipped.append(SkippedFile(path=path, reason="unreadable"))
                continue
            used += len(content)
            if b"\x00" in content[:BINARY_SNIFF_BYTES]:
                skipped.append(SkippedFile(path=path, reason="binary file"))
                continue
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                skipped.append(SkippedFile(path=path, reason="not UTF-8"))
                continue
            files.append(SourceFile(path=path, text=text))

    files.sort(key=lambda file: file.path)
    skipped.sort(key=lambda entry: entry.path)
    return ArchiveContents(files=files, skipped=skipped)
