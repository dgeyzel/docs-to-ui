"""The Docs app's JSON API (SPEC §12.1)."""

from d2u.generations.models import Generation, GenerationStatus
from d2u.schemas.api import (
    ApiError,
    ApiErrorBody,
    FeedbackCreated,
    FeedbackRequest,
    GenerationList,
)
from d2u.sources.registry import display_name
from plain.exceptions import NON_FIELD_ERRORS
from plain.forms import FormFieldMissingError
from plain.forms import ValidationError as FormValidationError
from plain.http import (
    BadRequestError400,
    HTTPException,
    JsonResponse,
    NotFoundError404,
    Response,
)
from plain.urls import reverse
from plain.views import View
from pydantic import BaseModel, ValidationError

from app.api.openapi import build_openapi
from app.api.serializers import generation_resource
from app.api.waiting import is_finished, parse_wait, wait_for_finish
from app.generate.export import render_export_html
from app.generate.feedback import is_known_operation, submit_feedback
from app.generate.forms import SourceForm
from app.generate.lookups import (
    get_generation_or_404,
    succeeded_page,
    succeeded_page_or_404,
)
from app.generate.pipeline import create_generation, enqueue_generation, regenerate
from app.generate.presentation import build_page_view

DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100
ERROR_CODES = {
    400: "bad_request",
    403: "forbidden",
    404: "not_found",
    413: "content_too_large",
    415: "unsupported_media_type",
}
ERROR_MESSAGES = {
    400: "The request is invalid.",
    403: "The request was refused.",
    404: "Not found.",
    413: "The request body is too large.",
    415: "Unsupported content type.",
}


def model_response(
    model: BaseModel, *, status_code: int = 200, headers: dict[str, str] | None = None
) -> Response:
    """A JSON response holding one API model."""
    return Response(
        model.model_dump_json(),
        content_type="application/json",
        status_code=status_code,
        headers=headers,
    )


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    fields: dict[str, list[str]] | None = None,
    generation: Generation | None = None,
) -> Response:
    """A response in the API's error envelope."""
    body = ApiErrorBody(
        code=code,
        message=message,
        fields=fields,
        generation=generation_resource(generation) if generation else None,
    )
    return Response(
        ApiError(error=body).model_dump_json(exclude_none=True),
        content_type="application/json",
        status_code=status_code,
    )


def generation_created(generation: Generation) -> Response:
    """202 with the new generation, which may already have failed to queue."""
    generation = Generation.query.get(generation.id)
    resource = generation_resource(generation)
    return model_response(
        resource, status_code=202, headers={"Location": resource.links.self}
    )


class ApiView(View):
    """A JSON API view: client errors are answered in the error envelope."""

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, FormFieldMissingError):
            return error_response(
                status_code=400,
                code="invalid_input",
                message=exc.message,
                fields={exc.field_name: [exc.message]},
            )
        if isinstance(exc, HTTPException) and exc.status_code < 500:
            status = exc.status_code
            return error_response(
                status_code=status,
                code=ERROR_CODES.get(status, "bad_request"),
                message=str(exc) or ERROR_MESSAGES.get(status, "Request failed."),
            )
        raise exc

    def waited_generation(self) -> Generation:
        """The URL's generation, after waiting as long as `wait` asks."""
        generation = get_generation_or_404(self.url_kwargs)
        timeout_s = parse_wait(self.request.query_params.get("wait"))
        if timeout_s and not is_finished(generation):
            generation = wait_for_finish(generation, timeout_s=timeout_s)
        return generation


class GenerationsView(ApiView):
    def get(self) -> Response:
        params = self.request.query_params
        query = Generation.query.defer("input_blob").order_by("-created_at", "-id")
        status = params.get("status") or ""
        if status:
            if status not in {s.value for s in GenerationStatus}:
                raise BadRequestError400(f"Unknown status {status!r}.")
            query = query.filter(status=status)
        limit = _parse_limit(params.get("limit"))
        return model_response(
            GenerationList(generations=[generation_resource(g) for g in query[:limit]])
        )

    def post(self) -> Response:
        form = SourceForm(request=self.request)
        if not form.is_valid():
            errors = _form_errors(form)
            general = errors.get(NON_FIELD_ERRORS) or []
            return error_response(
                status_code=400,
                code="invalid_input",
                message=general[0] if general else "The submission is invalid.",
                fields=errors,
            )
        generation = create_generation(form.submitted_input())
        enqueue_generation(generation)
        return generation_created(generation)


