import json
from datetime import UTC, datetime
from pathlib import Path

import dspy
import pytest
from dspy.utils.dummies import DummyLM

from app.llm.artifacts import (
    ENRICH_PROGRAM,
    PROGRAM_NAMES,
    ArtifactMeta,
    artifact_path,
    load_meta,
    load_program,
    load_programs,
    new_program,
    save_program,
)
from app.llm.exceptions import ArtifactNotFoundError, LLMConfigurationError
from app.llm.lm import FAKE_MODEL, build_lm
from app.llm.schemas import BatchEnrichment, Operation
from tests.helpers import FIXTURES_DIR

REPO_ARTIFACTS = Path(__file__).resolve().parents[3] / "artifacts" / "programs"


def make_meta(program: str, version: str = "v1") -> ArtifactMeta:
    return ArtifactMeta(
        program=program,
        version=version,
        dataset_hash="abc",
        scores={"dev": 0.5},
        model="gemini/gemini-3.8-flash",
        thinking_level="medium",
        dspy_version=dspy.__version__,
        created_at=datetime(2026, 9, 27, tzinfo=UTC),
    )


def test_build_lm_sends_no_sampling_parameters() -> None:
    lm = build_lm(model="gemini/gemini-3.8-flash", thinking_level="high")

    assert isinstance(lm, dspy.LM)
    for name in ("temperature", "top_p", "top_k"):
        assert lm.kwargs.get(name) is None
    assert lm.kwargs["reasoning_effort"] == "high"


def test_build_lm_rejects_unknown_thinking_levels() -> None:
    with pytest.raises(LLMConfigurationError, match="Thinking level"):
        build_lm(model="gemini/gemini-3.8-flash", thinking_level="extreme")


def test_fake_model_uses_dummy_lm_with_fixture_responses() -> None:
    lm = build_lm(
        model=FAKE_MODEL,
        thinking_level="medium",
        fake_responses_path=FIXTURES_DIR / "llm" / "petstore.json",
    )

    assert isinstance(lm, DummyLM)


def test_fake_model_requires_fixture_responses(tmp_path: Path) -> None:
    with pytest.raises(LLMConfigurationError, match="LLM_FAKE_RESPONSES"):
        build_lm(model=FAKE_MODEL, thinking_level="medium")

    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(LLMConfigurationError, match="JSON object"):
        build_lm(model=FAKE_MODEL, thinking_level="medium", fake_responses_path=bad)


def test_artifact_save_load_run_round_trip(tmp_path: Path) -> None:
    program = new_program(ENRICH_PROGRAM)
    path = save_program(program, root=tmp_path, meta=make_meta(ENRICH_PROGRAM))

    loaded = load_program(root=tmp_path, program=ENRICH_PROGRAM, version="v1")
    answer = {
        "reasoning": "r",
        "result": {
            "operations": [
                {
                    "operation_id": "GET /a",
                    "summary": "Get a",
                    "description_md": "Gets a.",
                    "param_descriptions": {},
                    "examples": [],
                }
            ]
        },
    }
    with dspy.context(lm=DummyLM([answer])):
        prediction = loaded(
            operations=[
                Operation(
                    id="GET /a",
                    kind="http",
                    signature="GET /a",
                    group_hint="a",
                    params=[],
                )
            ],
            api_title="API",
            language="openapi",
        )

    assert path == tmp_path / ENRICH_PROGRAM / "v1.json"
    assert isinstance(prediction.result, BatchEnrichment)
    assert prediction.result.operations[0].summary == "Get a"
    assert load_meta(root=tmp_path, program=ENRICH_PROGRAM, version="v1").scores == {
        "dev": 0.5
    }
    assert not list(tmp_path.rglob("*.tmp"))


def test_loading_a_missing_artifact_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(ArtifactNotFoundError):
        load_programs(root=tmp_path, version="v1")


@pytest.mark.parametrize("version", ["../escape", "a/b", "", ".hidden"])
def test_artifact_versions_cannot_escape_the_artifact_root(version: str) -> None:
    with pytest.raises(LLMConfigurationError, match="Invalid program version"):
        artifact_path(root=Path("artifacts"), program=ENRICH_PROGRAM, version=version)


@pytest.mark.parametrize("program", PROGRAM_NAMES)
def test_committed_baseline_artifacts_load(program: str) -> None:
    load_program(root=REPO_ARTIFACTS, program=program, version="baseline")
    meta = json.loads((REPO_ARTIFACTS / program / "baseline.meta.json").read_text())

    assert meta["version"] == "baseline"
