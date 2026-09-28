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
    # Shared packages. d2u.telemetry comes first so startup spans aren't dropped.
    "d2u.telemetry",
    "d2u.traces",
    "d2u.sources",
    "d2u.registry",
    "d2u.generations",
    "d2u.ui",
    # Local packages.
    "app.generate",
]

JOBS_SCHEDULE = [
    ("d2u.traces.jobs.PruneTracesJob", "@daily"),
]

# Pasted input is sent as form data, so this must exceed
# GENERATIONS_MAX_INPUT_BYTES (1 MB); the form enforces the exact limit.
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# The database is shared with the Tuning app, whose tables and migrations the
# Docs app doesn't install. Without this, preflight would offer to drop them.
PREFLIGHT_SILENCED_CHECKS = [
    "postgres.database_tables",
    "postgres.prunable_migrations",
]

MIDDLEWARE = [
    "plain.postgres.DatabaseConnectionMiddleware",
]

# Langfuse's conventional variable names (SPEC §15). The PLAIN_TELEMETRY_LANGFUSE_*
# forms work too and take precedence.
TELEMETRY_LANGFUSE_BASE_URL = os.environ.get("LANGFUSE_BASE_URL", "")
TELEMETRY_LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
TELEMETRY_LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
TELEMETRY_LANGFUSE_PROJECT_ID = os.environ.get("LANGFUSE_PROJECT_ID", "")
