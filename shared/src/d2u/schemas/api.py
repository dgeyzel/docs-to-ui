"""Request and response bodies of the Docs app's JSON API (SPEC §12.1).

Plain-free, so the OpenAPI description and the tests can use them directly.
The `DocPage` itself is served unchanged and lives in `d2u.schemas.docpage`.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from d2u.sources.bundle import FileManifest

GenerationStatusName = Literal["pending", "running", "succeeded", "failed"]


class GenerationInput(BaseModel):
    """What was submitted. The input itself is never returned."""

    model_config = ConfigDict(frozen=True)

    origin: Literal["paste", "file", "zip"]
    filename: str
    entry: str
    bytes: int
    sha256: str


class GenerationUsage(BaseModel):
    """Token counts, cost and model latency, zero until the generation finishes."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int


class GenerationError(BaseModel):
    """Why a generation failed. `path` and `line` are set for input errors."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    path: str | None = None
    line: int | None = None


class GenerationLinks(BaseModel):
    """Where to find the generation and its page.

    Paths are relative to the server. `trace` is absent when no trace
    backend with a viewer is selected, and may then point to Langfuse.
    """

    model_config = ConfigDict(frozen=True)

    self: str
    page: str
    html: str
    ui: str
    trace: str | None = None


class GenerationResource(BaseModel):
    """One generation as the API returns it."""

    model_config = ConfigDict(frozen=True)

    id: int
    status: GenerationStatusName
    stage: str
    language: str
    strategy: Literal["llm", "hybrid", "parser"]
    input: GenerationInput
    model: str
    prompt_label: str
    usage: GenerationUsage
    error: GenerationError | None = None
    manifest: FileManifest | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    links: GenerationLinks


class GenerationList(BaseModel):
    """Generations, newest first."""

    model_config = ConfigDict(frozen=True)

    generations: list[GenerationResource]


class TextSubmission(BaseModel):
    """A JSON submission of pasted text. Files and zips are sent as multipart."""

    model_config = ConfigDict(frozen=True)

    text: str
    language: str = Field(default="", description='An adapter name; "" detects it.')
    strategy: Literal["", "llm", "hybrid"] = Field(
        default="", description="Offered only when hybrid is enabled."
    )


class FeedbackRequest(BaseModel):
    """A 👍 (1) or 👎 (-1) on the whole page or on one operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: str | None = Field(default=None, max_length=512)
    score: Literal[1, -1]
    comment: str = Field(default="", max_length=5000)


class FeedbackCreated(BaseModel):
    """The recorded feedback."""

    model_config = ConfigDict(frozen=True)

    id: int
    generation_id: int
    operation_id: str | None
    score: int
    comment: str


class ApiErrorBody(BaseModel):
    """What went wrong. `fields` maps form fields to messages for `invalid_input`."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    fields: dict[str, list[str]] | None = None
    generation: GenerationResource | None = None


class ApiError(BaseModel):
    """The envelope of every error response."""

    model_config = ConfigDict(frozen=True)

    error: ApiErrorBody
