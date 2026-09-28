"""Exceptions raised by the prompts package."""


class PromptsError(Exception):
    """Base class for every error raised by the prompts package."""


class PromptError(PromptsError):
    """A prompt operation can't be done; the message is meant for the user."""
