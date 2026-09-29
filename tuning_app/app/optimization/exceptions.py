"""Exceptions raised by the optimization package."""


class OptimizationError(Exception):
    """Base class for every error raised by the optimization package."""


class OptimizationRunError(OptimizationError):
    """A run can't be started or continued; the message is meant for the user."""


class ProgramExportError(OptimizationError):
    """An optimized program can't be turned into a prompt version."""
