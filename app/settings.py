import os

URLS_ROUTER = "app.urls.AppRouter"

TIME_ZONE = "America/Chicago"

INSTALLED_PACKAGES = [
    "plain.postgres",
    "plain.jobs",
    "plain.htmx",
    "plain.elements",
    "plain.assets",
    "plain.templates",
    # Local packages. app.telemetry comes first so startup spans aren't dropped.
    "app.telemetry",
    "app.traces",
    "app.sources",
    "app.generations",
]

JOBS_SCHEDULE = [
    ("app.traces.jobs.PruneTracesJob", "@daily"),
]

# Pasted input is sent as form data, so this must exceed
# GENERATIONS_MAX_INPUT_BYTES (5 MB); the form enforces the exact limit.
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024

MIDDLEWARE = [
    "plain.postgres.DatabaseConnectionMiddleware",
]

# Langfuse's conventional variable names (SPEC §15). The PLAIN_TELEMETRY_LANGFUSE_*
# forms work too and take precedence.
TELEMETRY_LANGFUSE_BASE_URL = os.environ.get("LANGFUSE_BASE_URL", "")
TELEMETRY_LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
TELEMETRY_LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
TELEMETRY_LANGFUSE_PROJECT_ID = os.environ.get("LANGFUSE_PROJECT_ID", "")
