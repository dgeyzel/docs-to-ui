"""A prompt version as a DSPy program, and back (SPEC §9.4). Plain-free.

The program is one `dspy.Predict` whose signature mirrors the Docs app's
call: the bundle's files (formatted exactly as `d2u.generation` formats
them) in, a `GeneratedPage` out. Its instructions and demos are the prompt
version's instructions and few-shot examples. DSPy only searches for better
instructions and demos; scores always come from the production path (D13).
"""

import json

import dspy
from d2u.generation.prompts import PageExample, PromptSpec, format_files
from d2u.schemas.generated import GeneratedPage
from pydantic import ValidationError

from app.optimization.exceptions import ProgramExportError


class GeneratePage(dspy.Signature):
    """Document the API in the source files."""

    source: str = dspy.InputField(desc="The source files, each labeled with its path.")
    page: GeneratedPage = dspy.OutputField()


def source_text(files: dict[str, str], entry: str | None) -> str:
    """The input as the Docs app's final user message presents it."""
    return format_files(files, entry=entry)


def build_program(prompt: PromptSpec) -> dspy.Predict:
    """A program with the prompt's instructions and few-shot examples as demos."""
    program = dspy.Predict(GeneratePage.with_instructions(prompt.instructions))
    program.demos = [
        dspy.Example(source=source_text(example.input_files, None), page=example.output)
        for example in prompt.page_examples
    ]
    return program


def _page(value: object) -> GeneratedPage:
    if isinstance(value, GeneratedPage):
        return value
    if isinstance(value, str):
        return GeneratedPage.model_validate_json(value)
    return GeneratedPage.model_validate(value)


def export_prompt(
    program: dspy.Module,
    *,
    files_by_source: dict[str, dict[str, str]],
    base: PromptSpec,
    version: str,
) -> PromptSpec:
    """The optimized program's instructions and demos as a prompt version.

    `files_by_source` maps every training input's formatted source back to
    its files, so demos become `PageExample`s the Docs app can render.
    Demos whose source or page can't be recovered are dropped.

    Raises:
        ProgramExportError: The program has no single predictor to export.
    """
    predictors = program.predictors()
    if len(predictors) != 1:
        raise ProgramExportError(f"Expected one predictor, found {len(predictors)}.")
    predictor = predictors[0]
    examples: list[PageExample] = []
    seen: set[str] = set()
    for demo in predictor.demos:
        source = demo.get("source") if hasattr(demo, "get") else None
        files = files_by_source.get(source or "")
        if files is None:
            continue
        try:
            page = _page(demo.get("page"))
        except ValidationError, json.JSONDecodeError, ValueError:
            continue
        key = json.dumps(files, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        examples.append(PageExample(input_files=files, output=page))
    return PromptSpec(
        language=base.language,
        strategy="llm",
        version=version,
        instructions=predictor.signature.instructions,
        page_examples=examples,
    )
