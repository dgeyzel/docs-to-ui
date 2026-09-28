"""Forwarding finished spans only to the trace backends chosen in the UI.

Plain-free, so it can be tested without an app. The selection is loaded by a
callable and cached for a TTL, so a change made in the Tuning app reaches
every process without a restart (SPEC §11.2).
"""

import logging
import threading
import time
from collections.abc import Callable, Mapping

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor

logger = logging.getLogger(__name__)

WARNING_INTERVAL_S = 60.0


class SelectionCache:
    """The chosen backend names, reloaded at most once per TTL.

    A failed load keeps the previous selection (empty before the first
    success) and is retried after the TTL, so a database outage costs at most
    one attempt per TTL. `current()` never raises.

    Args:
        load: Returns the chosen backend names. May raise.
        ttl_s: Longest time a loaded selection is used before reloading.
        clock: Monotonic clock in seconds, injectable for tests.
    """

    def __init__(
        self,
        load: Callable[[], frozenset[str]],
        *,
        ttl_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._load = load
        self._ttl_s = ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._selection: frozenset[str] = frozenset()
        self._expires_at = float("-inf")
        self._last_warning = float("-inf")

    def current(self) -> frozenset[str]:
        """The cached selection, reloaded first if the TTL has passed."""
        with self._lock:
            now = self._clock()
            if now >= self._expires_at:
                self._refresh(now)
            return self._selection

    def invalidate(self) -> None:
        """Reload on the next `current()` call, e.g. right after a change."""
        with self._lock:
            self._expires_at = float("-inf")

    def _refresh(self, now: float) -> None:
        self._expires_at = now + self._ttl_s
        try:
            self._selection = frozenset(self._load())
        except Exception:
            # Telemetry boundary: a failed lookup must never affect the caller.
            if now - self._last_warning >= WARNING_INTERVAL_S:
                self._last_warning = now
                logger.warning(
                    "Could not load the trace backend selection; keeping %s",
                    sorted(self._selection),
                    exc_info=True,
                )


class RoutingSpanProcessor(SpanProcessor):
    """Sends each finished span to the processors of the selected backends.

    Every available backend's processor is attached once, at startup; only
    the routing changes at runtime.

    Args:
        processors: One processor per available backend, by backend name.
        selection: Returns the currently selected backend names. Names
            without a processor (an unavailable backend) are ignored.
    """

    def __init__(
        self,
        processors: Mapping[str, SpanProcessor],
        selection: Callable[[], frozenset[str]],
    ) -> None:
        self._processors = dict(processors)
        self._selection = selection

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        """Nothing to do: backends only receive finished spans."""

    def on_end(self, span: ReadableSpan) -> None:
        """Forward the span to every selected backend. Never raises."""
        try:
            selected = self._selection()
        except Exception:
            # Telemetry boundary: routing must never affect the traced code.
            logger.exception("Could not read the trace backend selection")
            return
        for name, processor in self._processors.items():
            if name not in selected:
                continue
            try:
                processor.on_end(span)
            except Exception:
                # Telemetry boundary: one backend must not break the others.
                logger.exception("Trace backend %s rejected a span", name)

    def shutdown(self) -> None:
        """Shut down every backend's processor, selected or not."""
        for processor in self._processors.values():
            processor.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Flush every backend's processor; True only if all succeed."""
        results = [
            processor.force_flush(timeout_millis)
            for processor in self._processors.values()
        ]
        return all(results)
