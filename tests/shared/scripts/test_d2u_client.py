import json
import urllib.request
from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path

import pytest

from scripts.d2u_client import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_TIMEOUT,
    ClientError,
    HttpResult,
    encode_multipart,
    error_message,
    generate,
    main,
)

BASE_URL = "https://localhost:8443"
GENERATION = {
    "id": 7,
    "links": {
        "self": "/api/v1/generations/7",
        "page": "/api/v1/generations/7/page",
        "html": "/api/v1/generations/7/page.html",
    },
}
PAGE = b'{"schema_version": 2}'


def json_result(status: int, body: dict) -> HttpResult:
    return HttpResult(status=status, body=json.dumps(body).encode())


def not_ready() -> HttpResult:
    return json_result(409, {"error": {"code": "not_ready", "message": "pending"}})


class FakeServer:
    """Answers requests in order and records them."""

    def __init__(self, *responses: HttpResult) -> None:
        self.responses = list(responses)
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request) -> HttpResult:
        self.requests.append(request)
        return self.responses.pop(0)


class SteppingClock:
    def __init__(self, step: float) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


def test_encode_multipart_is_readable_as_form_data() -> None:
    body = encode_multipart(
        fields={"language": "openapi", "entry": ""},
        filename='spec".yaml',
        data=b"openapi: 3.0.0\n",
        boundary="b0undary",
    )

    message = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: multipart/form-data; boundary=b0undary\r\n\r\n" + body
    )
    parts = {
        part.get_param("name", header="content-disposition"): part
        for part in message.iter_parts()
    }
    assert parts["language"].get_content() == "openapi"
    assert parts["file"].get_filename() == "spec.yaml"
    assert parts["file"].get_content() == b"openapi: 3.0.0\n"


def test_generate_uploads_waits_and_returns_the_page_and_html() -> None:
    server = FakeServer(
        json_result(202, GENERATION),
        not_ready(),
        HttpResult(status=200, body=PAGE),
        HttpResult(status=200, body=b"<html></html>"),
    )

    result = generate(
        send=server,
        base_url=BASE_URL,
        filename="spec.yaml",
        data=b"openapi: 3.0.0\n",
        want_html=True,
    )

    assert (result.generation_id, result.page_json, result.html) == (
        7,
        PAGE,
        b"<html></html>",
    )
    post, *gets = server.requests
    assert post.get_method() == "POST"
    assert post.full_url == f"{BASE_URL}/api/v1/generations"
    assert post.get_header("Content-type", "").startswith("multipart/form-data")
    assert gets[0].full_url.startswith(f"{BASE_URL}/api/v1/generations/7/page?wait=")
    assert gets[-1].full_url == f"{BASE_URL}/api/v1/generations/7/page.html"


def test_generate_reports_a_refused_submission() -> None:
    server = FakeServer(
        json_result(
            400,
            {
                "error": {
                    "code": "invalid_input",
                    "message": "The submission is invalid.",
                    "fields": {"file": ["File exceeds the 1.0 MB limit."]},
                }
            },
        )
    )

    with pytest.raises(ClientError, match="File exceeds") as caught:
        generate(send=server, base_url=BASE_URL, filename="a.yaml", data=b"x")
    assert caught.value.exit_code == EXIT_FAILED


def test_generate_reports_a_failed_generation_with_its_location() -> None:
    failure = {
        "error": {
            "code": "generation_failed",
            "message": "Generation 7 failed.",
            "generation": {
                "error": {
                    "code": "input_error",
                    "message": "Bad YAML.",
                    "path": "broken.yaml",
                    "line": 6,
                }
            },
        }
    }
    server = FakeServer(json_result(202, GENERATION), json_result(422, failure))

    with pytest.raises(ClientError, match=r"input_error \(broken.yaml:6\): Bad YAML."):
        generate(send=server, base_url=BASE_URL, filename="broken.yaml", data=b"x")


def test_generate_times_out() -> None:
    server = FakeServer(json_result(202, GENERATION), *[not_ready() for _ in range(5)])

    with pytest.raises(ClientError, match="didn't finish") as caught:
        generate(
            send=server,
            base_url=BASE_URL,
            filename="a.yaml",
            data=b"x",
            timeout_s=3,
            clock=SteppingClock(step=1),
        )
    assert caught.value.exit_code == EXIT_TIMEOUT


def test_error_message_falls_back_to_the_status() -> None:
    assert error_message(HttpResult(status=502, body=b"<html>")) == "HTTP 502"


def test_main_writes_the_page_and_html(tmp_path: Path) -> None:
    source = tmp_path / "spec.yaml"
    source.write_text("openapi: 3.0.0\n")
    out, html = tmp_path / "page.json", tmp_path / "page.html"
    server = FakeServer(
        json_result(202, GENERATION),
        HttpResult(status=200, body=PAGE),
        HttpResult(status=200, body=b"<html></html>"),
    )

    code = main(
        ["generate", str(source), "--out", str(out), "--html", str(html)], send=server
    )

    assert code == EXIT_OK
    assert out.read_bytes() == PAGE
    assert html.read_bytes() == b"<html></html>"


def test_main_returns_the_failure_exit_code(tmp_path: Path, capsys) -> None:
    source = tmp_path / "spec.yaml"
    source.write_text("x")
    server = FakeServer(
        json_result(400, {"error": {"code": "invalid_input", "message": "No."}})
    )

    code = main(
        ["generate", str(source), "--out", str(tmp_path / "p.json")], send=server
    )

    assert code == EXIT_FAILED
    assert "invalid_input: No." in capsys.readouterr().err
    assert not (tmp_path / "p.json").exists()
