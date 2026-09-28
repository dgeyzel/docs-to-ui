"""What the LLM returns for the `llm` and `hybrid` strategies (SPEC §5).

These models are the structured-output schemas sent to the provider. The LLM
never supplies IDs; they are derived in code from these fields.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from d2u.schemas.docpage import Example, OperationDocs, ParamLocation


class GeneratedParam(BaseModel):
    """One parameter as the LLM describes it."""

    model_config = ConfigDict(frozen=True)

    name: str
    location: ParamLocation
    type: str
    required: bool
    default: str | None = None
    description: str = ""


class GeneratedOperation(BaseModel):
    """One operation: structure and prose together."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["http", "function", "class", "method"]
    method: str | None = None
    path: str | None = None
    qualified_name: str | None = None
    signature: str
    group: str
    summary: str = Field(max_length=200)
    description_md: str = ""
    params: list[GeneratedParam] = Field(default_factory=list)
    returns: str | None = None
    examples: list[Example] = Field(default_factory=list)
    source_path: str | None = None
    source_line: int | None = None


class GeneratedPage(BaseModel):
    """A whole page, or one part of it when the input is split."""

    model_config = ConfigDict(frozen=True)

    title: str
    overview_md: str
    operations: list[GeneratedOperation]


class GeneratedOverview(BaseModel):
    """The overview written after a split input's parts are merged."""

    model_config = ConfigDict(frozen=True)

    title: str
    overview_md: str


class GeneratedDocs(BaseModel):
    """The `hybrid` strategy's answer for one batch of parsed operations."""

    model_config = ConfigDict(frozen=True)

    operations: list[OperationDocs]


class ConnectionCheck(BaseModel):
    """The answer to a model registry connection test (SPEC §7)."""

    model_config = ConfigDict(frozen=True)

    ok: bool
