from plain.runtime import Secret

TELEMETRY_BACKENDS: list[str] = ["native"]
TELEMETRY_SERVICE_NAME: str = "docs-to-ui"
TELEMETRY_NATIVE_MAX_ATTRIBUTE_BYTES: int = 262144

# Required when "langfuse" is in TELEMETRY_BACKENDS. app/settings.py fills
# these from Langfuse's usual LANGFUSE_* environment variables.
TELEMETRY_LANGFUSE_BASE_URL: str = ""
TELEMETRY_LANGFUSE_PUBLIC_KEY: str = ""
TELEMETRY_LANGFUSE_SECRET_KEY: Secret[str] = ""
TELEMETRY_LANGFUSE_PROJECT_ID: str = ""
