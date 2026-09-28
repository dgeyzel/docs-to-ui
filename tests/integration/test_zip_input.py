from io import BytesIO

import pytest
from plain.test import Client

from app.generations.jobs import GenerateDocJob
from app.generations.models import Generation
from app.llm.schemas import DocPage
from tests.helpers import FIXTURES_DIR, make_zip, zip_dir

pytestmark = pytest.mark.usefixtures("db")

SPEC = "openapi: 3.0.0\ninfo: {title: X, version: '1'}\npaths:\n  /a:\n    get: {}\n"


def upload_zip(data: bytes, *, language: str = "", entry: str = "") -> Generation:
    file = BytesIO(data)
    file.name = "source.zip"
    response = Client().post(
        "/generations",
        data={"file": file, "text": "", "language": language, "entry": entry},
    )
    assert response.status_code == 302
    generation = Generation.query.order_by("-id").first()
    assert generation is not None
    GenerateDocJob(generation.id).run()
    return Generation.query.get(generation.id)


def test_python_package_zip_is_documented_with_a_manifest() -> None:
    generation = upload_zip(
        zip_dir(FIXTURES_DIR / "python" / "acme", prefix="acme-main/")
    )

    assert generation.status == "succeeded"
    assert generation.input_origin == "zip"
    assert generation.language == "python"
    assert generation.input_manifest == {
        "included": [
            "src/acme/__init__.py",
            "src/acme/client.py",
            "src/acme/errors.py",
            "src/acme/helpers.py",
            "src/acme/plugins/loader.py",
        ],
        "skipped": [
            {"path": "pyproject.toml", "reason": "not a Python file"},
            {
                "path": "src/acme/tests/test_client.py",
                "reason": "excluded: **/tests/**",
            },
            {"path": "tests/test_acme.py", "reason": "excluded: **/tests/**"},
        ],
    }
    page = DocPage.model_validate(generation.doc_json)
    assert page.surface.title == "acme"
    assert len(page.surface.operations) == 8

    html = Client().get(f"/generations/{generation.id}").content.decode()
    assert "Files read (5 included, 3 skipped)" in html
    assert "excluded: **/tests/**" in html
    assert "acme.Client" in html


def test_multi_file_openapi_zip_resolves_refs() -> None:
    generation = upload_zip(zip_dir(FIXTURES_DIR / "openapi" / "multi"))

    assert generation.status == "succeeded"
    assert generation.language == "openapi"
    page = DocPage.model_validate(generation.doc_json)
    assert [op.id for op in page.surface.operations] == ["GET /pets", "GET /status"]
    assert generation.input_manifest["skipped"] == [
        {"path": "README.md", "reason": "not an OpenAPI file"}
    ]


def test_zip_with_unsafe_paths_fails_with_input_error() -> None:
    generation = upload_zip(make_zip({"ok.py": "def f(): pass", "../evil.py": "x"}))

    assert generation.status == "failed"
    assert generation.error_code == "input_error"
    assert "'..'" in generation.error_detail["message"]


def test_zip_limits_come_from_settings(settings) -> None:
    settings.SOURCES_ZIP_MAX_ENTRIES = 2

    generation = upload_zip(make_zip({"a.py": "", "b.py": "", "c.py": ""}))

    assert generation.status == "failed"
    assert generation.error_code == "input_error"
    assert "more than 2 entries" in generation.error_detail["message"]


def test_several_entry_files_need_a_choice_in_the_form() -> None:
    data = make_zip(
        {"v1/openapi.yaml": SPEC, "v2/openapi.yaml": SPEC.replace("/a", "/b")}
    )

    ambiguous = upload_zip(data)
    chosen = upload_zip(data, entry="v2/openapi.yaml")

    assert ambiguous.status == "failed"
    assert "Entry file" in ambiguous.error_detail["message"]
    assert chosen.status == "succeeded", chosen.error_detail
    assert chosen.input_entry == "v2/openapi.yaml"
    page = DocPage.model_validate(chosen.doc_json)
    assert [op.id for op in page.surface.operations] == ["GET /b"]


def test_mixed_zips_use_the_chosen_language_and_skip_the_rest() -> None:
    data = make_zip(
        {
            "openapi.yaml": SPEC,
            "client.py": "def get(key: str) -> str:\n    return key\n",
        }
    )

    detected = upload_zip(data)
    python = upload_zip(data, language="python")

    assert detected.language == "openapi"
    assert python.language == "python"
    assert python.input_manifest["skipped"] == [
        {"path": "openapi.yaml", "reason": "not a Python file"}
    ]


def test_regenerate_keeps_the_zip_and_entry_choice() -> None:
    data = make_zip(
        {"v1/openapi.yaml": SPEC, "v2/openapi.yaml": SPEC.replace("/a", "/b")}
    )
    original = upload_zip(data, entry="v2/openapi.yaml")

    Client().post(f"/generations/{original.id}/regenerate")
    copy = Generation.query.order_by("-id").first()
    assert copy is not None
    GenerateDocJob(copy.id).run()

    copy = Generation.query.get(copy.id)
    assert copy.status == "succeeded"
    assert copy.input_origin == "zip"
    assert copy.input_entry == "v2/openapi.yaml"
