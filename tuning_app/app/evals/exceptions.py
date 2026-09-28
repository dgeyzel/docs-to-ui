"""Exceptions raised by the evals package."""


class EvalsError(Exception):
    """Base class for every error raised by the evals package."""


class EvalRunError(EvalsError):
    """An eval run can't be started or continued; the message is meant for the user."""
