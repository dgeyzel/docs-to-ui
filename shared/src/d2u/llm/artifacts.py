"""Versioned program artifacts: saved DSPy program state plus metadata.

Layout: `<root>/<program>/<version>.json`, next to `<version>.meta.json`.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import dspy
from pydantic import BaseModel, ConfigDict

from d2u.llm.exceptions import ArtifactNotFoundError, LLMConfigurationError
from d2u.llm.signatures import EnrichOperations, WriteOverview

ENRICH_PROGRAM = "enrich_operations"
OVERVIEW_PROGRAM = "write_overview"
PROGRAM_NAMES = (ENRICH_PROGRAM, OVERVIEW_PROGRAM)
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ArtifactMeta(BaseModel):
    """What produced an artifact and how well it scored."""

    model_config = ConfigDict(frozen=True)

    program: str
    version: str
    dataset_hash: str
    scores: dict[str, float]
    model: str
    thinking_level: str
    dspy_version: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Programs:
    """The modules one generation runs."""

    enrich: dspy.Module
    overview: dspy.Module


def new_program(name: str) -> dspy.Module:
    """A fresh, unoptimized module for a program name.

    Raises:
        LLMConfigurationError: Unknown program name.
    """
    if name == ENRICH_PROGRAM:
        return dspy.ChainOfThought(EnrichOperations)
    if name == OVERVIEW_PROGRAM:
        return dspy.Predict(WriteOverview)
    raise LLMConfigurationError(f"Unknown program {name!r}")


def artifact_path(*, root: Path, program: str, version: str) -> Path:
    """Path of an artifact's state file.

    Raises:
        LLMConfigurationError: The version contains unsafe characters.
    """
    if not _VERSION.match(version):
        raise LLMConfigurationError(f"Invalid program version {version!r}")
    return root / program / f"{version}.json"


def save_program(module: dspy.Module, *, root: Path, meta: ArtifactMeta) -> Path:
    """Write an artifact and its metadata; returns the state file path.

    Both files are written to `.tmp` names first and then renamed, so a
    reader never sees a half-written artifact.
    """
    path = artifact_path(root=root, program=meta.program, version=meta.version)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta_path = path.with_suffix(".meta.json")
    tmp_state = path.with_name(f"{path.name}.tmp")
    tmp_meta = meta_path.with_name(f"{meta_path.name}.tmp")
    state = json.dumps(module.dump_state(), indent=2, ensure_ascii=False)
    tmp_state.write_text(state + "\n", encoding="utf-8")
    tmp_meta.write_text(meta.model_dump_json(indent=2) + "\n", encoding="utf-8")
    tmp_state.replace(path)
    tmp_meta.replace(meta_path)
    return path


def load_program(*, root: Path, program: str, version: str) -> dspy.Module:
    """Load a saved program.

    Raises:
        ArtifactNotFoundError: No artifact exists for that program and version.
    """
    path = artifact_path(root=root, program=program, version=version)
    if not path.is_file():
        raise ArtifactNotFoundError(f"No artifact at {path}")
    module = new_program(program)
    module.load_state(json.loads(path.read_text(encoding="utf-8")))
    return module


def load_meta(*, root: Path, program: str, version: str) -> ArtifactMeta:
    """Read an artifact's metadata.

    Raises:
        ArtifactNotFoundError: The metadata file is missing.
    """
    path = artifact_path(root=root, program=program, version=version).with_suffix(
        ".meta.json"
    )
    if not path.is_file():
        raise ArtifactNotFoundError(f"No artifact metadata at {path}")
    return ArtifactMeta.model_validate_json(path.read_text(encoding="utf-8"))


def load_programs(*, root: Path, version: str) -> Programs:
    """Load every program a generation needs at one version.

    Raises:
        ArtifactNotFoundError: Any program is missing at that version.
    """
    return Programs(
        enrich=load_program(root=root, program=ENRICH_PROGRAM, version=version),
        overview=load_program(root=root, program=OVERVIEW_PROGRAM, version=version),
    )
