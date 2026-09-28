"""Running one strategy on a prepared bundle, outside the Docs app's job.

Plain-free. The Tuning app seeds gold examples and runs evals through this,
so they use the same generation functions as the Docs app (SPEC D13): the
syntax check before an `llm` call, extraction for `hybrid` and `parser`, and
the strategies in `d2u.generation.strategies`.
"""

from opentelemetry import trace

from d2u.generation.client import ModelSpec
from d2u.generation.exceptions import LLMConfigurationError
from d2u.generation.prompts import PromptSpec
from d2u.generation.strategies import (
    GenerationConfig,
    GenerationResult,
    generate_hybrid,
    generate_llm,
    generate_parser,
)
from d2u.schemas.docpage import ApiSurface
from d2u.sources.adapters.base import LanguageAdapter
from d2u.sources.bundle import SourceBundle
from d2u.sources.registry import select_files

tracer = trace.get_tracer(__name__)
STRATEGIES = ("llm", "hybrid", "parser")


def generate_for_bundle(
    *,
    strategy: str,
    bundle: SourceBundle,
    adapter: LanguageAdapter,
    config: GenerationConfig,
    model: ModelSpec | None = None,
    prompt: PromptSpec | None = None,
) -> GenerationResult:
    """Build a page from a bundle with one strategy.

    The bundle is first filtered to the files the adapter reads, as the Docs
    app does for a zip. `llm` and `hybrid` need a model and a prompt;
    `parser` needs neither.

    Raises:
        InputError: The input doesn't parse.
        LLMConfigurationError: A model or prompt is missing, or misconfigured.
        ProviderError, OutputValidationError, GenerationFailedError,
            GenerationTimeoutError: As raised by the strategy.
        ValueError: The strategy is unknown.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy {strategy!r}")
    bundle, _ = select_files(bundle, adapter)
    if strategy == "parser":
        return generate_parser(
            surface=_extract(bundle, adapter),
            group_of=adapter.group_key,
            display_name=adapter.display_name,
        )
    if strategy == "llm":
        with tracer.start_as_current_span("check", attributes={"docs.stage": "check"}):
            adapter.check_syntax(bundle)
    if model is None or prompt is None:
        raise LLMConfigurationError(
            f"The {strategy} strategy needs a model and a prompt."
        )
    if strategy == "llm":
        return generate_llm(
            source_files={file.path: file.text for file in bundle.files},
            entry=adapter.entry_file(bundle),
            language=adapter.name,
            model=model,
            prompt=prompt,
            config=config,
        )
    return generate_hybrid(
        surface=_extract(bundle, adapter),
        group_of=adapter.group_key,
        display_name=adapter.display_name,
        model=model,
        prompt=prompt,
        config=config,
    )


def _extract(bundle: SourceBundle, adapter: LanguageAdapter) -> ApiSurface:
    with tracer.start_as_current_span("extract", attributes={"docs.stage": "extract"}):
        return adapter.extract(bundle)
