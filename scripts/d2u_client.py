"""Generate a documentation page through the Docs app's JSON API and save it.

Usage:
    uv run python scripts/d2u_client.py generate openapi.yaml --out page.json
    uv run python scripts/d2u_client.py generate project.zip --entry api/openapi.yaml \\
        --out page.json --html page.html --base-url https://localhost:8443

The Docs app and its worker must be running. Uses only the standard library,
so the script can be copied anywhere Python runs. Exit codes: 0 saved, 1 the
API refused the input or the generation failed, 3 timed out.
"""

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE_URL = "https://localhost:8443"
API_PREFIX = "/api/v1/"
# Each page request asks the server to wait this long; the server caps it.
WAIT_PER_REQUEST_S = 30
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_TIMEOUT = 3


@dataclass(frozen=True, slots=True)
class HttpResult:
    """One HTTP response, whatever its status."""

    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> dict:
        """The body parsed as a JSON object."""
        return json.loads(self.body)


type Send = Callable[[urllib.request.Request], HttpResult]


class ClientError(Exception):
    """The API refused a request, or a generation failed."""

    def __init__(self, message: str, *, exit_code: int = EXIT_FAILED) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def encode_multipart(
    *, fields: dict[str, str], filename: str, data: bytes, boundary: str
) -> bytes:
    """A `multipart/form-data` body with text fields and one `file` part."""
    lines: list[bytes] = []
    for name, value in fields.items():
        lines += [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="{name}"'.encode(),
            b"",
            value.encode("utf-8"),
        ]
    safe_name = filename.replace('"', "").replace("\r", "").replace("\n", "")
    lines += [
        f"--{boundary}".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{safe_name}"'.encode(),
        b"Content-Type: application/octet-stream",
        b"",
        data,
        f"--{boundary}--".encode(),
        b"",
    ]
    return b"\r\n".join(lines)


def error_message(result: HttpResult) -> str:
    """A readable message from an error response in the API's envelope."""
    try:
        error = result.json()["error"]
    except ValueError, KeyError, TypeError:
        return f"HTTP {result.status}"
    message = f"{error.get('code', 'error')}: {error.get('message', '')}"
    for name, problems in (error.get("fields") or {}).items():
        message += f"\n  {name}: {' '.join(problems)}"
    failure = (error.get("generation") or {}).get("error")
    if failure:
        location = failure.get("path") or ""
        if location and failure.get("line"):
            location += f":{failure['line']}"
        where = f" ({location})" if location else ""
        message += f"\n  {failure.get('code')}{where}: {failure.get('message', '')}"
    return message


def make_send(*, context: ssl.SSLContext | None, timeout_s: float) -> Send:
    """A `Send` over urllib that returns error statuses instead of raising."""

    def send(request: urllib.request.Request) -> HttpResult:
        try:
            with urllib.request.urlopen(
                request, timeout=timeout_s, context=context
            ) as response:
                return HttpResult(
                    status=response.status,
                    body=response.read(),
                    headers=dict(response.headers.items()),
                )
        except urllib.error.HTTPError as exc:
            return HttpResult(
                status=exc.code, body=exc.read(), headers=dict(exc.headers.items())
            )
        except urllib.error.URLError as exc:
            raise ClientError(f"Could not reach the Docs app: {exc.reason}") from exc

    return send


@dataclass(frozen=True, slots=True)
class Generated:
    """A finished generation: its id, `DocPage` JSON and optional HTML."""

    generation_id: int
    page_json: bytes
    html: bytes | None


def generate(
    *,
    send: Send,
    base_url: str,
    filename: str,
    data: bytes,
    language: str = "",
    entry: str = "",
    strategy: str = "",
    want_html: bool = False,
    timeout_s: float = 600,
    clock: Callable[[], float] = time.monotonic,
) -> Generated:
    """Upload one file, wait for its page, and return it.

    Raises:
        ClientError: The input was refused, the generation failed, or it
            didn't finish within `timeout_s`.
    """
    boundary = uuid.uuid4().hex
    body = encode_multipart(
        fields={"language": language, "entry": entry, "strategy": strategy},
        filename=filename,
        data=data,
        boundary=boundary,
    )
    created = send(
        urllib.request.Request(
            urllib.parse.urljoin(base_url, API_PREFIX + "generations"),
            data=body,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
            },
        )
    )
    if created.status != 202:
        raise ClientError(error_message(created))
    generation = created.json()
    links = generation["links"]

    deadline = clock() + timeout_s
    while True:
        wait = max(1, min(WAIT_PER_REQUEST_S, int(deadline - clock())))
        page = send(_get(base_url, f"{links['page']}?wait={wait}"))
        if page.status == 200:
            break
        if page.status != 409:
            raise ClientError(error_message(page))
        if clock() >= deadline:
            raise ClientError(
                f"Generation {generation['id']} didn't finish in {timeout_s:g} s.",
                exit_code=EXIT_TIMEOUT,
            )

    html = None
    if want_html:
        exported = send(_get(base_url, links["html"]))
        if exported.status != 200:
            raise ClientError(error_message(exported))
        html = exported.body
    return Generated(generation_id=generation["id"], page_json=page.body, html=html)


def _get(base_url: str, path: str) -> urllib.request.Request:
    return urllib.request.Request(urllib.parse.urljoin(base_url, path), method="GET")


def ssl_context(*, insecure: bool, ca_file: str | None) -> ssl.SSLContext:
    """TLS settings: the system's CAs, a given CA file, or no verification."""
    context = ssl.create_default_context(cafile=ca_file)
    if insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def main(argv: list[str] | None = None, *, send: Send | None = None) -> int:
    """Run the client. Returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    gen = commands.add_parser("generate", help="Document a file or zip.")
    gen.add_argument("path", type=Path, help="A .yaml, .yml, .json, .py or .zip file.")
    gen.add_argument(
        "--out", type=Path, required=True, help="Where to write the DocPage JSON."
    )
    gen.add_argument(
        "--html", type=Path, help="Also write the standalone HTML export here."
    )
    gen.add_argument(
        "--language", default="", help='"openapi" or "python"; detected when omitted.'
    )
    gen.add_argument("--entry", default="", help="The entry file inside a zip.")
    gen.add_argument("--strategy", default="", help='"llm" or "hybrid" (if enabled).')
    gen.add_argument("--base-url", default=DEFAULT_BASE_URL, help="The Docs app's URL.")
    gen.add_argument(
        "--timeout", type=float, default=600, help="Seconds to wait in total."
    )
    gen.add_argument(
        "--ca-file", help="A CA certificate to trust, e.g. mkcert's root CA."
    )
    gen.add_argument(
        "--insecure", action="store_true", help="Skip TLS certificate checks."
    )
    args = parser.parse_args(argv)

    if send is None:
        context = ssl_context(insecure=args.insecure, ca_file=args.ca_file)
        send = make_send(context=context, timeout_s=WAIT_PER_REQUEST_S + 30)
    try:
        result = generate(
            send=send,
            base_url=args.base_url,
            filename=args.path.name,
            data=args.path.read_bytes(),
            language=args.language,
            entry=args.entry,
            strategy=args.strategy,
            want_html=args.html is not None,
            timeout_s=args.timeout,
        )
    except ClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    args.out.write_bytes(result.page_json)
    print(f"wrote: {args.out} (generation {result.generation_id})")
    if args.html is not None and result.html is not None:
        args.html.write_bytes(result.html)
        print(f"wrote: {args.html}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
