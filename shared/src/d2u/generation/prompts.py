"""Prompts: instructions plus few-shot examples, rendered into chat messages.

A prompt version is plain data (SPEC §8). The Tuning app produces new
versions; this module is the only place that turns one into messages.
"""

import json
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from d2u.schemas.docpage import Operation
from d2u.schemas.generated import GeneratedDocs, GeneratedPage

PromptStrategy = Literal["llm", "hybrid"]
Message = dict[str, str]
LANGUAGES = ("openapi", "python")
PROMPT_STRATEGIES: tuple[PromptStrategy, ...] = ("llm", "hybrid")

# Final user messages start with these markers; fake-model fixtures match on them.
OPERATIONS_MARKER = "Operations to document:"
OVERVIEW_MARKER = "Operations to summarize:"


class PageExample(BaseModel):
    """A few-shot example for the `llm` strategy: files in, page out."""

    model_config = ConfigDict(frozen=True)

    input_files: dict[str, str]
    output: GeneratedPage


class DocsExample(BaseModel):
    """A few-shot example for the `hybrid` strategy: operations in, docs out."""

    model_config = ConfigDict(frozen=True)

    operations: list[Operation]
    output: GeneratedDocs


class PromptSpec(BaseModel):
    """The parts of a prompt version that shape the call."""

    model_config = ConfigDict(frozen=True)

    language: str
    strategy: PromptStrategy
    version: str
    instructions: str
    page_examples: list[PageExample] = Field(default_factory=list)
    docs_examples: list[DocsExample] = Field(default_factory=list)


def baseline_instructions(language: str, strategy: PromptStrategy) -> str:
    """The shipped baseline instructions for a language and strategy."""
    return (files("d2u.prompts") / f"{language}_{strategy}.md").read_text(
        encoding="utf-8"
    )


def overview_instructions() -> str:
    """Instructions for the overview written after a split input is merged."""
    return (files("d2u.prompts") / "overview.md").read_text(encoding="utf-8")


ENTRY_MARKER = "Entry file:"


def format_files(source_files: dict[str, str], *, entry: str | None = None) -> str:
    """The bundle's files, each labeled with its path, after the entry file's name."""
    blocks = [
        f'<file path="{path}">\n{text}\n</file>'
        for path, text in sorted(source_files.items())
    ]
    heading = f"{ENTRY_MARKER} {entry}\n\n" if entry else ""
    return heading + "Source files:\n\n" + "\n\n".join(blocks)


def format_operations(
    operations: list[Operation], *, api_title: str, language: str
) -> str:
    """A batch of parsed operations for the `hybrid` strategy."""
    payload = json.dumps(
        [op.model_dump(mode="json") for op in operations], indent=2, ensure_ascii=False
    )
    return (
        f"{OPERATIONS_MARKER}\n```json\n{payload}\n```\n\n"
        f"API: {api_title}\nLanguage: {language}"
    )


def page_messages(
    prompt: PromptSpec, source_files: dict[str, str], *, entry: str | None = None
) -> list[Message]:
    """Messages for the `llm` strategy: instructions, examples, then the files."""
    messages: list[Message] = [{"role": "system", "content": prompt.instructions}]
    for example in prompt.page_examples:
        messages.append({"role": "user", "content": format_files(example.input_files)})
        messages.append(
            {"role": "assistant", "content": example.output.model_dump_json()}
        )
    messages.append(
        {"role": "user", "content": format_files(source_files, entry=entry)}
    )
    return messages


def docs_messages(
    prompt: PromptSpec, operations: list[Operation], *, api_title: str, language: str
) -> list[Message]:
    """Messages for one `hybrid` batch: instructions, examples, then the operations."""
    messages: list[Message] = [{"role": "system", "content": prompt.instructions}]
    for example in prompt.docs_examples:
        messages.append(
            {
                "role": "user",
                "content": format_operations(
                    example.operations, api_title=api_title, language=language
                ),
            }
        )
        messages.append(
            {"role": "assistant", "content": example.output.model_dump_json()}
        )
    messages.append(
        {
            "role": "user",
            "content": format_operations(
                operations, api_title=api_title, language=language
            ),
        }
    )
    return messages


def overview_messages(*, title: str, summaries: list[str]) -> list[Message]:
    """Messages for the overview call: every operation's one-line summary."""
    listing = "\n".join(f"- {summary}" for summary in summaries)
    return [
        {"role": "system", "content": overview_instructions()},
        {"role": "user", "content": f"{OVERVIEW_MARKER}\nAPI: {title}\n\n{listing}"},
    ]


CONNECTION_CHECK_MARKER = "Connection check:"


def connection_check_messages() -> list[Message]:
    """The smallest structured-output request, for a model's Test connection."""
    return [
        {
            "role": "user",
            "content": f"{CONNECTION_CHECK_MARKER} answer with ok set to true.",
        }
    ]


JUDGE_MARKER = "Documentation to judge:"


def judge_instructions() -> str:
    """Instructions for the eval judge (faithfulness claims and prose quality)."""
    return (files("d2u.prompts") / "judge.md").read_text(encoding="utf-8")


def judge_messages(source_files: dict[str, str], documentation: str) -> list[Message]:
    """Messages asking a judge to grade `documentation` against the source files."""
    return [
        {"role": "system", "content": judge_instructions()},
        {
            "role": "user",
            "content": f"{JUDGE_MARKER}\n```json\n{documentation}\n```\n\n"
            + format_files(source_files),
        },
    ]
