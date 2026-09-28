"""Exceptions raised while generating a page."""


class GenerationError(Exception):
    """Base class for every error raised by the generation package."""


class LLMConfigurationError(GenerationError):
    """A model or prompt is configured incorrectly (bad parameters, missing key)."""


class ProviderError(GenerationError):
    """The model provider failed: auth, rate limits, outages, bad requests."""


class OutputValidationError(GenerationError):
    """The model's answer didn't validate, even after one retry."""


class GenerationFailedError(GenerationError):
    """Too many `hybrid` batches failed for the page to be useful.

    Args:
        message: What went wrong, safe to show to the user.
        provider: True when the failures came from the model provider.
    """

    def __init__(self, message: str, *, provider: bool) -> None:
        self.provider = provider
        super().__init__(message)


class GenerationTimeoutError(GenerationError):
    """The soft generation deadline passed."""
