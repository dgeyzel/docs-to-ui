"""Exceptions raised by the gold sets package."""


class GoldSetsError(Exception):
    """Base class for every error raised by the gold sets package."""


class GoldSetError(GoldSetsError):
    """A gold-set operation can't be done; the message is meant for the user."""
