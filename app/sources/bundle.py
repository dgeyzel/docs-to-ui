"""Source bundles: the normalized form of every input before an adapter sees it."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.sources.exceptions import InputError

BundleOrigin = Literal["paste", "file", "zip"]


class SourceFile(BaseModel):
    """One text file. `path` is relative and "/"-separated."""

    model_config = ConfigDict(frozen=True)

    path: str
    text: str


class SourceBundle(BaseModel):
    """The files an adapter works on, and where they came from.

    `entry` is the file the user chose as the entry point, when a
    multi-file input has more than one candidate.
    """

    model_config = ConfigDict(frozen=True)

    files: list[SourceFile]
    origin: BundleOrigin
    entry: str | None = None


class SkippedFile(BaseModel):
    """A file that was not included in the bundle, and why."""

    model_config = ConfigDict(frozen=True)

    path: str
    reason: str


class FileManifest(BaseModel):
    """Which files were read, stored on the generation for the user to inspect."""

    model_config = ConfigDict(frozen=True)

    included: list[str]
    skipped: list[SkippedFile] = Field(default_factory=list)


def decode_text(*, path: str, data: bytes) -> str:
    """Decode input bytes as UTF-8 (a leading BOM is dropped).

    Raises:
        InputError: The bytes are not valid UTF-8.
    """
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError(
            path=path, line=None, message="File is not valid UTF-8 text."
        ) from exc


def normalize_filename(filename: str) -> str:
    """Reduce an uploaded filename to its final path component.

    Browsers send only a base name, but the value is untrusted, so any
    directory part (either separator) is discarded.
    """
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name or "input"


def single_file_bundle(
    *, filename: str, data: bytes, origin: BundleOrigin
) -> SourceBundle:
    """Build a one-file bundle from a pasted text or uploaded file.

    Raises:
        InputError: The content is not valid UTF-8.
    """
    path = normalize_filename(filename)
    text = decode_text(path=path, data=data)
    return SourceBundle(files=[SourceFile(path=path, text=text)], origin=origin)


def manifest_for(bundle: SourceBundle) -> FileManifest:
    """Return the manifest for a bundle where every file was included."""
    return FileManifest(included=[file.path for file in bundle.files])