class GenerationView(ApiView):
    def get(self) -> Response:
        return model_response(generation_resource(self.waited_generation()))


class PageView(ApiView):
    def get(self) -> Response:
        generation = self.waited_generation()
        page = succeeded_page(generation)
        if page is not None:
            return Response(page.model_dump_json(), content_type="application/json")
        if generation.status == GenerationStatus.FAILED:
            return error_response(
                status_code=422,
                code="generation_failed",
                message=f"Generation {generation.id} failed.",
                generation=generation,
            )
        return error_response(
            status_code=409,
            code="not_ready",
            message=f"Generation {generation.id} is {generation.status}.",
            generation=generation,
        )


class PageHtmlView(ApiView):
    def get(self) -> Response:
        generation = get_generation_or_404(self.url_kwargs)
        page = succeeded_page_or_404(generation)
        html = render_export_html(
            page_view=build_page_view(
                page=page, language_display=display_name(generation.language)
            )
        )
        return Response(html, content_type="text/html; charset=utf-8")


class RegenerateView(ApiView):
    def post(self) -> Response:
        original = get_generation_or_404(self.url_kwargs)
        generation = regenerate(original)
        enqueue_generation(generation)
        return generation_created(generation)


class FeedbackView(ApiView):
    def post(self) -> Response:
        generation = get_generation_or_404(self.url_kwargs)
        page = succeeded_page(generation)
        if page is None:
            return error_response(
                status_code=409,
                code="not_ready",
                message="Feedback needs a generation that has succeeded.",
                generation=generation,
            )
        try:
            request = FeedbackRequest.model_validate(self.request.json_data)
        except ValidationError as exc:
            return error_response(
                status_code=400,
                code="invalid_input",
                message="The feedback is invalid.",
                fields=_validation_fields(exc),
            )
        operation_id = request.operation_id or None
        if not is_known_operation(page, operation_id):
            raise NotFoundError404(f"Unknown operation {operation_id!r}.")
        feedback = submit_feedback(
            generation,
            operation_id=operation_id,
            score=request.score,
            comment=request.comment,
        )
        return model_response(
            FeedbackCreated(
                id=feedback.id,
                generation_id=generation.id,
                operation_id=feedback.operation_id or None,
                score=feedback.score,
                comment=feedback.comment,
            ),
            status_code=201,
        )


class OpenApiView(ApiView):
    def get(self) -> Response:
        document = build_openapi(
            server_url=reverse("api:openapi").removesuffix("/openapi.json")
        )
        # Readable UTF-8 rather than \u escapes for non-ASCII text.
        return JsonResponse(document, json_dumps_params={"ensure_ascii": False})


def _parse_limit(raw: str | None) -> int:
    if not raw:
        return DEFAULT_LIST_LIMIT
    try:
        limit = int(raw)
    except ValueError as exc:
        raise BadRequestError400("limit must be a whole number.") from exc
    if not 1 <= limit <= MAX_LIST_LIMIT:
        raise BadRequestError400(f"limit must be between 1 and {MAX_LIST_LIMIT}.")
    return limit


def _form_errors(form: SourceForm) -> dict[str, list[str]]:
    # Plain stores ValidationError objects here, despite the list[str] hint.
    fields: dict[str, list[str]] = {}
    for name, errors in form.errors.items():
        for error in errors:
            messages = (
                error.messages
                if isinstance(error, FormValidationError)
                else [str(error)]
            )
            fields.setdefault(name, []).extend(messages)
    return fields


def _validation_fields(exc: ValidationError) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for error in exc.errors():
        name = ".".join(str(part) for part in error["loc"]) or NON_FIELD_ERRORS
        fields.setdefault(name, []).append(error["msg"])
    return fields
