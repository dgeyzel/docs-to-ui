"""Turning generations into the API's response models."""

from d2u.generations.models import Generation
from d2u.schemas.api import GenerationResource
from d2u.telemetry.api import trace_url
from plain.urls import reverse


def generation_links(generation: Generation) -> dict[str, str | None]:
    """Server-relative links for a generation."""
    return {
        "self": reverse("api:generation", id=generation.id),
        "page": reverse("api:page", id=generation.id),
        "html": reverse("api:page_html", id=generation.id),
        "ui": reverse("generations:detail", id=generation.id),
        "trace": trace_url(generation.trace_id),
    }


def generation_error(generation: Generation) -> dict[str, object] | None:
    """The stored error, or None when the generation hasn't failed."""
    if not generation.error_code:
        return None
    detail = generation.error_detail or {}
    return {
        "code": generation.error_code,
        "message": detail.get("message") or "",
        "path": detail.get("path") or None,
        "line": detail.get("line"),
    }


def generation_resource(generation: Generation) -> GenerationResource:
    """A generation as the API returns it. The input itself is never included."""
    return GenerationResource.model_validate(
        {
            "id": generation.id,
            "status": generation.status,
            "stage": generation.stage,
            "language": generation.language,
            "strategy": generation.strategy,
            "input": {
                "origin": generation.input_origin,
                "filename": generation.input_filename,
                "entry": generation.input_entry,
                "bytes": generation.input_bytes,
                "sha256": generation.input_sha256,
            },
            "model": generation.model,
            "prompt_label": generation.prompt_label,
            "usage": {
                "input_tokens": generation.input_tokens,
                "output_tokens": generation.output_tokens,
                "cost_usd": generation.cost_usd,
                "latency_ms": generation.latency_ms,
            },
            "error": generation_error(generation),
            "manifest": generation.input_manifest or None,
            "created_at": generation.created_at,
            "started_at": generation.started_at,
            "finished_at": generation.finished_at,
            "links": generation_links(generation),
        }
    )
