"""Asking a judge model to grade a generated page (SPEC §9.5). Plain-free.

Judges go through the same LiteLLM client as generation, so they use the
registry's model settings, structured output and the validation retry.
"""

import json

from d2u.generation.client import (
    CallResult,
    FakeResponses,
    ModelSpec,
    complete_structured,
)
from d2u.generation.prompts import judge_messages
from d2u.schemas.docpage import DocPage
from d2u.schemas.judging import JudgeVerdict


def documentation_for_judge(page: DocPage) -> str:
    """The page's prose, per operation, as the JSON a judge reads."""
    docs = {entry.operation_id: entry for entry in page.operations}
    operations = []
    for op in page.surface.operations:
        entry = docs.get(op.id)
        operations.append(
            {
                "id": op.id,
                "signature": op.signature,
                "summary": entry.summary if entry else (op.source_description or ""),
                "description": entry.description_md if entry else "",
                "parameters": {
                    param.name: (
                        entry.param_descriptions.get(param.id, "") if entry else ""
                    )
                    or (param.source_description or "")
                    for param in op.params
                },
                "returns": op.returns,
            }
        )
    payload = {
        "title": page.surface.title,
        "overview": page.overview.overview_md,
        "operations": operations,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def judge_page(
    *,
    model: ModelSpec,
    source_files: dict[str, str],
    page: DocPage,
    fake: FakeResponses | None = None,
) -> CallResult[JudgeVerdict]:
    """Grade a page's faithfulness to the source and its prose quality.

    Raises:
        LLMConfigurationError, ProviderError, OutputValidationError: The call failed.
    """
    return complete_structured(
        model=model,
        messages=judge_messages(source_files, documentation_for_judge(page)),
        response_model=JudgeVerdict,
        fake=fake,
    )
