import json
import re

from d2u.sources.adapters.openapi import OpenApiAdapter
from plain.test import Client

from app.api.openapi import build_openapi
from app.api.urls import ApiRouter
from tests.helpers import bundle_of

HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def api_document() -> dict:
    return build_openapi(server_url="/api/v1")


def openapi_path(raw_route: str) -> str:
    return "/" + re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", raw_route)


def test_every_api_route_is_described() -> None:
    routes = {openapi_path(url.raw_route) for url in ApiRouter.urls}

    assert set(api_document()["paths"]) == routes


def test_every_schema_reference_resolves() -> None:
    document = api_document()
    text = json.dumps(document)
    refs = set(re.findall(r'"#/components/schemas/([^"]+)"', text))

    assert refs
    assert refs <= set(document["components"]["schemas"])


def test_the_served_description_documents_itself() -> None:
    response = Client().get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert response.json()["servers"] == [{"url": "/api/v1"}]
    adapter = OpenApiAdapter()
    bundle = bundle_of("openapi.json", response.content.decode("utf-8"))

    adapter.check_syntax(bundle)
    surface = adapter.extract(bundle)
    escaped = bundle_of("openapi.json", json.dumps(api_document()))
    assert adapter.extract(escaped) == surface

    operation_ids = {op.id for op in surface.operations}
    described = {
        f"{method.upper()} {path}"
        for path, item in api_document()["paths"].items()
        for method in HTTP_METHODS
        if method in item
    }
    assert operation_ids == described
