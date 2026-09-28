"""The stored and rendered page (`DocPage`) and the structures inside it.

Plain-free, so both apps and the generation code can use it directly.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ParamLocation = Literal["path", "query", "header", "body", "arg", "kwarg"]
OperationKind = Literal["http", "function", "class", "method"]


class SourceLocation(BaseModel):
    """Where an operation is defined, as a path inside the source bundle."""

    model_config = ConfigDict(frozen=True)

    path: str
    line: int


class Param(BaseModel):
    """One parameter of an operation, extracted deterministically."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    location: ParamLocation
    type: str
    required: bool
    default: str | None = None
    source_description: str | None = None


class Operation(BaseModel):
    """One documented unit: an HTTP endpoint, function, class or method."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: OperationKind
    signature: str
    group_hint: str
    params: list[Param]
    returns: str | None = None
    source_description: str | None = None
    location: SourceLocation | None = None


class ApiSurface(BaseModel):
    """Everything an adapter extracted from the input, with no LLM prose."""

    model_config = ConfigDict(frozen=True)

    title: str
    language: str
    operations: list[Operation]


class Example(BaseModel):
    """A code example. Displayed, never executed."""

    model_config = ConfigDict(frozen=True)

    title: str
    language: str
    code: str


class OperationDocs(BaseModel):
    """LLM-written documentation for one operation."""

    model_config = ConfigDict(frozen=True)

    operation_id: str
    summary: str = Field(max_length=200)
    description_md: str
    param_descriptions: dict[str, str]
    examples: list[Example]


class Overview(BaseModel):
    """Page overview and navigation groups (group name to operation IDs)."""

    model_config = ConfigDict(frozen=True)

    overview_md: str
    groups: dict[str, list[str]]


Strategy = Literal["llm", "hybrid", "parser"]


class DocPage(BaseModel):
    """A complete generated page.

    Operations in `surface` without a matching entry in `operations` are
    rendered as "not enriched", using their source descriptions. Pages
    stored before schema version 2 have no strategy and were built the way
    `hybrid` builds them.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: int = 2
    strategy: Strategy = "hybrid"
    surface: ApiSurface
    overview: Overview
    operations: list[OperationDocs]
