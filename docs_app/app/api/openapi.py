"""The OpenAPI 3.1 description of the JSON API, built from its response models."""

from typing import Any

from d2u.schemas.api import (
    ApiError,
    FeedbackCreated,
    FeedbackRequest,
    GenerationList,
    GenerationResource,
    TextSubmission,
)
from d2u.schemas.docpage import DocPage
from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaMode, models_json_schema

SCHEMA_REF = "#/components/schemas/{model}"
RESPONSE_MODELS: tuple[type[BaseModel], ...] = (
    GenerationResource,
    GenerationList,
    ApiError,
    FeedbackCreated,
    DocPage,
)
REQUEST_MODELS: tuple[type[BaseModel], ...] = (TextSubmission, FeedbackRequest)

# OpenAPI documents are free-form JSON objects.
type JsonObject = dict[str, Any]


def _ref(name: str) -> JsonObject:
    return {"$ref": SCHEMA_REF.format(model=name)}


def _json(name: str, description: str) -> JsonObject:
    return {
        "description": description,
        "content": {"application/json": {"schema": _ref(name)}},
    }


def _error(description: str) -> JsonObject:
    return _json("ApiError", description)


ID_PARAMETER: JsonObject = {
    "name": "id",
    "in": "path",
    "required": True,
    "schema": {"type": "integer"},
    "description": "The generation's id.",
}
WAIT_PARAMETER: JsonObject = {
    "name": "wait",
    "in": "query",
    "required": False,
    "schema": {"type": "integer", "minimum": 0},
    "description": "Seconds to wait for the generation to finish, capped by the server.",
}
NOT_FOUND = _error("No generation has this id.")


def _paths() -> JsonObject:
    return {
        "/generations": {
            "get": {
                "operationId": "listGenerations",
                "summary": "List generations",
                "description": "Generations, newest first.",
                "parameters": [
                    {
                        "name": "status",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "string",
                            "enum": ["pending", "running", "succeeded", "failed"],
                        },
                        "description": "Only generations with this status.",
                    },
                    {
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 20,
                        },
                        "description": "How many generations to return.",
                    },
                ],
                "responses": {
                    "200": _json("GenerationList", "The generations."),
                    "400": _error("An unknown status or a bad limit."),
                },
            },
            "post": {
                "operationId": "createGeneration",
                "summary": "Start a generation",
                "description": (
                    "Upload a file or `.zip`, or send pasted text, to document. "
                    "The generation runs in the background; poll it, or fetch its "
                    "page with `wait`."
                ),
                "requestBody": {
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "file": {
                                        "type": "string",
                                        "format": "binary",
                                        "description": "A `.yaml`, `.yml`, `.json`, `.py` or `.zip` file.",
                                    },
                                    "text": {
                                        "type": "string",
                                        "description": "Pasted source, instead of a file.",
                                    },
                                    "language": {
                                        "type": "string",
                                        "description": 'An adapter name; "" detects it.',
                                    },
                                    "entry": {
                                        "type": "string",
                                        "description": "The entry file inside a zip.",
                                    },
                                    "strategy": {
                                        "type": "string",
                                        "enum": ["", "llm", "hybrid"],
                                    },
                                },
                            }
                        },
                        "application/json": {"schema": _ref("TextSubmission")},
                    },
                },
                "responses": {
                    "202": _json(
                        "GenerationResource", "The generation was created and queued."
                    ),
                    "400": _error("The submission is invalid (`invalid_input`)."),
                    "413": _error("The request body is too large."),
                },
            },
        },
        "/generations/{id}": {
            "get": {
                "operationId": "getGeneration",
                "summary": "Get a generation",
                "description": "Its status, input metadata, usage, error and links.",
                "parameters": [ID_PARAMETER, WAIT_PARAMETER],
                "responses": {
                    "200": _json("GenerationResource", "The generation."),
                    "404": NOT_FOUND,
                },
            }
        },
        "/generations/{id}/page": {
            "get": {
                "operationId": "getGenerationPage",
                "summary": "Get the generated page",
                "description": "The `DocPage` JSON, the same as the JSON export.",
                "parameters": [ID_PARAMETER, WAIT_PARAMETER],
                "responses": {
                    "200": _json("DocPage", "The page."),
                    "404": NOT_FOUND,
                    "409": _error("The generation hasn't finished (`not_ready`)."),
                    "422": _error("The generation failed (`generation_failed`)."),
                },
            }
        },
        "/generations/{id}/page.html": {
            "get": {
                "operationId": "getGenerationPageHtml",
                "summary": "Get the page as standalone HTML",
                "description": "One self-contained file that makes no network requests.",
                "parameters": [ID_PARAMETER],
                "responses": {
                    "200": {
                        "description": "The page.",
                        "content": {"text/html": {"schema": {"type": "string"}}},
                    },
                    "404": _error("No generation has this id, or it hasn't succeeded."),
                },
            }
        },
        "/generations/{id}/regenerate": {
            "post": {
                "operationId": "regenerateGeneration",
                "summary": "Regenerate",
                "description": "Start a new generation from the same input.",
                "parameters": [ID_PARAMETER],
                "responses": {
                    "202": _json("GenerationResource", "The new generation."),
                    "404": NOT_FOUND,
                },
            }
        },
        "/generations/{id}/feedback": {
            "post": {
                "operationId": "createFeedback",
                "summary": "Rate a page or one operation",
                "description": "Recorded and mirrored like the page's 👍 / 👎.",
                "parameters": [ID_PARAMETER],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {"schema": _ref("FeedbackRequest")}
                    },
                },
                "responses": {
                    "201": _json("FeedbackCreated", "The feedback was recorded."),
                    "400": _error("The feedback is invalid (`invalid_input`)."),
                    "404": _error(
                        "No generation has this id, or the operation is unknown."
                    ),
                    "409": _error("The generation hasn't succeeded (`not_ready`)."),
                },
            }
        },
        "/openapi.json": {
            "get": {
                "operationId": "getOpenApi",
                "summary": "This description",
                "description": "The OpenAPI 3.1 description of this API.",
                "responses": {
                    "200": {
                        "description": "The description.",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    }
                },
            }
        },
    }


def component_schemas() -> JsonObject:
    """JSON schemas of every request and response model, keyed by model name."""
    models: list[tuple[type[BaseModel], JsonSchemaMode]] = [
        (model, "serialization") for model in RESPONSE_MODELS
    ] + [(model, "validation") for model in REQUEST_MODELS]
    _, schema = models_json_schema(models, ref_template=SCHEMA_REF)
    return schema["$defs"]


def build_openapi(*, server_url: str) -> JsonObject:
    """The OpenAPI document, with paths relative to `server_url`."""
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Docs-to-UI API",
            "version": "1",
            "description": (
                "Generate documentation pages from OpenAPI documents and Python "
                "source, and fetch them as `DocPage` JSON or standalone HTML."
            ),
        },
        "servers": [{"url": server_url}],
        "paths": _paths(),
        "components": {"schemas": component_schemas()},
    }
