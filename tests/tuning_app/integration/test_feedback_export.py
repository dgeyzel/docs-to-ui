import json
from pathlib import Path

import pytest
from d2u.generations.models import Feedback, Generation
from plain.postgres import get_connection
from plain.postgres.database_url import build_database_url

from dspy_pipeline.optimize import feedback_candidates, main
from tests.helpers import make_zip

pytestmark = pytest.mark.usefixtures("isolated_db")


def make_generation(
    *, origin: str, filename: str, data: bytes, language: str
) -> Generation:
    generation = Generation(
        language=language,
        input_origin=origin,
        input_filename=filename,
        input_blob=data,
        input_sha256="0" * 64,
        input_bytes=len(data),
        status="succeeded",
    )
    generation.create()
    return generation


def add_feedback(
    generation: Generation, *, score: int, comment: str, operation_id: str = ""
) -> None:
    Feedback(
        generation=generation, operation_id=operation_id, score=score, comment=comment
    ).create()


def test_export_includes_only_thumbs_down_with_comments() -> None:
    paste = make_generation(
        origin="paste", filename="", data=b"openapi: 3.0.0\n", language="openapi"
    )
    add_feedback(paste, score=-1, comment="Wrong limit.", operation_id="GET /pets")
    add_feedback(paste, score=-1, comment="")
    add_feedback(paste, score=1, comment="Great.")

    candidates = feedback_candidates(build_database_url(get_connection().settings_dict))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.language == "openapi"
    assert candidate.origin == "paste"
    assert candidate.files == {"input.yaml": "openapi: 3.0.0\n"}
    assert candidate.operation_id == "GET /pets"
    assert candidate.comment == "Wrong limit."


def test_export_unpacks_zip_inputs_safely(tmp_path: Path) -> None:
    data = make_zip({"repo/pkg/__init__.py": "", "repo/pkg/core.py": "def f(): pass\n"})
    generation = make_generation(
        origin="zip", filename="repo.zip", data=data, language="python"
    )
    add_feedback(generation, score=-1, comment="Missing examples.")
    output = tmp_path / "candidates.jsonl"

    main(
        [
            "export-feedback",
            "--database-url",
            build_database_url(get_connection().settings_dict),
            "--output",
            str(output),
        ]
    )

    (line,) = output.read_text().splitlines()
    candidate = json.loads(line)
    assert candidate["origin"] == "zip"
    assert candidate["files"] == {
        "pkg/__init__.py": "",
        "pkg/core.py": "def f(): pass\n",
    }
    assert "operation_id" not in candidate
