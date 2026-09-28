class Client:
    """A connection to an Acme server."""

    def __init__(self, url: str, timeout: float = 5.0) -> None:
        self.url = url

    def get(self, key: str, *, default: bytes | None = None) -> bytes:
        """Fetch the value stored under `key`."""
        return default or b""

    async def stream(self, *keys: str, **options: str) -> None:
        """Stream values as they change."""

    @staticmethod
    def version() -> str:
        """The client version."""
        return "1.0"

    def _private(self) -> None:
        pass


def _hidden() -> None:
    pass
