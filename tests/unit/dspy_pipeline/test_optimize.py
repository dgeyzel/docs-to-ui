import json
from pathlib import Path

import pytest

from app.llm.artifacts import ENRICH_PROGRAM, OVERVIEW_PROGRAM, load_meta, load_program
from dspy_pipeline.optimize import (
    DEFAULT_ARTIFACTS_ROOT,
    Split,
    batch_examples,
    dataset_hash,
    entry_surface,
    load_entries,
    main,
)
from tests.helpers import FIXTURES_DIR

FAKE = str(FIXTURES_DIR / "llm" / "pipeline.json")
FAKE_ARGS = ["--model", "fake", "--judge-model", "fake", "--fake-responses", FAKE]


def printed_report(output: str) -> dict:
    """The JSON report, skipping any progress lines DSPy printed before it."""
    return json.loads(output[output.index("{\n") :])


@pytest.mark.parametrize("split", ["train", "dev"])
@pytest.mark.parametrize("language", ["openapi", "python"])
def test_every_dataset_entry_extracts_like_the_app(language: str, split: Split) -> None:
    entries = load_entries(languages=[language], split=split)

    assert entries
    for entry in entries:
        surface, adapter = entry_surface(entry)
        assert surface.language == language
        assert adapter.name == language
        assert surface.operations


def test_datasets_include_multi_file_zip_entries() -> None:
    entries = load_entries(languages=["openapi", "python"], split="train")

    zips = [entry for entry in entries if entry.origin == "zip"]
    assert {entry.language for entry in zips} == {"openapi", "python"}
    assert all(len(entry.files) > 1 for entry in zips)


def test_dataset_ids_are_unique_across_splits() -> None:
    entries = load_entries(
        languages=["openapi", "python"], split="train"
    ) + load_entries(languages=["openapi", "python"], split="dev")

    ids = [entry.id for entry in entries]
    assert len(ids) == len(set(ids))


def test_dataset_hash_is_stable_and_content_sensitive() -> None:
    entries = load_entries(languages=["openapi"], split="dev")

    assert dataset_hash(entries) == dataset_hash(list(entries))
    assert dataset_hash(entries) != dataset_hash(entries[:-1])


def test_batch_examples_follow_the_app_batching() -> None:
    entries = load_entries(languages=["openapi"], split="train")

    examples = batch_examples(entries, token_budget=60000, max_operations=2)

    assert all(len(example.operations) <= 2 for example in examples)
    assert set(examples[0].inputs().keys()) == {"operations", "api_title", "language"}
    assert sum(len(example.operations) for example in examples) == sum(
        len(entry_surface(entry)[0].operations) for entry in entries
    )


def test_evaluate_reports_every_component(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["evaluate", *FAKE_ARGS, "--language", "openapi"])

    report = printed_report(capsys.readouterr().out)
    assert exit_code == 0
    assert report["version"] == "baseline"
    assert report["examples"] == 3
    assert set(report["mean"]) == {
        "coverage",
        "fidelity",
        "consistency",
        "examples",
        "prose",
        "total",
    }
    assert report["mean"]["consistency"] == pytest.approx(0.9)
    assert report["mean"]["prose"] == pytest.approx(0.75)


def test_optimize_saves_a_loadable_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "programs"
    for program in (ENRICH_PROGRAM, OVERVIEW_PROGRAM):
        target = root / program
        target.mkdir(parents=True)
        for suffix in (".json", ".meta.json"):
            source = DEFAULT_ARTIFACTS_ROOT / program / f"baseline{suffix}"
            (target / f"baseline{suffix}").write_text(source.read_text())

    exit_code = main(
        [
            "optimize",
            *FAKE_ARGS,
            "--language",
            "openapi",
            "--version",
            "v-test",
            "--max-demos",
            "1",
            "--artifacts-root",
            str(root),
        ]
    )

    report = printed_report(capsys.readouterr().out)
    assert exit_code == 0
    assert report["version"] == "v-test"
    load_program(root=root, program=ENRICH_PROGRAM, version="v-test")
    load_program(root=root, program=OVERVIEW_PROGRAM, version="v-test")
    meta = load_meta(root=root, program=ENRICH_PROGRAM, version="v-test")
    assert meta.model == "fake"
    assert meta.scores == {"dev_total": report["mean"]["total"]}
    assert len(meta.dataset_hash) == 64
    assert not list(root.rglob("*.tmp"))
