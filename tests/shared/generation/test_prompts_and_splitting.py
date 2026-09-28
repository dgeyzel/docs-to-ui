import pytest
from d2u.generation.prompts import (
    LANGUAGES,
    OPERATIONS_MARKER,
    OVERVIEW_MARKER,
    PROMPT_STRATEGIES,
    DocsExample,
    PageExample,
    PromptSpec,
    baseline_instructions,
    docs_messages,
    format_files,
    overview_messages,
    page_messages,
)
from d2u.generation.splitting import estimate_tokens, source_budget, split_files
from d2u.schemas.docpage import Operation
from d2u.schemas.generated import GeneratedDocs, GeneratedPage

PAGE = GeneratedPage(title="T", overview_md="O", operations=[])
OP = Operation(id="GET /a", kind="http", signature="GET /a", group_hint="a", params=[])


@pytest.mark.parametrize("strategy", PROMPT_STRATEGIES)
@pytest.mark.parametrize("language", LANGUAGES)
def test_every_language_and_strategy_has_baseline_instructions(
    language: str, strategy: str
) -> None:
    text = baseline_instructions(language, strategy)  # ty: ignore[invalid-argument-type]

    assert "never" in text.lower()
    assert "HTML" in text


def test_page_messages_put_instructions_examples_then_files() -> None:
    prompt = PromptSpec(
        language="openapi",
        strategy="llm",
        version="v1",
        instructions="Write docs.",
        page_examples=[
            PageExample(input_files={"ex.yaml": "openapi: 3.1.0"}, output=PAGE)
        ],
    )

    messages = page_messages(prompt, {"b.yaml": "B", "a.yaml": "A"}, entry="a.yaml")

    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[0]["content"] == "Write docs."
    assert '<file path="ex.yaml">' in messages[1]["content"]
    assert messages[2]["content"] == PAGE.model_dump_json()
    final = messages[3]["content"]
    assert final.startswith("Entry file: a.yaml")
    assert final.index('<file path="a.yaml">') < final.index('<file path="b.yaml">')


def test_files_without_an_entry_have_no_entry_line() -> None:
    assert format_files({"a.py": "x = 1"}).startswith("Source files:")


def test_docs_messages_send_the_parsed_operations() -> None:
    prompt = PromptSpec(
        language="openapi",
        strategy="hybrid",
        version="v1",
        instructions="Describe.",
        docs_examples=[
            DocsExample(operations=[OP], output=GeneratedDocs(operations=[]))
        ],
    )

    messages = docs_messages(prompt, [OP], api_title="API", language="openapi")

    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[-1]["content"].startswith(OPERATIONS_MARKER)
    assert '"id": "GET /a"' in messages[-1]["content"]


def test_overview_messages_list_every_summary() -> None:
    messages = overview_messages(
        title="API", summaries=["GET /a: Get a", "GET /b: Get b"]
    )

    assert (
        messages[-1]["content"]
        == f"{OVERVIEW_MARKER}\nAPI: API\n\n- GET /a: Get a\n- GET /b: Get b"
    )


def test_small_inputs_are_one_part() -> None:
    files = {"a/x.py": "x" * 40, "b/y.py": "y" * 40}

    assert split_files(files, budget=100) == [files]


def test_large_inputs_split_and_keep_directories_together() -> None:
    files = {
        "a/one.py": "1" * 200,
        "a/two.py": "2" * 200,
        "b/three.py": "3" * 200,
        "c/four.py": "4" * 200,
    }

    parts = split_files(files, budget=100)

    assert [sorted(part) for part in parts] == [
        ["a/one.py", "a/two.py"],
        ["b/three.py", "c/four.py"],
    ]


def test_a_file_larger_than_the_budget_gets_its_own_part() -> None:
    files = {"big.py": "x" * 4000, "small.py": "y" * 40}

    parts = split_files(files, budget=100)

    assert [list(part) for part in parts] == [["big.py"], ["small.py"]]


def test_every_file_lands_in_exactly_one_part() -> None:
    files = {f"d{i % 5}/f{i}.py": "z" * (i * 13 % 300) for i in range(40)}

    parts = split_files(files, budget=200)

    paths = [path for part in parts for path in part]
    assert sorted(paths) == sorted(files)


def test_the_source_budget_leaves_room_for_instructions() -> None:
    assert source_budget(max_input_tokens=1000, instructions="x" * 400) == 700
    assert estimate_tokens("") == 1
