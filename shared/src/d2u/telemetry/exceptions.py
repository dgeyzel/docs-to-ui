"""Exceptions raised by the telemetry package."""


class TelemetryError(Exception):
    """Base class for every error raised by the telemetry package."""


class TelemetryConfigurationError(TelemetryError):
    """A telemetry setting is invalid."""
