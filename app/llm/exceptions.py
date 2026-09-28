"""Exceptions raised by the LLM layer."""


class LLMError(Exception):
    """Base class for every error raised by the llm package."""


class LLMConfigurationError(LLMError):
    """The LLM layer was configured incorrectly (bad model or missing fixtures)."""


class ArtifactNotFoundError(LLMError):
    """No program artifact exists for the requested program and version."""


class GenerationFailedError(LLMError):
    """Too many batches failed for the page to be useful.

    Args:
        message: What went wrong, safe to show to the user.
        provider: True when the failures came from the model provider
            (auth, rate limits, outages) rather than from invalid output.
    """

    def __init__(self, message: str, *, provider: bool) -> None:
        self.provider = provider
        super().__init__(message)


class GenerationTimeoutError(LLMError):
    """The soft generation deadline passed."""
