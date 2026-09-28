from plain.runtime import Secret

TELEMETRY_SERVICE_NAME: str = "docs-to-ui"
TELEMETRY_NATIVE_MAX_ATTRIBUTE_BYTES: int = 262144
# How long a process caches the trace backends chosen in the Tuning app.
TELEMETRY_SETTINGS_TTL_S: int = 10
# False attaches no backends at all (tests and image builds), whatever is
# chosen in the Tuning app.
TELEMETRY_EXPORT_ENABLED: bool = True

# Needed before "langfuse" can be chosen. app/settings.py fills these from
# Langfuse's usual LANGFUSE_* environment variables.
TELEMETRY_LANGFUSE_BASE_URL: str = ""
TELEMETRY_LANGFUSE_PUBLIC_KEY: str = ""
TELEMETRY_LANGFUSE_SECRET_KEY: Secret[str] = ""
TELEMETRY_LANGFUSE_PROJECT_ID: str = ""
