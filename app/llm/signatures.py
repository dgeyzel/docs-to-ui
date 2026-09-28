"""DSPy signatures for every LLM program. Defined once, here.

The docstrings are the task instructions the model sees.
"""

import dspy

from app.llm.schemas import ApiSurface, BatchEnrichment, Operation, Overview


class EnrichOperations(dspy.Signature):
    """Write reference documentation for a batch of API operations.

    For every operation, write a one-line summary (at most 200 characters), a
    Markdown description, a short description for each parameter keyed by the
    parameter's `id`, and code examples. For HTTP APIs give a `curl` example and
    a `json` response example; for Python code give `python` examples.

    Use only the operations and parameters provided: never invent endpoints,
    parameters, fields or behaviour. `source_description` was written by the
    API's authors, so expand on it but never contradict it. Write Markdown and
    code only, never HTML.
    """

    operations: list[Operation] = dspy.InputField()
    api_title: str = dspy.InputField()
    language: str = dspy.InputField(desc="Source language, e.g. openapi or python")
    result: BatchEnrichment = dspy.OutputField(
        desc="One entry per input operation, with `operation_id` equal to its `id`"
    )


class WriteOverview(dspy.Signature):
    """Write the overview for an API documentation page and organize navigation.

    Write one to three short Markdown paragraphs that explain what the API is
    for and how its parts fit together. Then group the operations for the
    sidebar: every operation id must appear in exactly one group, and group
    names should be short and human-readable. Write Markdown only, never HTML.
    """

    surface_outline: str = dspy.InputField(
        desc="The API title followed by one line per operation: id, group hint"
    )
    batch_summaries: list[str] = dspy.InputField(
        desc="One-line summaries of the operations, written earlier"
    )
    result: Overview = dspy.OutputField(
        desc="`groups` maps group name to operation ids, in reading order"
    )


class ExtractApiSurface(dspy.Signature):
    """Extract the public API surface from source code in a language without a parser.

    List every public operation with its parameters, types and existing
    documentation. Never invent operations. Unused in v1: every shipped
    language has a deterministic parser.
    """

    source: str = dspy.InputField()
    language: str = dspy.InputField()
    surface: ApiSurface = dspy.OutputField()


class JudgeEnrichment(dspy.Signature):
    """Grade documentation written for a batch of API operations.

    `consistency` is 1.0 when nothing in the documentation contradicts any
    operation's `source_description`, and lower for each contradiction.
    `prose_quality` rates clarity, accuracy of tone and usefulness from 1
    (unusable) to 5 (excellent reference documentation). Judge only what is
    written; do not reward length.
    """

    operations: list[Operation] = dspy.InputField()
    documentation: BatchEnrichment = dspy.InputField()
    consistency: float = dspy.OutputField(desc="0.0 to 1.0")
    prose_quality: int = dspy.OutputField(desc="1 to 5")
