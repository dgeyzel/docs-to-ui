"""What an eval judge returns (SPEC §9.5). Plain-free."""

from pydantic import BaseModel, ConfigDict, Field


class ClaimVerdict(BaseModel):
    """One factual claim from the documentation, checked against the source."""

    model_config = ConfigDict(frozen=True)

    operation_id: str
    claim: str
    supported: bool
    rationale: str = ""


class JudgeVerdict(BaseModel):
    """Per-claim faithfulness verdicts and a prose-quality rating."""

    model_config = ConfigDict(frozen=True)

    claims: list[ClaimVerdict]
    prose_quality: int = Field(ge=1, le=5)
    prose_rationale: str = ""
