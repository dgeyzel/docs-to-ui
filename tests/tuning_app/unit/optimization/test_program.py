import dspy
import pytest
from d2u.generation.client import FakeResponses
from d2u.generation.prompts import PageExample, PromptSpec
from d2u.schemas.generated import GeneratedPage

from app.optimization.exceptions import ProgramExportError
from app.optimization.lm import fake_lm
from app.optimization.program import build_program, export_prompt, source_text

PAGE = GeneratedPage(title="API", overview_md="Overview.", operations=[])
FILES = {"api.yaml": "openapi: 3.0.0"}
BASE = PromptSpec(
    language="openapi",
    strategy="llm",
    version="baseline",
    instructions="Document it.",
    page_examples=[PageExample(input_files=FILES, output=PAGE)],
)


def test_a_prompt_version_becomes_a_program_with_its_demos() -> None:
    program = build_program(BASE)

    assert program.signature is not None
    assert program.signature.instructions == "Document it."
    assert program.demos[0].source == source_text(FILES, None)
    assert program.demos[0].page == PAGE


def test_the_source_is_formatted_like_the_docs_apps_final_message() -> None:
    assert source_text(FILES, "api.yaml").startswith("Entry file: api.yaml")


def test_an_optimized_program_exports_its_instructions_and_known_demos() -> None:
    program = build_program(BASE)
    assert program.signature is not None
    program.signature = program.signature.with_instructions("Better instructions.")
    program.demos = [
        dspy.Example(source=source_text(FILES, None), page=PAGE.model_dump_json()),
        dspy.Example(source="an input the run never saw", page=PAGE),
        dspy.Example(source=source_text(FILES, None), page="not a page"),
    ]

    spec = export_prompt(
        program,
        files_by_source={source_text(FILES, None): FILES},
        base=BASE,
        version="opt-1",
    )

    assert spec.version == "opt-1"
    assert spec.instructions == "Better instructions."
    assert spec.page_examples == [PageExample(input_files=FILES, output=PAGE)]


def test_programs_with_several_predictors_cannot_be_exported() -> None:
    class Two(dspy.Module):
        def __init__(self) -> None:
            super().__init__()
            self.first = build_program(BASE)
            self.second = build_program(BASE)

    with pytest.raises(ProgramExportError, match="Expected one predictor, found 2"):
        export_prompt(Two(), files_by_source={}, base=BASE, version="x")


def test_the_fake_lm_answers_pages_from_the_fixtures() -> None:
    lm = fake_lm(
        FakeResponses(
            {
                "Judge me": {"claims": [], "prose_quality": 3},
                "openapi: 3.0.0": PAGE.model_dump(),
            }
        )
    )
    with dspy.context(lm=lm):
        prediction = build_program(BASE.model_copy(update={"page_examples": []}))(
            source=source_text(FILES, None)
        )

    assert prediction.page == PAGE
