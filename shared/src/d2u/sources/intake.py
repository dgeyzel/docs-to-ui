"""Turning raw input (a paste, a file or a zip) into a bundle and its adapter.

Plain-free: both apps receive input the same way, and the Tuning app's gold
examples store exactly what the Docs app would have read.
"""

from dataclasses import dataclass
from typing import Literal

from d2u.sources.adapters.base import LanguageAdapter
from d2u.sources.archive import ArchiveLimits, read_zip
from d2u.sources.bundle import (
    FileManifest,
    SourceBundle,
    manifest_for,
    single_file_bundle,
)
from d2u.sources.exceptions import InputError
from d2u.sources.registry import detect, get_adapter, select_files

InputKind = Literal["paste", "file", "zip"]


@dataclass(frozen=True, slots=True)
class RawInput:
    """Input as submitted: its bytes, how it arrived, and the user's choices.

    `language` is "" for auto-detection; `entry` is "" to detect it.
    """

    origin: InputKind
    data: bytes
    filename: str = ""
    language: str = ""
    entry: str = ""


@dataclass(frozen=True, slots=True)
class PreparedInput:
    """The bundle an adapter will read, the adapter, and what was read."""

    bundle: SourceBundle
    adapter: LanguageAdapter
    manifest: FileManifest


def prepare_input(
    raw: RawInput, *, adapters: list[LanguageAdapter], limits: ArchiveLimits
) -> PreparedInput:
    """Turn raw input into a bundle and choose its adapter.

    A paste has no filename, so with auto-detection each adapter is offered
    the text under its own default file extension and the best sniff wins.
    A zip is read in memory under `limits`, then filtered to the files the
    chosen adapter reads.

    Raises:
        InputError: The input is unreadable, too large, or its language is unknown.
    """
    requested = (
        get_adapter(name=raw.language, adapters=adapters) if raw.language else None
    )

    if raw.origin == "paste":
        candidates = [requested] if requested else adapters
        best: tuple[float, SourceBundle, LanguageAdapter] | None = None
        for adapter in candidates:
            bundle = single_file_bundle(
                filename=f"input{adapter.file_extensions[0]}",
                data=raw.data,
                origin="paste",
            )
            score = adapter.sniff(bundle)
            if best is None or score > best[0]:
                best = (score, bundle, adapter)
        if best is None or (requested is None and best[0] == 0.0):
            raise InputError(
                path="",
                line=None,
                message="Could not detect the input language; choose one explicitly.",
            )
        return PreparedInput(
            bundle=best[1], adapter=best[2], manifest=manifest_for(best[1])
        )

    if raw.origin == "zip":
        contents = read_zip(raw.data, limits=limits)
        everything = SourceBundle(
            files=contents.files, origin="zip", entry=raw.entry or None
        )
        adapter = requested or detect(bundle=everything, adapters=adapters)
        bundle, filtered_out = select_files(everything, adapter)
        skipped = sorted(
            [*contents.skipped, *filtered_out], key=lambda entry: entry.path
        )
        manifest = FileManifest(
            included=[file.path for file in bundle.files], skipped=skipped
        )
        return PreparedInput(bundle=bundle, adapter=adapter, manifest=manifest)

    bundle = single_file_bundle(filename=raw.filename, data=raw.data, origin="file")
    adapter = requested or detect(bundle=bundle, adapters=adapters)
    return PreparedInput(bundle=bundle, adapter=adapter, manifest=manifest_for(bundle))
