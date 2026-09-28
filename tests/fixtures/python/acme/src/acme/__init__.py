"""Acme client library."""

from acme.errors import AcmeError

from .client import Client
from .helpers import internal_helper

__all__ = ["Client", "AcmeError", "connect"]


def connect(url: str, *, timeout: float = 5.0) -> "Client":
    """Connect to an Acme server."""
    return Client(url, timeout)
